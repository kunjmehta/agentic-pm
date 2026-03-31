"""Agent / HITL router.

Handles the two-phase reasoning + execution flow, SSE streaming, conversation
history, agent state inspection, and the function registry listing.

Endpoints (all under /v1):
    POST /query                      Phase 1: reasoning → HITL interrupt
    POST /query/stream               SSE streaming variant of Phase 1
    POST /approve/{thread_id}        Phase 2: resume after approval
    POST /reject/{thread_id}         Cancel pending execution
    GET  /conversations/{thread_id}  Interaction history
    GET  /agent/state/{thread_id}    Graph checkpoint state
    GET  /registry                   Function registry schema
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.semi_auto.state import make_initial_state
from src.semi_auto.models.responses import (
    ApprovalRequest,
    SemiAutoQueryRequest,
)
from src.semi_auto.registry.functions import get_registry_schema
from src.semi_auto.models.endpoints import (
    AgentStateResponse,
    ConversationResponse,
    RegistryResponse,
    RejectResponse,
)
from src.semi_auto.models.responses import SemiAutoResponse, TaskPreviewResponse
from src.semi_auto.routers._helpers import (
    _get_graph,
    _make_config,
    _state_to_preview,
    _state_to_response,
    _load_conversation,
    _save_conversation,
)
from src.common.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["agent"])

_REASONING_NODE_TO_AGENT = {
    "portfolio_reasoning_node": "portfolio",
    "quant_reasoning_node": "quant",
    "backtester_reasoning_node": "backtester",
}


# ── Phase 1: reasoning → HITL interrupt ───────────────────────────────────────


@router.post("/v1/query")
async def query_endpoint(request: SemiAutoQueryRequest):
    """Phase 1: Run reasoning nodes and return TaskPreviewResponse for HITL approval.

    The graph runs through context_node → classify_intent → market_hours_guard →
    portfolio_reasoning_node → (quant_reasoning_node / backtester_reasoning_node in
    parallel) then INTERRUPTS before executor_node.

    Returns:
        TaskPreviewResponse with task queues and reasoning traces.
        If a guard short-circuited, returns SemiAutoResponse directly.
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

    state_snapshot = graph.get_state(config)
    current_state = state_snapshot.values
    next_nodes = list(state_snapshot.next)

    logger.info(f"[api/query] thread={thread_id} next_nodes={next_nodes}")

    if "executor_node" in next_nodes:
        preview = _state_to_preview(current_state, thread_id)
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

    # Guard short-circuit
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


# ── Phase 1 (streaming) ────────────────────────────────────────────────────────


@router.post("/v1/query/stream")
async def query_stream(request: SemiAutoQueryRequest):
    """SSE stream: runs Phase 1 reasoning and emits token-level thought events.

    Event types emitted:
    - ``thought_delta``: per-LLM-token from reasoning nodes
    - ``reasoning``: full plan + task list per agent
    - ``interrupt``: HITL gate reached
    - ``text``: guard short-circuit response
    - ``error``: exception
    - ``done``: always last
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
        def _fmt(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

        try:
            async for event in graph.astream_events(initial, config=config, version="v2"):
                event_type = event.get("event", "")
                node_name = (event.get("metadata") or {}).get("langgraph_node", "")
                agent = _REASONING_NODE_TO_AGENT.get(node_name)

                if event_type == "on_chat_model_stream" and agent:
                    chunk = (event.get("data") or {}).get("chunk")
                    token = getattr(chunk, "content", "") if chunk else ""
                    if token:
                        yield _fmt({"type": "thought_delta", "agent": agent, "token": token})

            state_snapshot = graph.get_state(config)
            snapshot = state_snapshot.values
            next_nodes = list(state_snapshot.next)

            for agent_key, reasoning_key, queue_key in [
                ("portfolio", "portfolio_reasoning", "portfolio_task_queue"),
                ("quant", "quant_reasoning", "quant_task_queue"),
                ("backtester", "backtester_reasoning", "backtester_task_queue"),
            ]:
                reasoning = snapshot.get(reasoning_key)
                tasks = snapshot.get(queue_key) or []
                if reasoning or tasks:
                    yield _fmt({"type": "reasoning", "agent": agent_key, "content": reasoning or "", "tasks": tasks})

            if "executor_node" not in next_nodes:
                turns = _load_conversation(thread_id)
                turns.append({
                    "turn_number": snapshot.get("turn_number", len(turns) + 1),
                    "query": request.query,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "complete",
                    "intent": snapshot.get("intent"),
                    "symbol": snapshot.get("symbol"),
                    "final_response": snapshot.get("final_response"),
                })
                _save_conversation(thread_id, turns)
                yield _fmt({"type": "text", "content": snapshot.get("final_response", "(no response)")})
                yield _fmt({"type": "done"})
                return

            turns = _load_conversation(thread_id)
            turns.append({
                "turn_number": snapshot.get("turn_number", len(turns) + 1),
                "query": request.query,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "pending_approval",
                "intent": snapshot.get("intent"),
                "symbol": snapshot.get("symbol"),
                "portfolio_reasoning": snapshot.get("portfolio_reasoning"),
                "quant_reasoning": snapshot.get("quant_reasoning"),
                "backtester_reasoning": snapshot.get("backtester_reasoning"),
                "pm_review_notes": snapshot.get("pm_review_notes"),
                "portfolio_tasks": snapshot.get("portfolio_task_queue") or [],
                "quant_tasks": snapshot.get("quant_task_queue") or [],
                "backtester_tasks": snapshot.get("backtester_task_queue") or [],
            })
            _save_conversation(thread_id, turns)
            yield _fmt({
                "type": "interrupt",
                "message": "Reasoning complete. Call POST /v1/approve/{thread_id} to execute.",
                "thread_id": thread_id,
                "tasks_preview": {
                    "portfolio": snapshot.get("portfolio_task_queue") or [],
                    "quant": snapshot.get("quant_task_queue") or [],
                    "backtester": snapshot.get("backtester_task_queue") or [],
                },
            })
            yield _fmt({"type": "done"})

        except Exception as exc:
            logger.error(f"[api/stream] error: {exc}", exc_info=True)
            yield _fmt({"type": "error", "content": str(exc)})
            yield _fmt({"type": "done"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Phase 2: resume after approval ────────────────────────────────────────────


@router.post("/v1/approve/{thread_id}")
async def approve_endpoint(thread_id: str, request: ApprovalRequest):
    """Phase 2: Resume graph after HITL approval.

    Optionally modifies task queues before resuming.

    Args:
        thread_id: Thread to resume.
        request: ApprovalRequest with optional modified task queues.

    Returns:
        SemiAutoResponse with final response and execution results.
    """
    graph = _get_graph()
    config = _make_config(thread_id)

    try:
        current_state = graph.get_state(config)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Thread not found: {exc}")

    state_values = current_state.values if current_state else {}

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


# ── Reject ─────────────────────────────────────────────────────────────────────


@router.post("/v1/reject/{thread_id}", response_model=RejectResponse)
async def reject_endpoint(thread_id: str):
    """Cancel pending execution for a thread.

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


# ── Conversation history ───────────────────────────────────────────────────────


@router.get("/v1/conversations/{thread_id}", response_model=ConversationResponse)
async def get_conversation(thread_id: str, limit: int = Query(default=10, ge=1, le=50)):
    """Load interaction history for a thread from JSON file.

    Args:
        thread_id: Conversation thread UUID.
        limit: Max turns to return (most recent, 1–50).

    Returns:
        Dict with thread_id, turns list, and count.
    """
    try:
        turns = _load_conversation(thread_id)
        turns = turns[-limit:]
        return {"thread_id": thread_id, "turns": turns, "count": len(turns)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Agent state ────────────────────────────────────────────────────────────────


@router.get("/v1/agent/state/{thread_id}", response_model=AgentStateResponse)
async def get_agent_state(thread_id: str):
    """Return graph checkpoint state for a thread.

    Args:
        thread_id: Thread identifier.

    Returns:
        Current graph state values (sensitive fields stripped).
    """
    graph = _get_graph()
    config = _make_config(thread_id)
    try:
        state = graph.get_state(config)
        if state is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        values = dict(state.values) if state.values else {}
        for key in ("prior_turns",):
            values.pop(key, None)
        return {"thread_id": thread_id, "state": values}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Registry ───────────────────────────────────────────────────────────────────


@router.get("/v1/registry", response_model=RegistryResponse)
async def get_registry():
    """List all registered functions with their parameter schemas.

    Returns:
        Dict of function_name → parameter documentation.
    """
    schema = get_registry_schema()
    return {"registry": schema, "count": len(schema)}
