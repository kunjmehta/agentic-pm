"""Application lifespan and background task management.

Extracted from api.py so that api.py remains a thin wiring module.  All
module-level globals live in :mod:`src.semi_auto.app_state`; this module
mutates them during startup / shutdown.
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI

import src.semi_auto.app_state as _state
from src.semi_auto.graph import build_graph
from src.common.utils import get_logger, config as app_config
from src.common.data_gatherer.data_coordinator import DataCoordinator
from src.common.data_gatherer.db_stream_handlers import (
    start_background_flush_task,
    stop_background_flush_task,
)

logger = get_logger(__name__)


# ── Background tasks ───────────────────────────────────────────────────────────


async def _run_periodic_archival() -> None:
    """Background task: archive aged live_trades rows into historical_trades.

    Runs every ``_ARCHIVAL_INTERVAL_MINUTES`` minutes.  On each tick calls
    ``AlpacaDAO.archive_live_trades()`` to move rows whose ``ingested_at``
    timestamp is older than ``_ARCHIVAL_CUTOFF_MINUTES`` into the
    ``historical_trades`` table, then deletes them from ``live_trades``.

    Startup archival is handled once by the lifespan before this task
    is created, so stale rows from previous runs are cleared immediately.
    """
    from src.common.dao.alpaca_dao import AlpacaDAO

    logger.info(
        f"[archival] periodic task started — interval={_state._ARCHIVAL_INTERVAL_MINUTES}m, "
        f"cutoff={_state._ARCHIVAL_CUTOFF_MINUTES}m"
    )
    try:
        while True:
            await asyncio.sleep(_state._ARCHIVAL_INTERVAL_MINUTES * 60)
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=_state._ARCHIVAL_CUTOFF_MINUTES)
            dao = AlpacaDAO()
            try:
                archived = dao.archive_live_trades(cutoff_time=cutoff)
                if archived:
                    logger.info(f"[archival] archived {archived} live trade(s) older than {cutoff.isoformat()}")
                else:
                    logger.debug("[archival] no live trades eligible for archival")
            except Exception as exc:
                logger.error(f"[archival] archival failed: {exc}", exc_info=True)
            finally:
                dao.close()
    except asyncio.CancelledError:
        logger.info("[archival] periodic archival task cancelled")
        # Final flush on shutdown
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_state._ARCHIVAL_CUTOFF_MINUTES)
        dao = AlpacaDAO()
        try:
            archived = dao.archive_live_trades(cutoff_time=cutoff)
            logger.info(f"[archival] shutdown archival: archived {archived} trade(s)")
        except Exception as exc:
            logger.error(f"[archival] shutdown archival failed: {exc}", exc_info=True)
        finally:
            dao.close()


async def _run_live_streams(coordinator: DataCoordinator) -> None:
    """Start live market data streams for all watchlist symbols.

    Runs streaming only (no historical backfill) so the API starts fast.
    Trades are batched via TradeCache and flushed to market_data.duckdb in
    bulk.  Bars are written directly per-event since they are low-frequency
    and trigger indicator computation.  A background asyncio task handles
    time-based cache eviction.
    """
    symbols = coordinator.symbols
    logger.info(f"[streams] starting live streams for {symbols}")
    flush_task = None
    try:
        for symbol in symbols:
            await coordinator.start_streaming(symbol)
        flush_task = start_background_flush_task()
        logger.info("[streams] background cache-flush task started")
        shutdown_flag = [False]
        await coordinator.run_streaming_loop(shutdown_flag)
    except asyncio.CancelledError:
        logger.info("[streams] stream loop cancelled — shutting down")
    except Exception as exc:
        logger.error(f"[streams] unexpected error: {exc}", exc_info=True)
    finally:
        if flush_task is not None:
            await stop_background_flush_task()
            logger.info("[streams] background flush task stopped")
        coordinator.stop_all_streaming()
        coordinator.close()


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle — startup and shutdown."""
    logger.info("=" * 70)
    logger.info("Starting Semi-Auto Portfolio Manager API (port 8000)...")
    logger.info("=" * 70)

    logger.info("Compiling LangGraph...")
    _state._graph = build_graph()
    logger.info("[OK] Graph compiled with HITL interrupt_before=['executor_node']")

    # ── Startup archival: clear stale live_trades from previous run ────────
    try:
        from src.common.dao.alpaca_dao import AlpacaDAO as _AlpacaDAO
        _startup_cutoff = datetime.now(timezone.utc) - timedelta(minutes=_state._ARCHIVAL_CUTOFF_MINUTES)
        _startup_dao = _AlpacaDAO()
        try:
            _archived = _startup_dao.archive_live_trades(cutoff_time=_startup_cutoff)
            logger.info(f"[startup] archived {_archived} stale live trade(s) from previous run")
        finally:
            _startup_dao.close()
    except Exception as exc:
        logger.warning(f"[startup] startup archival skipped: {exc}")

    # ── Periodic archival ──────────────────────────────────────────────────
    _state._archival_task = asyncio.create_task(
        _run_periodic_archival(),
        name="live-trades-archival",
    )
    logger.info(
        f"[OK] Periodic archival task started "
        f"(every {_state._ARCHIVAL_INTERVAL_MINUTES}m, cutoff {_state._ARCHIVAL_CUTOFF_MINUTES}m)"
    )

    # ── Live market data streams ───────────────────────────────────────────
    try:
        watchlist = app_config.get("watchlist", default=["AAPL"])
        _state._data_coordinator = DataCoordinator(symbols=watchlist)
        _state._stream_task = asyncio.create_task(
            _run_live_streams(_state._data_coordinator),
            name="live-market-streams",
        )
        logger.info(f"[OK] Live streaming task started for watchlist: {watchlist}")
    except Exception as exc:
        logger.warning(f"[streams] failed to start — continuing without live data: {exc}")

    logger.info("=" * 70)
    logger.info("API Server: http://localhost:8000")
    logger.info("Interactive Docs: http://localhost:8000/docs")
    logger.info("=" * 70)

    yield

    logger.info("Shutting down Semi-Auto API...")
    if _state._archival_task and not _state._archival_task.done():
        _state._archival_task.cancel()
        try:
            await asyncio.wait_for(_state._archival_task, timeout=10.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    logger.info("[OK] Archival task stopped")
    if _state._stream_task and not _state._stream_task.done():
        _state._stream_task.cancel()
        try:
            await asyncio.wait_for(_state._stream_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    logger.info("[OK] Live streams stopped")
