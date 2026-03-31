"""FastAPI server for the semi-auto multi-agent portfolio manager.

Runs on port 8000.

Two-phase HITL flow:
  POST /v1/query       → runs reasoning nodes → returns TaskPreviewResponse (status="pending_approval")
  POST /v1/approve/{id} → resumes graph → returns SemiAutoResponse (status="success")
  POST /v1/reject/{id}  → cancels pending execution

Endpoints:
    GET  /                              - API info
    GET  /v1/health                     - Liveness check
    GET  /v1/health/detailed            - Per-component health
    POST /v1/query                      - Invoke graph (Phase 1: reasoning → HITL interrupt)
    POST /v1/query/stream               - SSE stream with per-node events
    POST /v1/approve/{thread_id}        - Resume graph after HITL approval (Phase 2: execute)
    POST /v1/reject/{thread_id}         - Cancel pending execution
    GET  /v1/conversations/{thread_id}  - Load interaction history
    GET  /v1/registry                   - List FUNCTION_REGISTRY keys + param schemas
    GET  /v1/portfolio/status           - Direct portfolio status
    GET  /v1/agent/state/{thread_id}    - Graph checkpoint state
    POST /v1/admin/cleanup              - Delete expired threads
    GET  /v1/admin/stats                - Database statistics
"""

import asyncio
import json
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.semi_auto.graph import build_graph
from src.semi_auto.state import make_initial_state
from src.semi_auto.models.responses import (
    ApprovalRequest,
    ExecutionResult,
    SemiAutoQueryRequest,
    SemiAutoResponse,
    TaskPreviewResponse,
)
from src.semi_auto.registry.functions import get_registry_schema
from src.common.utils import get_logger

logger = get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

CONVERSATIONS_DIR = Path("data/conversations")

# ── Shared state ───────────────────────────────────────────────────────────────

_graph = None


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global _graph

    logger.info("=" * 70)
    logger.info("Starting Semi-Auto Portfolio Manager API (port 8000)...")
    logger.info("=" * 70)

    logger.info("Compiling LangGraph...")
    _graph = build_graph()
    logger.info("[OK] Graph compiled with HITL interrupt_before=['executor_node']")

    logger.info("=" * 70)
    logger.info("API Server: http://localhost:8000")
    logger.info("Interactive Docs: http://localhost:8000/docs")
    logger.info("=" * 70)

    yield

    logger.info("Shutting down Semi-Auto API...")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Semi-Auto Portfolio Manager",
    description=(
        "LangGraph multi-agent system with reasoning agents, task queues, "
        "human-in-the-loop approval, and parallel function execution."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_graph():
    """Get compiled graph or raise 503."""
    if _graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph not yet initialized",
        )
    return _graph


def _make_config(thread_id: str) -> dict:
    """Build LangGraph config for a thread."""
    return {"configurable": {"thread_id": thread_id}}


def _state_to_preview(state: dict, thread_id: str) -> TaskPreviewResponse:
    """Convert graph state to a TaskPreviewResponse.

    Args:
        state: Current GraphState dict (post-interrupt).
        thread_id: Thread identifier.

    Returns:
        TaskPreviewResponse Pydantic model with status="pending_approval".
    """
    preview = TaskPreviewResponse(
        status="pending_approval",  # explicit — required for frontend HITL gate
        thread_id=thread_id,
        conversation_id=state.get("conversation_id", ""),
        portfolio_reasoning=state.get("portfolio_reasoning"),
        quant_reasoning=state.get("quant_reasoning"),
        backtester_reasoning=state.get("backtester_reasoning"),
        pm_review_notes=state.get("pm_review_notes"),
        portfolio_tasks=state.get("portfolio_task_queue") or [],
        quant_tasks=state.get("quant_task_queue") or [],
        backtester_tasks=state.get("backtester_task_queue") or [],
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


def _load_conversation(thread_id: str) -> list:
    """Load conversation turns from JSON file.

    Args:
        thread_id: Thread UUID used as filename.

    Returns:
        List of turn dicts; empty list if file not found or unreadable.
    """
    path = CONVERSATIONS_DIR / f"{thread_id}.json"
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
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = CONVERSATIONS_DIR / f"{thread_id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(turns, indent=2, default=str), encoding="utf-8")
    os.replace(str(tmp), str(path))
    logger.debug(f"[_save_conversation] saved {len(turns)} turn(s) → {path}")


# ── Endpoints ──────────────────────────────────────────────────────────────────


@app.get("/")
async def root():
    """API info."""
    return {
        "name": "Semi-Auto Portfolio Manager",
        "version": "1.0.0",
        "description": "LangGraph multi-agent with reasoning agents + HITL task approval",
        "port": 8002,
        "endpoints": {
            "POST /v1/query": "Phase 1: reasoning → HITL interrupt (returns task preview)",
            "POST /v1/approve/{thread_id}": "Phase 2: approve tasks → execute → synthesize",
            "POST /v1/reject/{thread_id}": "Cancel pending execution",
            "GET /v1/registry": "List registered functions",
            "GET /v1/health": "Liveness check",
        },
    }


@app.get("/v1/health")
async def health():
    """Basic liveness check."""
    return {"status": "ok", "graph_ready": _graph is not None, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/v1/health/detailed")
async def health_detailed():
    """Per-component health check."""
    components = {}

    # Graph
    components["graph"] = {"status": "ok" if _graph is not None else "not_ready"}

    # Registry
    try:
        from src.semi_auto.registry.functions import AVAILABLE_FUNCTIONS
        components["registry"] = {"status": "ok", "functions": len(AVAILABLE_FUNCTIONS)}
    except Exception as e:
        components["registry"] = {"status": "error", "error": str(e)}

    # Portfolio DB
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        snap = dao.get_latest_snapshot()
        dao.close()
        components["portfolio_db"] = {"status": "ok", "latest_snapshot": snap is not None}
    except Exception as e:
        components["portfolio_db"] = {"status": "error", "error": str(e)}

    overall = "ok" if all(c.get("status") == "ok" for c in components.values()) else "degraded"
    return {"status": overall, "components": components, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/v1/query")
async def query_endpoint(request: SemiAutoQueryRequest):
    """Phase 1: Run reasoning nodes and return TaskPreviewResponse for HITL approval.

    The graph runs through context_node → classify_intent → market_hours_guard →
    portfolio_reasoning_node → (quant_reasoning_node / backtester_reasoning_node in parallel)
    then INTERRUPTS before executor_node.

    Returns:
        TaskPreviewResponse with task queues and reasoning traces.
        If guard short-circuited, returns SemiAutoResponse directly.

    Args:
        request: SemiAutoQueryRequest.
    """
    graph = _get_graph()

    thread_id = request.thread_id or str(uuid.uuid4())
    conversation_id = request.conversation_id or str(uuid.uuid4())
    config = _make_config(thread_id)

    initial = make_initial_state(
        query=request.query,
        thread_id=thread_id,
        backtest_mode=request.backtest_mode,
        conversation_id=conversation_id,
    )

    logger.info(f"[api/query] thread={thread_id} query='{request.query[:60]}'")

    try:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: graph.invoke(initial, config=config)
        )
    except Exception as exc:
        logger.error(f"[api/query] graph invoke failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    # Use get_state().next — the authoritative LangGraph interrupt signal.
    # graph.invoke() return value is unreliable for detecting interrupts because
    # it returns only the last node's state diff, not the full accumulated state.
    state_snapshot = graph.get_state(config)
    current_state = state_snapshot.values
    next_nodes = list(state_snapshot.next)

    logger.info(f"[api/query] thread={thread_id} next_nodes={next_nodes}")

    # Interrupted before executor_node → HITL pending approval
    if "executor_node" in next_nodes:
        preview = _state_to_preview(current_state, thread_id)
        # Persist Phase 1 turn
        turns = _load_conversation(thread_id)
        turns.append({
            "turn_number": current_state.get("turn_number", len(turns) + 1),
            "query": request.query,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "pending_approval",
            "intent": current_state.get("intent"),
            "symbol": current_state.get("symbol"),
            "portfolio_reasoning": current_state.get("portfolio_reasoning"),
            "quant_reasoning": current_state.get("quant_reasoning"),
            "backtester_reasoning": current_state.get("backtester_reasoning"),
            "pm_review_notes": current_state.get("pm_review_notes"),
            "portfolio_tasks": current_state.get("portfolio_task_queue") or [],
            "quant_tasks": current_state.get("quant_task_queue") or [],
            "backtester_tasks": current_state.get("backtester_task_queue") or [],
        })
        _save_conversation(thread_id, turns)
        return preview

    # Guard short-circuit (market closed, routing_error, etc.) → respond directly
    turns = _load_conversation(thread_id)
    turns.append({
        "turn_number": current_state.get("turn_number", len(turns) + 1),
        "query": request.query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "intent": current_state.get("intent"),
        "symbol": current_state.get("symbol"),
        "final_response": current_state.get("final_response"),
    })
    _save_conversation(thread_id, turns)
    return _state_to_response(current_state, thread_id, request.query, 0)


@app.post("/v1/approve/{thread_id}")
async def approve_endpoint(thread_id: str, request: ApprovalRequest):
    """Phase 2: Resume graph after HITL approval.

    Optionally modifies task queues before resuming (if request provides overrides).
    Resumes from MemorySaver checkpoint at executor_node.

    Args:
        thread_id: Thread to resume.
        request: ApprovalRequest with optional modified task queues.

    Returns:
        SemiAutoResponse with final response and execution results.
    """
    graph = _get_graph()
    config = _make_config(thread_id)

    # Load current state from checkpoint
    try:
        current_state = graph.get_state(config)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Thread not found: {exc}")

    state_values = current_state.values if current_state else {}

    # Apply optional overrides to task queues
    override_updates = {}
    if request.modified_portfolio_tasks is not None:
        override_updates["portfolio_task_queue"] = request.modified_portfolio_tasks
        logger.info(f"[api/approve] overriding portfolio_task_queue with {len(request.modified_portfolio_tasks)} tasks")
    if request.modified_quant_tasks is not None:
        override_updates["quant_task_queue"] = request.modified_quant_tasks
    if request.modified_backtester_tasks is not None:
        override_updates["backtester_task_queue"] = request.modified_backtester_tasks

    if override_updates:
        graph.update_state(config, override_updates)

    logger.info(f"[api/approve] resuming thread={thread_id}")

    try:
        final_state = await asyncio.get_event_loop().run_in_executor(
            None, lambda: graph.invoke(None, config=config)
        )
    except Exception as exc:
        logger.error(f"[api/approve] graph resume failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    original_query = state_values.get("query", "")
    response = _state_to_response(final_state, thread_id, original_query, 0)

    # Update or append Phase 2 execution data to persisted turn
    turns = _load_conversation(thread_id)
    turn_number = final_state.get("turn_number") or 1
    matched = False
    for t in reversed(turns):
        if t.get("turn_number") == turn_number and t.get("status") == "pending_approval":
            t["status"] = response.status
            t["final_response"] = response.final_response
            t["tasks_executed"] = response.tasks_executed
            t["execution_results"] = [r.model_dump() for r in response.execution_results]
            t["timestamp_completed"] = datetime.now(timezone.utc).isoformat()
            matched = True
            break
    if not matched:
        turns.append({
            "turn_number": turn_number,
            "query": original_query,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": response.status,
            "final_response": response.final_response,
            "tasks_executed": response.tasks_executed,
            "execution_results": [r.model_dump() for r in response.execution_results],
        })
    _save_conversation(thread_id, turns)
    return response


@app.post("/v1/reject/{thread_id}")
async def reject_endpoint(thread_id: str):
    """Cancel pending execution for a thread.

    Args:
        thread_id: Thread to cancel.

    Returns:
        Cancellation confirmation.
    """
    logger.info(f"[api/reject] thread={thread_id} cancelled by user")
    return {
        "status": "cancelled",
        "thread_id": thread_id,
        "message": "Task execution cancelled. No functions were executed.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


_REASONING_NODE_TO_AGENT = {
    "portfolio_reasoning_node": "portfolio",
    "quant_reasoning_node": "quant",
    "backtester_reasoning_node": "backtester",
}


@app.post("/v1/query/stream")
async def query_stream(request: SemiAutoQueryRequest):
    """SSE stream: runs Phase 1 (reasoning) and emits token-level thought events.

    Emits events:
      {"type": "thought_delta", "agent": "portfolio", "token": "..."}  ← per LLM token
      {"type": "reasoning", "agent": "portfolio", "content": "...", "tasks": [...]}
      {"type": "reasoning", "agent": "quant", "content": "..."}
      {"type": "interrupt", "message": "...", "thread_id": "...", "tasks_preview": {...}}
      {"type": "text", "content": "..."}  ← on guard short-circuit
      {"type": "error", "content": "..."}
      {"type": "done"}

    Args:
        request: SemiAutoQueryRequest.
    """
    graph = _get_graph()
    thread_id = request.thread_id or str(uuid.uuid4())
    conversation_id = request.conversation_id or str(uuid.uuid4())
    config = _make_config(thread_id)

    initial = make_initial_state(
        query=request.query,
        thread_id=thread_id,
        backtest_mode=request.backtest_mode,
        conversation_id=conversation_id,
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events as graph executes, including per-token thought_delta."""
        def _format_event(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

        try:
            # Stream events from the graph as LLM tokens arrive
            async for event in graph.astream_events(initial, config=config, version="v2"):
                event_type = event.get("event", "")
                metadata = event.get("metadata", {})
                node_name = metadata.get("langgraph_node", "")
                agent = _REASONING_NODE_TO_AGENT.get(node_name)

                # Emit token-level thought_delta for reasoning nodes only
                if event_type == "on_chat_model_stream" and agent:
                    chunk = event.get("data", {}).get("chunk")
                    token = getattr(chunk, "content", "") if chunk else ""
                    if token:
                        yield _format_event({
                            "type": "thought_delta",
                            "agent": agent,
                            "token": token,
                        })

            # After stream ends: use get_state() for authoritative results
            state_snapshot = graph.get_state(config)
            snapshot = state_snapshot.values
            next_nodes = list(state_snapshot.next)

            # Emit structured reasoning summaries (full plan + task lists)
            for agent_key, reasoning_key, queue_key in [
                ("portfolio", "portfolio_reasoning", "portfolio_task_queue"),
                ("quant", "quant_reasoning", "quant_task_queue"),
                ("backtester", "backtester_reasoning", "backtester_task_queue"),
            ]:
                reasoning = snapshot.get(reasoning_key)
                tasks = snapshot.get(queue_key) or []
                if reasoning or tasks:
                    yield _format_event({
                        "type": "reasoning",
                        "agent": agent_key,
                        "content": reasoning or "",
                        "tasks": tasks,
                    })

            # Guard short-circuit (market closed, routing_error, etc.)
            if "executor_node" not in next_nodes:
                yield _format_event({
                    "type": "text",
                    "content": snapshot.get("final_response", "(no response)"),
                })
                yield _format_event({"type": "done"})
                return

            # Interrupted before executor_node → HITL approval
            yield _format_event({
                "type": "interrupt",
                "message": "Reasoning complete. Call POST /v1/approve/{thread_id} to execute.",
                "thread_id": thread_id,
                "tasks_preview": {
                    "portfolio": snapshot.get("portfolio_task_queue") or [],
                    "quant": snapshot.get("quant_task_queue") or [],
                    "backtester": snapshot.get("backtester_task_queue") or [],
                },
            })
            yield _format_event({"type": "done"})

        except Exception as exc:
            logger.error(f"[api/stream] error: {exc}", exc_info=True)
            yield _format_event({"type": "error", "content": str(exc)})
            yield _format_event({"type": "done"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/v1/conversations/{thread_id}")
async def get_conversation(thread_id: str, limit: int = Query(default=10, ge=1, le=50)):
    """Load interaction history for a thread from JSON file.

    Args:
        thread_id: Conversation thread UUID.
        limit: Max turns to return (most recent).

    Returns:
        Dict with thread_id, turns list, and count.
    """
    try:
        turns = _load_conversation(thread_id)
        turns = turns[-limit:]
        return {"thread_id": thread_id, "turns": turns, "count": len(turns)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/v1/registry")
async def get_registry():
    """List all registered functions with their parameter schemas.

    Returns:
        Dict of function_name → parameter documentation.
    """
    return {"registry": get_registry_schema(), "count": 11}


@app.get("/v1/portfolio/status")
async def portfolio_status():
    """Direct portfolio status without agent reasoning.

    Returns:
        Portfolio status dict from Alpaca.
    """
    try:
        from src.agentic.agents.portfolio.skills.portfoliostatus.status import get_portfolio_status_core
        result = get_portfolio_status_core()
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/v1/agent/state/{thread_id}")
async def get_agent_state(thread_id: str):
    """Return graph checkpoint state for a thread.

    Args:
        thread_id: Thread identifier.

    Returns:
        Current graph state values including task queues.
    """
    graph = _get_graph()
    config = _make_config(thread_id)
    try:
        state = graph.get_state(config)
        if state is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        values = dict(state.values) if state.values else {}
        # Remove large/sensitive fields
        for key in ("prior_turns",):
            values.pop(key, None)
        return {"thread_id": thread_id, "state": values}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/v1/admin/cleanup")
async def admin_cleanup(dry_run: bool = Query(default=True)):
    """Delete expired threads from portfolio DB.

    Args:
        dry_run: If True, only count; don't delete.

    Returns:
        Cleanup result dict.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        result = dao.cleanup_expired_threads(dry_run=dry_run)
        dao.close()
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/v1/admin/stats")
async def admin_stats():
    """Return basic database statistics.

    Returns:
        Dict with row counts per table.
    """
    stats: Dict[str, Any] = {}
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        stats["portfolio_db"] = {
            "interactions": len(dao.get_interaction_history("", "semi_auto_pm", 9999)),
        }
        snap = dao.get_latest_snapshot()
        stats["portfolio_db"]["latest_snapshot"] = snap.get("date_only") if snap else None
        dao.close()
    except Exception as e:
        stats["portfolio_db"] = {"error": str(e)}

    return {"stats": stats, "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
