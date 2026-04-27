"""Application lifespan — API process only.

Manages startup and shutdown for the API server. ETL streaming, live-trade
archival, and autonomous signal processing each run in their own dedicated
process (see ``src/processes/``).

Responsibilities:
- LangGraph compilation + checkpointer
- LLM singleton warm-up
- Strategy registration + IoC wiring (WS broadcaster, registry)
- Notification service
- Backtest scheduler
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI

import src.server.app_state as _state
from src.server.graph import build_graph
from src.server.agents import init_all_agents
from src.common.utils import get_logger, config as app_config
from src.common.ingestion import set_ws_broadcaster

logger = get_logger(__name__)


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage API server lifecycle — startup and shutdown."""
    logger.info("=" * 70)
    logger.info("Starting Semi-Auto Portfolio Manager API (port 8000)...")
    logger.info("=" * 70)

    _state._event_loop = asyncio.get_event_loop()
    logger.info("[OK] Event loop reference stored for cross-thread telemetry")

    # ── LangGraph ──────────────────────────────────────────────────────────────
    logger.info("Compiling LangGraph...")
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    checkpoint_path = project_root / "data" / "checkpoints.db"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    _state._checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
    _state._checkpointer = await _state._checkpointer_cm.__aenter__()
    _state._graph = build_graph(checkpointer=_state._checkpointer)
    logger.info("[OK] Graph compiled with HITL interrupt_before=['executor_node']")

    # ── Schema init — API owns analysis writes ─────────────────────────────────
    from src.common.dao.analysis_dao import AnalysisDAO
    AnalysisDAO()  # creates analysis.duckdb + schema if not present
    logger.info("[OK] Analysis DB schema ensured")

    # ── IoC callbacks ──────────────────────────────────────────────────────────
    from src.server.ws_manager import ws_manager as _ws_manager
    from src.common.registry import strategy_registry as _strategy_registry_mod
    from src.server.registry.register_strategies import ensure_strategies_registered

    ensure_strategies_registered()
    set_ws_broadcaster(_ws_manager.broadcast)
    logger.info("[OK] WebSocket broadcaster wired")

    # ── LLM warm-up ───────────────────────────────────────────────────────────
    logger.info("Pre-warming LLM singletons...")
    init_all_agents()
    logger.info("[OK] All LLM singletons initialized")

    # ── Notification service ───────────────────────────────────────────────────
    logger.info("Initializing notification service...")
    from src.server.services.notifications import get_notification_service

    notification_service = await get_notification_service(
        app_config.get("notifications", default={})
    )
    if notification_service.enabled:
        active = [ch.name for ch in notification_service.channels if ch.enabled]
        logger.info(
            f"[OK] Notification service enabled with channels: "
            f"{', '.join(active) if active else 'none'}"
        )
    else:
        logger.info("[OK] Notification service disabled in config")

    # ── Account info banner ────────────────────────────────────────────────────
    try:
        from src.common.external.alpaca_portfolio import fetch_account_info, fetch_positions

        account = await asyncio.to_thread(fetch_account_info)
        positions = await asyncio.to_thread(fetch_positions)
        logger.info("=" * 70)
        logger.info("Alpaca Account Status:")
        logger.info(f"   Equity:        ${account['equity']:,.2f}")
        logger.info(f"   Cash:          ${account['cash']:,.2f}")
        logger.info(f"   Buying Power:  ${account['buying_power']:,.2f}")
        logger.info(f"   Positions:     {len(positions)}")
        if positions:
            logger.info(f"   Symbols:       {', '.join(p['symbol'] for p in positions[:5])}")
        logger.info("=" * 70)
    except Exception as exc:
        logger.warning(f"[startup] Could not fetch account info: {exc}")

    # ── Backtest scheduler ─────────────────────────────────────────────────────
    try:
        from src.server.services.backtest_scheduler import backtest_scheduler

        backtest_scheduler.start()
        logger.info("[OK] Backtest scheduler started")
    except Exception as exc:
        logger.warning(f"[backtest-scheduler] Failed to start: {exc}", exc_info=True)

    logger.info("=" * 70)
    logger.info("API Server: http://localhost:8000")
    logger.info("Interactive Docs: http://localhost:8000/docs")
    logger.info("=" * 70)

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    logger.info("Shutting down Semi-Auto API...")

    try:
        from src.server.services.backtest_scheduler import backtest_scheduler

        backtest_scheduler.stop()
        logger.info("[OK] Backtest scheduler stopped")
    except Exception as exc:
        logger.warning(f"[backtest-scheduler] Shutdown error: {exc}")

    try:
        from src.server.services import sandbox_service

        await sandbox_service.cleanup_all()
        logger.info("[OK] Sandbox sessions cleaned up")
    except Exception as exc:
        logger.warning(f"[sandbox] Shutdown cleanup error: {exc}")

    if getattr(_state, "_checkpointer_cm", None) is not None:
        try:
            await _state._checkpointer_cm.__aexit__(None, None, None)
        except Exception:
            pass
        _state._checkpointer_cm = None
    logger.info("[OK] Checkpointer closed")

    try:
        from src.common.db_connections import close_all as _close_db
        _close_db()
        logger.info("[OK] Shared DB connections closed")
    except Exception as exc:
        logger.warning(f"[db_connections] Shutdown error: {exc}")
