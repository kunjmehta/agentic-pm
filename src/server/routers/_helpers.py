"""Shared helpers for all routers.

Provides graph access, LangGraph config, state→response conversion, and
conversation persistence.  All helpers that previously lived at module level
in api.py are collected here so routers can import them without coupling to
the monolith.
"""

import asyncio
import functools
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, TypeVar

from fastapi import HTTPException, status

import src.server.app_state as _state
from src.common.utils.converters import df_to_records as _df_to_records  # noqa: F401  re-exported
from src.server.models.responses import (
    ExecutionResult,
    SemiAutoResponse,
    TaskPreviewResponse,
)
from src.common.utils import get_logger

logger = get_logger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


# ── Shared middleware ──────────────────────────────────────────────────────────


def handle_http_errors(fn: _F) -> _F:
    """Decorator: convert unhandled exceptions into HTTP 500 responses.

    Re-raises :class:`fastapi.HTTPException` unchanged so intentional HTTP
    errors (404, 503, etc.) pass through unmodified.  All other exceptions are
    caught, logged, and converted to a 500 with the exception message as the
    ``detail`` field.

    Usage::

        @router.get("/v1/something")
        @handle_http_errors
        async def my_endpoint():
            ...

    Args:
        fn: The async endpoint function to wrap.

    Returns:
        Wrapped async function with unified error handling.
    """
    @functools.wraps(fn)
    async def _wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception(f"[{fn.__name__}] Unhandled error: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    return _wrapper  # type: ignore[return-value]


async def run_in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a synchronous callable in a thread pool without blocking the event loop.

    Wraps :func:`asyncio.to_thread` with a readable name used across all
    routers instead of repeating the boilerplate.

    Args:
        fn: Synchronous callable to execute in a thread.
        *args: Positional arguments forwarded to ``fn``.
        **kwargs: Keyword arguments forwarded to ``fn``.

    Returns:
        Return value of ``fn(*args, **kwargs)``.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


# ── Graph access ───────────────────────────────────────────────────────────────


def _get_graph():
    """Return compiled graph or raise HTTP 503.

    Delegates to :func:`src.server.dependencies.get_graph` so there is a
    single canonical place for graph-access + error handling.
    """
    from src.server.helpers import get_graph
    return get_graph()


def _make_config(thread_id: str) -> Dict[str, Dict[str, str]]:
    """Build LangGraph config for a thread."""
    return {"configurable": {"thread_id": thread_id}}


# ── State → response conversion ────────────────────────────────────────────────


def _state_to_preview(state: dict, thread_id: str) -> TaskPreviewResponse:
    """Convert graph state to a TaskPreviewResponse (post-interrupt).

    Args:
        state: Current GraphState dict.
        thread_id: Thread identifier.

    Returns:
        TaskPreviewResponse with status="pending_approval".
    """
    preview = TaskPreviewResponse(
        status="pending_approval",
        thread_id=thread_id,
        conversation_id=state.get("conversation_id", ""),
        portfolio_reasoning=state.get("portfolio_reasoning"),
        quant_reasoning=state.get("quant_reasoning"),
        backtester_reasoning=state.get("backtester_reasoning"),
        order_reasoning=state.get("order_reasoning"),
        pm_review_notes=state.get("pm_review_notes"),
        portfolio_tasks=state.get("portfolio_task_queue") or [],
        quant_tasks=state.get("quant_task_queue") or [],
        backtester_tasks=state.get("backtester_task_queue") or [],
        order_tasks=state.get("order_task_queue") or [],
    )
    logger.info(f"[_state_to_preview] status={preview.status} thread={thread_id}")
    return preview


def _state_to_response(state: dict, thread_id: str, query: str, start_ms: int) -> SemiAutoResponse:
    """Convert final graph state to SemiAutoResponse.

    Args:
        state: Final GraphState dict.
        thread_id: Thread identifier.
        query: Original query string.
        start_ms: Unix timestamp (ms) when query was received.

    Returns:
        SemiAutoResponse Pydantic model.
    """
    exec_results = state.get("execution_results") or {}
    execution_result_list = [
        ExecutionResult(
            task_id=r.get("task_id", k),
            function_name=r.get("function_name", ""),
            status=r.get("status", "unknown"),
            result=r.get("result"),
            error=r.get("error"),
            duration_ms=(r.get("timing") or {}).get("duration_ms") if isinstance(r.get("timing"), dict) else None,
        )
        for k, r in exec_results.items()
    ]

    return SemiAutoResponse(
        query=query,
        thread_id=thread_id,
        conversation_id=state.get("conversation_id", ""),
        turn_number=state.get("turn_number") or 1,
        intent=state.get("intent"),
        symbol=state.get("symbol"),
        portfolio_reasoning=state.get("portfolio_reasoning"),
        quant_reasoning=state.get("quant_reasoning"),
        backtester_reasoning=state.get("backtester_reasoning"),
        final_response=state.get("final_response", "(no response generated)"),
        tasks_executed=len(exec_results),
        execution_results=execution_result_list,
        timestamp=datetime.now(timezone.utc).isoformat(),
        execution_time_ms=state.get("execution_time_ms"),
        status="success" if not state.get("error") else "error",
        error=state.get("error"),
    )


# ── Conversation persistence ───────────────────────────────────────────────────


def _load_conversation(thread_id: str) -> List[Dict[str, Any]]:
    """Load conversation turns from JSON file.

    Args:
        thread_id: Thread UUID used as filename.

    Returns:
        List of turn dicts; empty list if file not found or unreadable.
    """
    path = _state.CONVERSATIONS_DIR / f"{thread_id}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"[_load_conversation] could not read {path}: {exc}")
        return []


def _save_conversation(thread_id: str, turns: List[Dict[str, Any]]) -> None:
    """Atomically write conversation turns to JSON file.

    Uses a .tmp file + os.replace for crash-safe writes.

    Args:
        thread_id: Thread UUID used as filename.
        turns: List of turn dicts to persist.
    """
    _state.CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = _state.CONVERSATIONS_DIR / f"{thread_id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(turns, indent=2, default=str), encoding="utf-8")
    os.replace(str(tmp), str(path))
    logger.debug(f"[_save_conversation] saved {len(turns)} turn(s) → {path}")


# ── DAO lifecycle helpers ─────────────────────────────────────────────────────


@contextmanager
def dao_context(dao_class: Any) -> Generator[Any, None, None]:
    """Context manager that guarantees DAO.close() is called even on exception.

    Args:
        dao_class: DAO class to instantiate (e.g. AnalystDAO).

    Yields:
        Open DAO instance.
    """
    dao = dao_class()
    try:
        yield dao
    finally:
        dao.close()



