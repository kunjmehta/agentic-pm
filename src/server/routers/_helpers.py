"""Shared helpers for all routers.

Provides graph access, LangGraph config, state→response conversion, and
conversation persistence.  All helpers that previously lived at module level
in api.py are collected here so routers can import them without coupling to
the monolith.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

import src.server.app_state as _state
from src.server.models.responses import (
    ExecutionResult,
    SemiAutoResponse,
    TaskPreviewResponse,
)
from src.common.utils import get_logger

logger = get_logger(__name__)


# ── Graph access ───────────────────────────────────────────────────────────────


def _get_graph():
    """Return compiled graph or raise HTTP 503.

    Reads from :data:`src.semi_auto.app_state._graph` so that the value
    set by the lifespan (or patched in tests) is always visible.
    """
    if _state._graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph not yet initialized",
        )
    return _state._graph


def _make_config(thread_id: str) -> dict:
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


def _load_conversation(thread_id: str) -> list:
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


def _save_conversation(thread_id: str, turns: list) -> None:
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


def _persist_reasoning_trace(thread_id: str, turn_number: int, state: dict) -> None:
    """Store LLM reasoning traces to analytics database for audit/compliance.

    Persists all reasoning outputs from the multi-agent workflow:
    - portfolio_reasoning (PM planning)
    - quant_reasoning (quant analyst signals)
    - backtester_reasoning (backtest results)
    - order_reasoning (order planning)
    - pm_review_notes (PM approval notes)
    - pm_decision_reasoning (post-execution order decision)

    Args:
        thread_id: Conversation thread identifier.
        turn_number: Sequential turn number within conversation.
        state: Current GraphState dict with reasoning traces.

    Note:
        Silently catches and logs any persistence errors to prevent blocking
        the main workflow. Analytics persistence is best-effort.
    """
    try:
        from src.common.dao import AnalyticsDAO

        dao = AnalyticsDAO()

        # Extract reasoning traces from state
        reasoning_data = {
            "thread_id": thread_id,
            "turn_number": turn_number,
            "conversation_id": state.get("conversation_id"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": state.get("query"),
            "intent": state.get("intent"),
            "symbol": state.get("symbol"),
            # Reasoning traces from each agent
            "portfolio_reasoning": state.get("portfolio_reasoning"),
            "quant_reasoning": state.get("quant_reasoning"),
            "backtester_reasoning": state.get("backtester_reasoning"),
            "order_reasoning": state.get("order_reasoning"),
            "pm_review_notes": state.get("pm_review_notes"),
            "pm_decision_reasoning": state.get("pm_decision_reasoning"),
            # Approval status
            "pm_review_approved": state.get("pm_review_approved"),
            "execute_orders": state.get("_execute_orders"),
            # Task counts
            "portfolio_task_count": len(state.get("portfolio_task_queue") or []),
            "quant_task_count": len(state.get("quant_task_queue") or []),
            "backtester_task_count": len(state.get("backtester_task_queue") or []),
            "order_task_count": len(state.get("order_task_queue") or []),
            # Execution metadata
            "error": state.get("error"),
            "execution_time_ms": state.get("execution_time_ms"),
        }

        # Save to analytics database
        dao.save_reasoning_trace(reasoning_data)
        dao.close()

        logger.info(
            f"[audit] Persisted reasoning trace: thread={thread_id} turn={turn_number} "
            f"intent={reasoning_data.get('intent')} symbol={reasoning_data.get('symbol')}"
        )

    except Exception as exc:
        # Non-blocking: log warning but don't fail the request
        logger.warning(
            f"[audit] Failed to persist reasoning trace for {thread_id}/{turn_number}: {exc}"
        )


# ── DAO response helpers ───────────────────────────────────────────────────────


def _df_to_records(df) -> list:
    """Convert a pandas DataFrame to a JSON-serialisable list of dicts.

    Returns an empty list if ``df`` is ``None`` or empty.
    """
    if df is None:
        return []
    try:
        if hasattr(df, "empty") and df.empty:
            return []
        return df.to_dict(orient="records")
    except Exception:
        return []
