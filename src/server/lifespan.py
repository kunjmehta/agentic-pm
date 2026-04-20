"""Application lifespan — API process only.

Manages startup and shutdown for the API server. ETL streaming, live-trade
archival, and autonomous signal processing each run in their own dedicated
process (see ``src/processes/``).

Responsibilities:
- LangGraph compilation + checkpointer
- LLM singleton warm-up
- Strategy registration + IoC wiring (WS broadcaster, registry)
- Notification service
- Historical data seeding (read-only, one-off at startup)
- Backtest scheduler
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI

import src.server.app_state as _state
from src.server.graph import build_graph
from src.server.agents import init_all_agents
from src.common.utils import get_logger, config as app_config
from src.common.data_gatherer.db_stream_handlers import (
    set_ws_broadcaster,
    set_strategy_registry,
)

logger = get_logger(__name__)


# ── Historical Data Initialization ─────────────────────────────────────────────


async def _ensure_historical_data_loaded(symbols: List[str], years: int = 3) -> None:
    """Ensure historical data is loaded for all watchlist symbols.

    Checks if historical data exists in the database, and fetches it if missing.
    Fetches N years of daily bars by default to ensure sufficient data for
    backtesting and indicator calculation.

    Args:
        symbols: List of symbols to check/fetch.
        years: Number of years of historical data to fetch. Default 3.
    """
    from src.common.dao.alpaca_dao import AlpacaDAO
    from src.common.external.alpaca import fetch_historical_bars

    logger.info("=" * 70)
    logger.info(f"Checking historical data for {len(symbols)} symbols...")
    logger.info("=" * 70)

    dao = AlpacaDAO()
    try:
        for symbol in symbols:
            try:
                result = dao.fetch_one(
                    "SELECT MAX(timestamp) as latest_ts, COUNT(*) as bar_count "
                    "FROM bars WHERE symbol = ? AND timeframe = '1Day'",
                    (symbol,),
                )
                latest_ts = result.get("latest_ts") if result else None
                bar_count = result.get("bar_count", 0) if result else 0
                expected_bars = years * 252

                if latest_ts is not None and bar_count >= expected_bars * 0.8:
                    logger.info(
                        f"[{symbol}] ✓ Historical data OK: {bar_count} bars, "
                        f"latest: {latest_ts}"
                    )
                    continue

                logger.info(
                    f"[{symbol}] Insufficient data ({bar_count} bars) — fetching {years} years..."
                )
                end = datetime.now(timezone.utc)
                start = end - timedelta(days=years * 365)
                bars_df = await asyncio.to_thread(
                    fetch_historical_bars,
                    symbol=symbol,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    timeframe="1Day",
                )
                logger.info(f"[{symbol}] ✓ Fetched {len(bars_df)} daily bars")

            except Exception as exc:
                logger.error(f"[{symbol}] Failed to load historical data: {exc}", exc_info=True)
    finally:
        dao.close()

    logger.info("Historical data check complete")


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

    # ── IoC callbacks ──────────────────────────────────────────────────────────
    from src.server.ws_manager import ws_manager as _ws_manager
    from src.common.registry import strategy_registry as _strategy_registry_mod
    from src.server.registry.register_strategies import ensure_strategies_registered

    ensure_strategies_registered()
    set_ws_broadcaster(_ws_manager.broadcast)
    set_strategy_registry(_strategy_registry_mod)
    logger.info("[OK] WebSocket broadcaster and strategy registry wired")

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

    # ── Historical data seeding ────────────────────────────────────────────────
    watchlist = app_config.get_watchlist_symbols()
    if watchlist:
        try:
            await _ensure_historical_data_loaded(watchlist, years=3)
        except Exception as exc:
            logger.warning(f"[startup] Historical data check failed: {exc}", exc_info=True)
    else:
        logger.warning("[startup] No watchlist symbols configured")

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
