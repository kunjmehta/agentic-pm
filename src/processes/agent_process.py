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
    Requires the API process to be running at localhost:8000 so that
    HITL approve/reject endpoints are accessible.
"""

import asyncio
import signal
import sys
import time
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

from src.common.utils import get_logger, config as app_config
from src.server.state import make_initial_state

logger = get_logger(__name__)


async def _run_signal_processing_cycle(aggregator, graph, config: dict) -> None:
    """Execute a single autonomous signal-processing cycle.

    Args:
        aggregator: SignalAggregator instance.
        graph: Compiled LangGraph instance.
        config: Autonomous trading config dict from app config.
    """
    min_confidence = config.get("min_signal_confidence", 0.65)
    interval = app_config.get("intervals", {}).get("quant_analysis_minutes", 30)

    signal_batch = await aggregator.generate_signal_batch(
        min_confidence=min_confidence,
        lookback_minutes=interval,
    )

    if not signal_batch or not signal_batch.signals:
        logger.info("[autonomous] No actionable signals found")
        return

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

    # autonomous_config = app_config.get("autonomous_trading", {})
    # if not autonomous_config.get("enabled", False):
    #     logger.warning(
    #         "[autonomous] Autonomous trading disabled in config — agent process idle. "
    #         "Set autonomous_trading.enabled=true to activate."
    #     )
    #     # Keep alive so the process doesn't exit immediately
    #     try:
    #         while True:
    #             await asyncio.sleep(60)
    #     except asyncio.CancelledError:
    #         return

    interval_minutes: int = app_config.get("intervals", {}).get("quant_analysis_minutes", 30)

    # Build graph with its own checkpointer for this process
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from src.server.graph import build_graph
    from src.server.agents import init_all_agents
    from src.server.services.signal_aggregator import SignalAggregator

    checkpoint_path = _project_root / "data" / "checkpoints_agent.db"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        init_all_agents()
        aggregator = SignalAggregator()

        logger.info(f"[OK] Graph compiled, LLMs warmed up, interval={interval_minutes}m")
        logger.info("=" * 70)

        try:
            while True:
                await asyncio.sleep(interval_minutes * 60)

                # Re-read config each cycle so hot-reload of enabled flag works
                if not app_config.get("autonomous_trading", {}).get("enabled", False):
                    logger.debug("[autonomous] Skipping cycle (disabled in config)")
                    continue

                logger.info("[autonomous] Starting signal processing cycle...")
                try:
                    await _run_signal_processing_cycle(aggregator, graph, autonomous_config)
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
