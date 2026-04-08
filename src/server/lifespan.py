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
from typing import List

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI

import src.server.app_state as _state
from src.server.graph import build_graph
from src.server.agents import init_all_agents
from src.common.utils import get_logger, config as app_config
from src.common.data_gatherer.data_coordinator import DataCoordinator
from src.common.data_gatherer.db_stream_handlers import (
    start_background_flush_task,
    stop_background_flush_task,
)
from src.server.services.signal_aggregator import SignalAggregator
from src.server.state import make_initial_state
from src.common.external.alpaca import fetch_historical_bars

logger = get_logger(__name__)


# ── Historical Data Initialization ─────────────────────────────────────────────


async def _ensure_historical_data_loaded(symbols: List[str], years: int = 3) -> None:
    """Ensure historical data is loaded for all watchlist symbols.

    Checks if historical data exists in the database, and fetches it if missing.
    Fetches 3 years of daily bars by default to ensure sufficient data for
    backtesting and indicator calculation.

    Args:
        symbols: List of symbols to check/fetch.
        years: Number of years of historical data to fetch. Default 3.
    """
    from src.common.dao.alpaca_dao import AlpacaDAO

    logger.info("=" * 70)
    logger.info(f"Checking historical data for {len(symbols)} symbols...")
    logger.info("=" * 70)

    dao = AlpacaDAO()

    try:
        for symbol in symbols:
            try:
                # Check if we have recent data
                latest_bar_query = """
                    SELECT MAX(timestamp) as latest_ts, COUNT(*) as bar_count
                    FROM bars
                    WHERE symbol = ? AND timeframe = '1Day'
                """
                result = dao.fetch_one(latest_bar_query, (symbol,))

                latest_ts = result.get("latest_ts") if result else None
                bar_count = result.get("bar_count", 0) if result else 0

                # Calculate expected bars (approx 252 trading days per year)
                expected_bars = years * 252

                needs_fetch = False
                if latest_ts is None:
                    logger.info(f"[{symbol}] No historical data found")
                    needs_fetch = True
                elif bar_count < expected_bars * 0.8:  # Allow 20% tolerance
                    logger.info(
                        f"[{symbol}] Insufficient data: {bar_count} bars "
                        f"(expected ~{expected_bars} for {years} years)"
                    )
                    needs_fetch = True
                else:
                    logger.info(
                        f"[{symbol}] ✓ Historical data OK: {bar_count} bars, "
                        f"latest: {latest_ts}"
                    )

                if needs_fetch:
                    # Fetch historical data
                    end = datetime.now(timezone.utc)
                    start = end - timedelta(days=years * 365)

                    logger.info(
                        f"[{symbol}] Fetching {years} years of daily bars "
                        f"({start.date()} to {end.date()})..."
                    )

                    bars_df = fetch_historical_bars(
                        symbol=symbol,
                        start=start.isoformat(),
                        end=end.isoformat(),
                        timeframe="1Day"
                    )

                    logger.info(
                        f"[{symbol}] ✓ Fetched {len(bars_df)} daily bars, "
                        f"saving to database..."
                    )

                    # Data is automatically saved by fetch_historical_bars
                    logger.info(f"[{symbol}] ✓ Historical data loaded successfully")

            except Exception as exc:
                logger.error(
                    f"[{symbol}] Failed to load historical data: {exc}",
                    exc_info=True
                )
                # Continue with other symbols even if one fails

    finally:
        dao.close()

    logger.info("=" * 70)
    logger.info("Historical data check complete")
    logger.info("=" * 70)


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


async def _run_live_streams_from_redis(symbols: List[str]) -> None:
    """Start live market data consumption from Redis Streams.

    Consumes trade and bar data from Redis Streams instead of direct Alpaca
    WebSocket connection. The standalone ingestion script handles the Alpaca
    streaming and publishes to Redis.

    Args:
        symbols: List of ticker symbols to consume
    """
    from src.common.cache.redis_stream_consumer import RedisStreamConsumer
    from src.common.data_gatherer.db_stream_handlers import (
        combined_trade_handler,
        combined_bar_handler
    )

    logger.info(f"[streams] starting Redis Stream consumer for {symbols}")

    consumer = RedisStreamConsumer()
    consumer.subscribe_trades(symbols, combined_trade_handler)
    consumer.subscribe_bars(symbols, combined_bar_handler)

    flush_task = start_background_flush_task()
    logger.info("[streams] background cache-flush task started")

    try:
        await consumer.run()  # Blocks until stopped
    except asyncio.CancelledError:
        logger.info("[streams] stream consumer cancelled")
    finally:
        consumer.stop()
        await stop_background_flush_task()
        logger.info("[streams] Redis Stream consumer and flush task stopped")


async def _run_live_streams(coordinator: DataCoordinator) -> None:
    """Start live market data streams for all watchlist symbols.

    DEPRECATED: This function uses direct Alpaca WebSocket streaming.
    Use _run_live_streams_from_redis() for the new Redis Streams architecture.

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


async def _run_periodic_signal_processing(
    aggregator: SignalAggregator,
    graph,
    interval_minutes: int = 30
) -> None:
    """Periodically process accumulated signals and submit autonomous orders.

    Runs every N minutes (configurable via intervals.quant_analysis_minutes).
    On each tick:
    1. Fetch and aggregate high-confidence signals
    2. Invoke graph with signal_batch state
    3. PM decision node validates and approves signals
    4. Risk guard validates orders
    5. Execution pauses at HITL interrupt (order_executor_node)
    6. User must approve/reject via /autonomous API endpoints

    Args:
        aggregator: SignalAggregator instance for fetching signals.
        graph: Compiled LangGraph instance.
        interval_minutes: Minutes between signal processing cycles.
    """
    logger.info(
        f"[autonomous] periodic signal processing started "
        f"(interval={interval_minutes}m)"
    )

    try:
        while True:
            try:
                # Wait for next interval
                await asyncio.sleep(interval_minutes * 60)

                # Check if autonomous trading is enabled
                autonomous_config = app_config.get("autonomous_trading", {})
                if not autonomous_config.get("enabled", False):
                    logger.debug("[autonomous] Skipping cycle (autonomous trading disabled)")
                    continue

                logger.info("[autonomous] Starting signal processing cycle...")

                # Generate signal batch
                signal_batch = await aggregator.generate_signal_batch(
                    min_confidence=autonomous_config.get("min_signal_confidence", 0.65),
                    lookback_minutes=interval_minutes
                )

                if not signal_batch or not signal_batch.signals:
                    logger.info("[autonomous] No actionable signals found")
                    continue

                logger.info(
                    f"[autonomous] Generated batch {signal_batch.batch_id} "
                    f"with {len(signal_batch.signals)} signals"
                )

                # Prepare initial state for autonomous mode
                import time
                thread_id = f"autonomous_{int(time.time())}"
                initial_state = make_initial_state(
                    query="[Autonomous Trading] Processing periodic signals",
                    thread_id=thread_id,
                    backtest_mode=False
                )

                # Add autonomous-specific state
                initial_state["signal_batch"] = signal_batch.model_dump()
                initial_state["autonomous_mode"] = True

                # Invoke graph starting at PM decision node
                # Graph will route: pm_decision → risk_guard → order_reasoning → HITL (order_executor)
                config = {
                    "configurable": {
                        "thread_id": thread_id
                    }
                }

                logger.info(f"[autonomous] Invoking graph for thread {thread_id}")
                result = await graph.ainvoke(initial_state, config)

                # Execution stops at HITL gate (interrupt_before=["order_executor_node"])
                # User must call /v1/approve/{thread_id} or /v1/reject/{thread_id} to continue
                if result.get("_execute_orders"):
                    logger.info(
                        f"[autonomous] Orders ready for HITL approval (thread_id={thread_id}): "
                        f"{result.get('pm_decision_reasoning')}"
                    )
                else:
                    logger.info(
                        f"[autonomous] No orders generated: {result.get('pm_decision_reasoning')}"
                    )

            except Exception as exc:
                logger.error(f"[autonomous] Error in signal processing cycle: {exc}", exc_info=True)
                # Continue running despite errors in individual cycles

    except asyncio.CancelledError:
        logger.info("[autonomous] periodic signal processing task cancelled")
        raise


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle — startup and shutdown."""
    logger.info("=" * 70)
    logger.info("Starting Semi-Auto Portfolio Manager API (port 8000)...")
    logger.info("=" * 70)

    _state._event_loop = asyncio.get_event_loop()
    logger.info("[OK] Event loop reference stored for cross-thread telemetry")

    logger.info("Compiling LangGraph...")
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    checkpoint_path = project_root / "data" / "checkpoints.db"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    _state._checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
    _state._checkpointer = await _state._checkpointer_cm.__aenter__()
    _state._graph = build_graph(checkpointer=_state._checkpointer)
    logger.info("[OK] Graph compiled with HITL interrupt_before=['executor_node']")

    logger.info("Pre-warming LLM singletons...")
    init_all_agents()
    logger.info("[OK] All LLM singletons initialized")

    # Initialize notification service
    logger.info("Initializing notification service...")
    from src.server.services.notifications import get_notification_service
    notification_config = app_config.get("notifications", default={})
    notification_service = await get_notification_service(notification_config)
    if notification_service.enabled:
        active_channels = [ch.name for ch in notification_service.channels if ch.enabled]
        logger.info(f"[OK] Notification service enabled with channels: {', '.join(active_channels) if active_channels else 'none'}")
    else:
        logger.info("[OK] Notification service disabled in config")

    # ── Ensure historical data is loaded ───────────────────────────────────
    watchlist = app_config.get_watchlist_symbols()
    if watchlist:
        try:
            await _ensure_historical_data_loaded(watchlist, years=3)
        except Exception as exc:
            logger.warning(f"[startup] Historical data check failed: {exc}", exc_info=True)
    else:
        logger.warning("[startup] No watchlist symbols configured")

    # ── Fetch account info at startup ──────────────────────────────────────
    try:
        from src.common.external.alpaca_portfolio import fetch_account_info, fetch_positions
        account = fetch_account_info()
        positions = fetch_positions()
        logger.info("=" * 70)
        logger.info(f"📊 Alpaca Account Status:")
        logger.info(f"   Equity:        ${account['equity']:,.2f}")
        logger.info(f"   Cash:          ${account['cash']:,.2f}")
        logger.info(f"   Buying Power:  ${account['buying_power']:,.2f}")
        logger.info(f"   Positions:     {len(positions)}")
        if positions:
            logger.info(f"   Symbols:       {', '.join(p['symbol'] for p in positions[:5])}")
        logger.info("=" * 70)
    except Exception as exc:
        logger.warning(f"[startup] Could not fetch account info: {exc}")

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

        # Check if Redis Streams mode is enabled
        redis_config = app_config.get("redis", {})
        use_redis_streams = redis_config.get("enabled", False)

        if use_redis_streams:
            # New Redis Streams architecture
            logger.info("[streams] Using Redis Streams consumer mode")
            _state._stream_task = asyncio.create_task(
                _run_live_streams_from_redis(watchlist),
                name="redis-stream-consumer",
            )
            logger.info(f"[OK] Redis Stream consumer started for watchlist: {watchlist}")
        else:
            # Legacy direct Alpaca streaming
            logger.info("[streams] Using legacy direct Alpaca streaming mode")
            _state._data_coordinator = DataCoordinator(symbols=watchlist)
            _state._stream_task = asyncio.create_task(
                _run_live_streams(_state._data_coordinator),
                name="live-market-streams",
            )
            logger.info(f"[OK] Live streaming task started for watchlist: {watchlist}")
    except Exception as exc:
        logger.warning(f"[streams] failed to start — continuing without live data: {exc}")

    # ── Periodic autonomous signal processing ──────────────────────────────
    _state._autonomous_task = None
    autonomous_config = app_config.get("autonomous_trading", {})
    if autonomous_config.get("enabled", False):
        try:
            logger.info("[autonomous] Initializing signal aggregator...")
            _state._signal_aggregator = SignalAggregator()

            # Get interval from config
            interval = app_config.get("intervals", {}).get("quant_analysis_minutes", 30)

            _state._autonomous_task = asyncio.create_task(
                _run_periodic_signal_processing(
                    _state._signal_aggregator,
                    _state._graph,
                    interval
                ),
                name="autonomous-signal-processing",
            )
            logger.info(
                f"[OK] Autonomous signal processing task started "
                f"(every {interval}m, HITL approval required)"
            )
        except Exception as exc:
            logger.warning(f"[autonomous] Failed to start: {exc}", exc_info=True)
    else:
        logger.info("[autonomous] Autonomous trading disabled in config")

    # ── Scheduled backtests ────────────────────────────────────────────────
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
    if _state._autonomous_task and not _state._autonomous_task.done():
        _state._autonomous_task.cancel()
        try:
            await asyncio.wait_for(_state._autonomous_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    logger.info("[OK] Autonomous signal processing stopped")
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
    if getattr(_state, '_checkpointer_cm', None) is not None:
        try:
            await _state._checkpointer_cm.__aexit__(None, None, None)
        except Exception:
            pass
        _state._checkpointer_cm = None
    logger.info("[OK] Checkpointer closed")
