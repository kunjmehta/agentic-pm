"""Agent / HITL router.

Handles the two-phase reasoning + execution flow, SSE streaming, conversation
history, agent state inspection, and the function registry listing.

Endpoints (all under /v1):
    POST /query                      Phase 1: reasoning → HITL interrupt
    POST /query/stream               SSE streaming variant of Phase 1
    POST /approve/{thread_id}        Phase 2: resume after approval (sync)
    POST /approve/stream/{thread_id} Phase 2: resume with live telemetry SSE
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

from src.server.state import make_initial_state
from src.server.models.responses import (
    ApprovalRequest,
    SemiAutoQueryRequest,
)
from src.server.registry.functions import get_registry_schema
from src.server.models.endpoints import (
    AgentStateResponse,
    ConversationResponse,
    RegistryResponse,
    RejectResponse,
)
from src.server.models.responses import SemiAutoResponse, TaskPreviewResponse
from src.server.routers._helpers import (
    _get_graph,
    _make_config,
    _state_to_preview,
    _state_to_response,
    _load_conversation,
    _save_conversation,
    _persist_reasoning_trace,
)
from src.common.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["agent"])

_REASONING_NODE_TO_AGENT = {
    "portfolio_reasoning_node": "portfolio",
    "quant_reasoning_node": "quant",
    "backtester_reasoning_node": "backtester",
}

_NODE_LABELS = {
    "classify_intent": "Classifying intent",
    "feedback_handler_node": "Processing user feedback",
    "portfolio_reasoning_node": "PM planning tasks",
    "quant_reasoning_node": "Quant analyst planning",
    "backtester_reasoning_node": "Backtester planning",
    "order_reasoning_node": "Order agent planning",
    "pm_review_node": "PM reviewing plan",
    "pm_decision_node": "PM deciding on orders",
    "executor_node": "Executing analysis tasks",
    "order_executor_node": "Executing orders",
    "synthesizer_node": "Synthesizing response",
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
        is_feedback=request.is_feedback,
    )

    logger.info(f"[api/query] thread={thread_id} query='{request.query[:60]}'")

    try:
        await graph.ainvoke(initial, config=config)
    except Exception as exc:
        logger.error(f"[api/query] graph invoke failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    state_snapshot = await graph.aget_state(config)
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
            "order_tasks": current_state.get("order_task_queue") or [],
            "order_reasoning": current_state.get("order_reasoning"),
        })
        _save_conversation(thread_id, turns)
        # Persist reasoning audit trail
        _persist_reasoning_trace(thread_id, current_state.get("turn_number", len(turns)), current_state)
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
    # Persist reasoning audit trail
    _persist_reasoning_trace(thread_id, current_state.get("turn_number", len(turns)), current_state)
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
        is_feedback=request.is_feedback,
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        def _fmt(data: dict) -> str:
            return f"data: {json.dumps(data, default=str)}\n\n"

        try:
            async for event in graph.astream_events(initial, config=config, version="v2"):
                event_type = event.get("event", "")
                node_name = (event.get("metadata") or {}).get("langgraph_node", "")
                agent = _REASONING_NODE_TO_AGENT.get(node_name)

                if event_type == "on_chain_start" and node_name in _NODE_LABELS:
                    yield _fmt({
                        "type": "node",
                        "data": {
                            "node": node_name,
                            "label": _NODE_LABELS[node_name],
                            "status": "started",
                        },
                    })

                elif event_type == "on_chain_end" and node_name in _NODE_LABELS:
                    yield _fmt({
                        "type": "node",
                        "data": {
                            "node": node_name,
                            "label": _NODE_LABELS[node_name],
                            "status": "done",
                        },
                    })

                elif event_type == "on_chat_model_stream" and agent:
                    chunk = (event.get("data") or {}).get("chunk")
                    token = getattr(chunk, "content", "") if chunk else ""
                    if token:
                        yield _fmt({"type": "thought_delta", "agent": agent, "token": token})

            state_snapshot = await graph.aget_state(config)
            snapshot = state_snapshot.values
            next_nodes = list(state_snapshot.next)

            for agent_key, reasoning_key, queue_key in [
                ("portfolio", "portfolio_reasoning", "portfolio_task_queue"),
                ("quant", "quant_reasoning", "quant_task_queue"),
                ("backtester", "backtester_reasoning", "backtester_task_queue"),
                ("order", "order_reasoning", "order_task_queue"),
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
                "order_tasks": snapshot.get("order_task_queue") or [],
                "order_reasoning": snapshot.get("order_reasoning"),
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
                    "order": snapshot.get("order_task_queue") or [],
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

    Works for both query-driven and autonomous trading flows:
    - Query-driven: Resumes from executor_node interrupt (analysis tasks)
    - Autonomous: Resumes from order_executor_node interrupt (autonomous orders)

    Optionally modifies task queues before resuming.

    Args:
        thread_id: Thread to resume (from query or autonomous signal processing).
        request: ApprovalRequest with optional modified task queues.

    Returns:
        SemiAutoResponse with final response and execution results.
    """
    graph = _get_graph()
    config = _make_config(thread_id)

    try:
        current_state = await graph.aget_state(config)
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
    if request.modified_order_tasks is not None:
        override_updates["order_task_queue"] = request.modified_order_tasks
        logger.info(f"[api/approve] overriding order_task_queue with {len(request.modified_order_tasks)} tasks")

    if override_updates:
        await graph.aupdate_state(config, override_updates)

    logger.info(f"[api/approve] resuming thread={thread_id}")

    try:
        final_state = await graph.ainvoke(None, config=config)
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
            t["execution_results"] = [r.model_dump(mode="json") for r in response.execution_results]
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
            "execution_results": [r.model_dump(mode="json") for r in response.execution_results],
        })
    _save_conversation(thread_id, turns)
    # Persist reasoning audit trail (post-execution)
    _persist_reasoning_trace(thread_id, turn_number, final_state)
    return response


# ── Phase 2 (streaming) ────────────────────────────────────────────────────────


@router.post("/v1/approve/stream/{thread_id}")
async def approve_stream_endpoint(thread_id: str, request: ApprovalRequest):
    """Phase 2 SSE: Resume graph after approval and stream per-task telemetry.

    Event types emitted:
    - ``tool_call``: ``{task_id, function_name, status: "started"|"success"|"error", duration_ms}``
    - ``telemetry``: execution summary on completion
    - ``error``: exception during graph run
    - ``done``: always last

    Args:
        thread_id: Thread to resume.
        request: ApprovalRequest with optional modified task queues.
    """
    import src.server.app_state as _state

    graph = _get_graph()
    config = _make_config(thread_id)

    try:
        current_state = await graph.aget_state(config)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Thread not found: {exc}")

    state_values = current_state.values if current_state else {}

    override_updates = {}
    if request.modified_portfolio_tasks is not None:
        override_updates["portfolio_task_queue"] = request.modified_portfolio_tasks
    if request.modified_quant_tasks is not None:
        override_updates["quant_task_queue"] = request.modified_quant_tasks
    if request.modified_backtester_tasks is not None:
        override_updates["backtester_task_queue"] = request.modified_backtester_tasks
    if request.modified_order_tasks is not None:
        override_updates["order_task_queue"] = request.modified_order_tasks

    if override_updates:
        await graph.aupdate_state(config, override_updates)

    # Create per-thread execution event queue for telemetry bridging
    q: asyncio.Queue = asyncio.Queue()
    _state._execution_queues[thread_id] = q

    logger.info(f"[api/approve/stream] resuming thread={thread_id}")

    async def event_generator() -> AsyncGenerator[str, None]:
        def _fmt(data: dict) -> str:
            return f"data: {json.dumps(data, default=str)}\n\n"

        async def _run_graph():
            try:
                final = await graph.ainvoke(None, config=config)
                return final
            finally:
                # Signal SSE generator that execution is complete
                await q.put("__done__")

        graph_task = asyncio.create_task(_run_graph())

        try:
            while True:
                item = await q.get()
                if item == "__done__":
                    break
                yield _fmt(item)

            final_state = await graph_task
            original_query = state_values.get("query", "")
            response = _state_to_response(final_state, thread_id, original_query, 0)

            # Persist conversation
            turns = _load_conversation(thread_id)
            turn_number = final_state.get("turn_number") or 1
            matched = False
            for t in reversed(turns):
                if t.get("turn_number") == turn_number and t.get("status") == "pending_approval":
                    t["status"] = response.status
                    t["final_response"] = response.final_response
                    t["tasks_executed"] = response.tasks_executed
                    t["execution_results"] = [r.model_dump(mode="json") for r in response.execution_results]
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
                    "execution_results": [r.model_dump(mode="json") for r in response.execution_results],
                })
            _save_conversation(thread_id, turns)

            yield _fmt({
                "type": "telemetry",
                "data": {
                    "status": response.status,
                    "tasks_executed": response.tasks_executed,
                    "final_response": response.final_response,
                    "execution_results": [r.model_dump() for r in response.execution_results],
                    "tool_timings": final_state.get("tool_timings") or [],
                },
            })
            yield _fmt({"type": "done"})

        except Exception as exc:
            logger.error(f"[api/approve/stream] error: {exc}", exc_info=True)
            yield _fmt({"type": "error", "content": str(exc)})
            yield _fmt({"type": "done"})
            if not graph_task.done():
                graph_task.cancel()
        finally:
            _state._execution_queues.pop(thread_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Reject ─────────────────────────────────────────────────────────────────────


@router.post("/v1/reject/{thread_id}", response_model=RejectResponse)
async def reject_endpoint(thread_id: str):
    """Cancel pending execution for a thread.

    Works for both query-driven and autonomous trading flows.
    Simply cancels the pending execution without resuming the graph.

    Args:
        thread_id: Thread to reject (from query or autonomous signal processing).

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
        # Return most recent 'limit' turns
        if limit and len(turns) > limit:
            turns = turns[-limit:]
        return {"thread_id": thread_id, "turns": turns, "count": len(turns)}
    except Exception as exc:
        logger.error(f"[conversations/{thread_id}] error loading conversation: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load conversation: {str(exc)}")


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
        state = await graph.aget_state(config)
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
