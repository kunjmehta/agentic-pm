"""Live telemetry SSE router — GET /v1/telemetry/stream/{thread_id}

Provides real-time Server-Sent Events (SSE) streaming of graph execution
telemetry for a specific thread. The frontend can subscribe to this stream
to display live progress updates during agent reasoning and task execution.

Event types:
    - node_start: Graph node started execution
    - node_end: Graph node completed execution
    - agent_thinking: LLM reasoning in progress (token-by-token)
    - task_execution: Tool/function execution events
    - graph_complete: Full graph execution finished
    - error: Execution error occurred
    - done: Stream termination signal

Endpoints:
    GET /v1/telemetry/stream/{thread_id}  SSE stream for thread telemetry
"""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.common.utils import get_logger
import src.semi_auto.app_state as app_state

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])


@router.get("/stream/{thread_id}")
async def stream_telemetry(thread_id: str):
    """Stream live execution telemetry for a thread via Server-Sent Events.

    This endpoint subscribes to the execution queue for a specific thread
    and streams telemetry events as they occur during graph execution.

    The stream begins when this endpoint is called and continues until
    the graph execution completes or an error occurs.

    Args:
        thread_id: Thread identifier to stream telemetry for.

    Returns:
        StreamingResponse with text/event-stream media type.

    Event format:
        data: {"type": "node_start", "node": "portfolio_reasoning_node", "timestamp": "..."}

        data: {"type": "agent_thinking", "agent": "portfolio", "token": "Analyzing..."}

        data: {"type": "task_execution", "task_id": "t1", "function": "get_bars", "status": "started"}

        data: {"type": "graph_complete", "status": "success", "duration_ms": 1234}

        data: {"type": "done"}

    Notes:
        - Events are emitted by graph nodes via app_state._execution_queues
        - The stream auto-terminates with {"type": "done"} event
        - Frontend LiveTelemetry component consumes this stream
        - If thread_id has no active execution, stream waits for events
    """
    logger.info(f"[telemetry/stream] starting SSE stream for thread={thread_id}")

    # Check if queue exists for this thread
    if thread_id not in app_state._execution_queues:
        logger.warning(
            f"[telemetry/stream] no execution queue for thread={thread_id}, "
            "this may be a pre-existing thread or the execution hasn't started yet"
        )
        # Create an empty queue - it may be populated later
        app_state._execution_queues[thread_id] = asyncio.Queue()

    queue = app_state._execution_queues[thread_id]

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events from the execution queue.

        Yields:
            SSE-formatted event strings (data: {...}\\n\\n).
        """
        def _fmt(data: dict) -> str:
            """Format dict as SSE event."""
            return f"data: {json.dumps(data)}\n\n"

        try:
            logger.info(f"[telemetry/stream] thread={thread_id} SSE generator started")

            # Send initial connection event
            yield _fmt({
                "type": "connection",
                "thread_id": thread_id,
                "message": "Telemetry stream connected",
            })

            # Stream events from queue until done sentinel
            while True:
                try:
                    # Wait for events with timeout to detect stale connections
                    item = await asyncio.wait_for(queue.get(), timeout=300.0)

                    if item == "__done__":
                        logger.info(f"[telemetry/stream] thread={thread_id} received done signal")
                        break

                    # Emit event to client
                    yield _fmt(item)

                except asyncio.TimeoutError:
                    # Send keepalive after 5min of inactivity
                    logger.debug(f"[telemetry/stream] thread={thread_id} keepalive")
                    yield _fmt({"type": "keepalive"})
                    continue

            # Send final done event
            yield _fmt({"type": "done"})
            logger.info(f"[telemetry/stream] thread={thread_id} stream complete")

        except asyncio.CancelledError:
            logger.info(f"[telemetry/stream] thread={thread_id} client disconnected")
            yield _fmt({"type": "disconnected", "reason": "client closed connection"})
            raise

        except Exception as exc:
            logger.error(
                f"[telemetry/stream] thread={thread_id} error: {exc}",
                exc_info=True
            )
            yield _fmt({"type": "error", "error": str(exc)})
            yield _fmt({"type": "done"})

        finally:
            # Cleanup queue when stream ends
            app_state._execution_queues.pop(thread_id, None)
            logger.info(f"[telemetry/stream] thread={thread_id} cleanup complete")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Helper functions for emitting telemetry events ────────────────────────


def emit_node_start(thread_id: str, node: str, label: str = "") -> None:
    """Emit a node_start telemetry event.

    Args:
        thread_id: Thread identifier.
        node: Node name (e.g., "portfolio_reasoning_node").
        label: Human-readable label (e.g., "PM planning tasks").
    """
    _emit_event(thread_id, {
        "type": "node_start",
        "node": node,
        "label": label,
    })


def emit_node_end(thread_id: str, node: str, label: str = "") -> None:
    """Emit a node_end telemetry event.

    Args:
        thread_id: Thread identifier.
        node: Node name.
        label: Human-readable label.
    """
    _emit_event(thread_id, {
        "type": "node_end",
        "node": node,
        "label": label,
    })


def emit_agent_thinking(thread_id: str, agent: str, token: str) -> None:
    """Emit an agent_thinking telemetry event (token-level streaming).

    Args:
        thread_id: Thread identifier.
        agent: Agent name (e.g., "portfolio", "quant").
        token: Single token from LLM output.
    """
    _emit_event(thread_id, {
        "type": "agent_thinking",
        "agent": agent,
        "token": token,
    })


def emit_task_execution(
    thread_id: str,
    task_id: str,
    function: str,
    status: str,
    duration_ms: int = 0,
    error: str = ""
) -> None:
    """Emit a task_execution telemetry event.

    Args:
        thread_id: Thread identifier.
        task_id: Task identifier.
        function: Function name being executed.
        status: "started" | "success" | "error".
        duration_ms: Execution duration in milliseconds.
        error: Error message if status is "error".
    """
    event = {
        "type": "task_execution",
        "task_id": task_id,
        "function": function,
        "status": status,
    }
    if duration_ms > 0:
        event["duration_ms"] = duration_ms
    if error:
        event["error"] = error

    _emit_event(thread_id, event)


def emit_graph_complete(
    thread_id: str,
    status: str,
    duration_ms: int = 0,
    tasks_executed: int = 0
) -> None:
    """Emit a graph_complete telemetry event.

    Args:
        thread_id: Thread identifier.
        status: "success" | "error" | "cancelled".
        duration_ms: Total graph execution duration.
        tasks_executed: Number of tasks executed.
    """
    _emit_event(thread_id, {
        "type": "graph_complete",
        "status": status,
        "duration_ms": duration_ms,
        "tasks_executed": tasks_executed,
    })


def _emit_event(thread_id: str, event: dict) -> None:
    """Internal helper to emit an event to the thread's telemetry queue.

    Args:
        thread_id: Thread identifier.
        event: Event dictionary to emit.
    """
    if thread_id not in app_state._execution_queues:
        # No active stream for this thread - skip event
        return

    queue = app_state._execution_queues[thread_id]

    # Use call_soon_threadsafe if we're in a different thread
    if app_state._event_loop:
        app_state._event_loop.call_soon_threadsafe(queue.put_nowait, event)
    else:
        # Fallback to direct put if event loop not available
        try:
            queue.put_nowait(event)
        except Exception as exc:
            logger.warning(f"[telemetry] failed to emit event: {exc}")


# ── Main block ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    """Smoke test: verify router routes are defined correctly."""
    print("=" * 60)
    print("routers/telemetry.py smoke tests")
    print("=" * 60)

    # Test 1: Route registration
    routes = [r.path for r in router.routes]
    expected = ["/v1/telemetry/stream/{thread_id}"]

    for path in expected:
        assert path in routes, f"Missing route: {path}"
        print(f"  [OK]  {path}")

    # Test 2: Helper functions callable
    print("\n[Helper Function Tests]")
    try:
        # These should not raise errors (no-op when queue doesn't exist)
        emit_node_start("test_thread", "test_node", "Test Node")
        print("  [OK]  emit_node_start callable")

        emit_node_end("test_thread", "test_node", "Test Node")
        print("  [OK]  emit_node_end callable")

        emit_agent_thinking("test_thread", "test_agent", "test token")
        print("  [OK]  emit_agent_thinking callable")

        emit_task_execution("test_thread", "t1", "test_func", "started")
        print("  [OK]  emit_task_execution callable")

        emit_graph_complete("test_thread", "success", 1000, 5)
        print("  [OK]  emit_graph_complete callable")

    except Exception as exc:
        print(f"  [FAIL] Helper functions: {exc}")
        raise

    print("\n[ALL OK] routers/telemetry.py smoke tests passed")
