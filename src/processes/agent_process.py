"""Agent process entry point — autonomous signal processing loop.

Runs in its own event loop, separate from the API server.

Responsibilities:
- Periodic signal aggregation (every N minutes per config)
- LangGraph invocation for autonomous PM decision-making
- HITL pause at order_executor_node
- User approves/rejects via /v1/approve or /v1/reject on the API process

Usage:
    python -m src.processes.agent_process
    # or
    python src/processes/agent_process.py

Note:
    Requires the API process to be running at localhost:8000.
    All DB reads (analysis, portfolio) are proxied through the API to avoid
    DuckDB's single-writer-per-file constraint on Windows.
"""

import asyncio
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

from src.common.utils import get_logger, config as app_config
from src.server.state import make_initial_state

# Agent process does not open analysis or portfolio DBs directly — those are
# owned by the API process.  Only market and backtest are opened here (read-only)
# when registry functions need bar/indicator data.
from src.common.db_connections import configure_read_only
configure_read_only(["market", "backtest"])

logger = get_logger(__name__)

_API_BASE = "http://localhost:8000"


async def _fetch_signal_batch(
    min_confidence: float,
    lookback_minutes: int,
    client: httpx.AsyncClient,
) -> Optional[dict]:
    """Fetch a signal batch from the API process.

    Delegates all DB access to the API (which owns analysis + portfolio write
    connections) so this process never opens those files directly.

    Args:
        min_confidence: Minimum signal confidence threshold (0–1).
        lookback_minutes: Lookback window for actionable signals.
        client: Shared async HTTP client.

    Returns:
        Raw batch dict (suitable for Pydantic model_validate) or None.
    """
    resp = await client.get(
        f"{_API_BASE}/v1/agent/signal-batch",
        params={"min_confidence": min_confidence, "lookback_minutes": lookback_minutes},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json().get("batch")


async def _run_signal_processing_cycle(
    batch_data: Optional[dict],
    graph,
    config: dict,
) -> None:
    """Execute a single autonomous signal-processing cycle.

    Args:
        batch_data: Raw signal batch dict from the API, or None.
        graph: Compiled LangGraph instance.
        config: Autonomous trading config dict from app config.
    """
    if not batch_data or not batch_data.get("signals"):
        logger.info("[autonomous] No actionable signals found")
        return

    from src.server.models.autonomous_signals import SignalBatch
    signal_batch = SignalBatch.model_validate(batch_data)

    logger.info(
        f"[autonomous] Batch {signal_batch.batch_id} — {len(signal_batch.signals)} signal(s)"
    )

    thread_id = f"autonomous_{int(time.time())}"
    initial_state = make_initial_state(
        query="[Autonomous Trading] Processing periodic signals",
        thread_id=thread_id,
        backtest_mode=False,
    )
    initial_state["signal_batch"] = signal_batch.model_dump()
    initial_state["autonomous_mode"] = True

    langgraph_config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(initial_state, langgraph_config)

    if result.get("_execute_orders"):
        logger.info(
            f"[autonomous] Orders ready for HITL approval (thread_id={thread_id}): "
            f"{result.get('pm_decision_reasoning')}"
        )
    else:
        logger.info(f"[autonomous] No orders generated: {result.get('pm_decision_reasoning')}")


async def main() -> None:
    """Agent process main coroutine — runs periodic signal processing loop."""
    logger.info("=" * 70)
    logger.info("Agent Process starting...")
    logger.info("=" * 70)

    interval_minutes: int = app_config.get("intervals", {}).get("quant_analysis_minutes", 30)

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from src.server.graph import build_graph
    from src.server.agents import init_all_agents

    checkpoint_path = _project_root / "data" / "checkpoints_agent.db"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        init_all_agents()

        logger.info(f"[OK] Graph compiled, LLMs warmed up, interval={interval_minutes}m")
        logger.info("=" * 70)

        async with httpx.AsyncClient() as client:
            try:
                while True:
                    await asyncio.sleep(interval_minutes * 60)

                    autonomous_config = app_config.get("autonomous_trading", {})
                    if not autonomous_config.get("enabled", False):
                        logger.debug("[autonomous] Skipping cycle (disabled in config)")
                        continue

                    logger.info("[autonomous] Starting signal processing cycle...")
                    try:
                        min_confidence = autonomous_config.get("min_signal_confidence", 0.65)
                        batch_data = await _fetch_signal_batch(
                            min_confidence=min_confidence,
                            lookback_minutes=interval_minutes,
                            client=client,
                        )
                        await _run_signal_processing_cycle(batch_data, graph, autonomous_config)
                    except Exception as exc:
                        logger.error(f"[autonomous] Cycle error: {exc}", exc_info=True)

            except asyncio.CancelledError:
                logger.info("Agent process shutting down...")


def _shutdown(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel all running tasks on SIGINT / SIGTERM."""
    for task in asyncio.all_tasks(loop):
        task.cancel()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown, loop)
        except NotImplementedError:
            pass  # Windows

    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
