"""ETL process entry point — standalone ingestion and indicator computation.

Runs in its own event loop, separate from the API server.

Responsibilities:
- Alpaca live market data streaming (WebSocket or Redis Streams)
- Bar ingestion → DuckDB writes
- Indicator computation per new bar
- Strategy signal generation
- Live-trades archival

Usage:
    python -m src.processes.etl_process
    # or
    python src/processes/etl_process.py
"""

import asyncio
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ETL owns writes to market only. API process owns analysis, portfolio, backtest.
# Agent process opens all databases read-only and writes via the API process.

_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

import httpx

from src.common.utils import get_logger, config as app_config
from src.common.ingestion import (
    set_ws_broadcaster,
    start_background_flush_task,
    stop_background_flush_task,
)
from src.server.registry.register_strategies import ensure_strategies_registered

logger = get_logger(__name__)

# Persistent HTTP client for forwarding WS broadcasts to the API process.
_http_client: Optional[httpx.AsyncClient] = None
_API_BROADCAST_URL = "http://127.0.0.1:8000/v1/market/internal/broadcast"


async def _api_broadcaster(message: dict) -> None:
    """Forward a bar/trade broadcast message to the API process via HTTP.

    Fire-and-forget: creates a background task so the stream handler is never
    delayed waiting for the HTTP round-trip.
    """
    if _http_client is None:
        return
    asyncio.create_task(_post_broadcast(message))


async def _post_broadcast(message: dict) -> None:
    try:
        await _http_client.post(_API_BROADCAST_URL, json=message, timeout=2.0)
    except Exception as exc:
        logger.debug(f"[broadcast] HTTP forward failed: {exc}")

# Archival constants (self-contained since app_state is API-only)
_ARCHIVAL_INTERVAL_MINUTES: int = 15
_ARCHIVAL_CUTOFF_MINUTES: int = 120
_ANALYST_SUMMARY_INTERVAL_MINUTES: int = 10


async def _run_periodic_archival() -> None:
    """Background task: archive aged live_trades rows into historical_trades.

    Runs every ``_ARCHIVAL_INTERVAL_MINUTES`` minutes.
    """
    from src.common.utils.container import get_alpaca_dao

    logger.info(
        f"[archival] periodic task started — interval={_ARCHIVAL_INTERVAL_MINUTES}m, "
        f"cutoff={_ARCHIVAL_CUTOFF_MINUTES}m"
    )
    try:
        while True:
            await asyncio.sleep(_ARCHIVAL_INTERVAL_MINUTES * 60)
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=_ARCHIVAL_CUTOFF_MINUTES)
            try:
                archived = get_alpaca_dao().archive_live_trades(cutoff_time=cutoff)
                if archived:
                    logger.info(f"[archival] archived {archived} live trade(s)")
                else:
                    logger.debug("[archival] no eligible live trades")
            except Exception as exc:
                logger.error(f"[archival] failed: {exc}", exc_info=True)
    except asyncio.CancelledError:
        logger.info("[archival] task cancelled — running final archival")
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_ARCHIVAL_CUTOFF_MINUTES)
        try:
            archived = get_alpaca_dao().archive_live_trades(cutoff_time=cutoff)
            logger.info(f"[archival] shutdown: archived {archived} trade(s)")
        except Exception as exc:
            logger.error(f"[archival] shutdown archival failed: {exc}", exc_info=True)


async def _run_periodic_analyst_summaries(watchlist: list) -> None:
    """Background task: generate 10-minute LLM analyst summaries per ticker.

    Runs every ``_ANALYST_SUMMARY_INTERVAL_MINUTES`` minutes. Each cycle fetches
    the last 10 minutes of bars, indicators, and signals for every watchlist
    symbol, calls the LLM, and upserts the result to ``analyst_summaries``.
    """
    from src.server.services.analyst_service import analyst_summary_service
    from src.common.dao.analysis_dao import AnalysisDAO
    from src.common.utils import config as app_config

    logger.info(
        f"[analyst-summaries] periodic task started — interval={_ANALYST_SUMMARY_INTERVAL_MINUTES}m"
    )
    await asyncio.sleep(60)  # startup grace: let streams settle

    try:
        while True:
            window_end = datetime.now()
            window_start = window_end - timedelta(minutes=_ANALYST_SUMMARY_INTERVAL_MINUTES)
            analysis_dao = AnalysisDAO()
            try:
                for symbol in watchlist:
                    result = await analyst_summary_service.generate_summary(
                        symbol, window_start, window_end
                    )
                    if result is None:
                        continue
                    analysis_dao.save_eod_summary(
                        symbol=symbol,
                        timestamp=window_end,
                        indicators={},
                        summary_text=result.summary,
                        signals={
                            "trend": result.trend,
                            "trend_reasoning": result.trend_reasoning,
                            "key_signals": result.key_signals,
                            "confidence": result.confidence,
                        },
                        model_used=app_config.get("graph_api.reasoning_model", "gpt-4o-mini"),
                    )
                    logger.info(
                        f"[analyst-summaries] {symbol} saved — trend={result.trend}"
                    )
            except Exception as exc:
                logger.error(f"[analyst-summaries] cycle error: {exc}", exc_info=True)
            finally:
                analysis_dao.close()

            await asyncio.sleep(_ANALYST_SUMMARY_INTERVAL_MINUTES * 60)
    except asyncio.CancelledError:
        logger.info("[analyst-summaries] task cancelled")


async def _run_streams(watchlist: list) -> None:
    """Start market data streams based on config (Redis or direct Alpaca)."""
    redis_config = app_config.get("redis", {})
    use_redis = redis_config.get("enabled", False)

    if use_redis:
        from src.common.cache.redis_stream_consumer import RedisStreamConsumer
        from src.common.ingestion import (
            combined_trade_handler,
            combined_bar_handler,
        )

        logger.info(f"[streams] Redis Streams consumer — symbols: {watchlist}")
        consumer = RedisStreamConsumer()
        consumer.subscribe_trades(watchlist, combined_trade_handler)
        consumer.subscribe_bars(watchlist, combined_bar_handler)

        flush_task = start_background_flush_task()
        try:
            await consumer.run()
        except asyncio.CancelledError:
            logger.info("[streams] Redis consumer cancelled")
        finally:
            consumer.stop()
            await stop_background_flush_task()
    else:
        from src.common.ingestion import DataCoordinator

        logger.info(f"[streams] Direct Alpaca WebSocket — symbols: {watchlist}")
        coordinator = DataCoordinator(symbols=watchlist)
        flush_task = None
        try:
            for symbol in watchlist:
                await coordinator.start_streaming(symbol)
            flush_task = start_background_flush_task()
            shutdown_flag = [False]
            await coordinator.run_streaming_loop(shutdown_flag)
        except asyncio.CancelledError:
            logger.info("[streams] direct stream cancelled")
        finally:
            if flush_task is not None:
                await stop_background_flush_task()
            coordinator.stop_all_streaming()


async def _ensure_historical_data_loaded(symbols: list[str], years: int = 3) -> None:
    """Seed historical daily bars for *symbols* if not already present.

    ETL owns the market write connection so this must run here, not in the API
    process.

    Args:
        symbols: Watchlist symbols to check.
        years: Years of daily bar history to fetch when data is missing.
    """
    from src.common.utils.container import get_alpaca_dao
    from src.common.external.alpaca import fetch_historical_bars

    logger.info("=" * 70)
    logger.info(f"[historical] Checking {len(symbols)} symbol(s) for {years}y of daily bars...")
    logger.info("=" * 70)

    dao = get_alpaca_dao()
    expected_bars = years * 252
    for symbol in symbols:
        try:
            result = dao.fetch_one(
                "SELECT MAX(timestamp) as latest_ts, COUNT(*) as bar_count "
                "FROM market_bars WHERE symbol = ? AND timeframe = '1Day'",
                (symbol,),
            )
            bar_count = result.get("bar_count", 0) if result else 0
            latest_ts = result.get("latest_ts") if result else None

            if latest_ts is not None and bar_count >= expected_bars * 0.8:
                logger.info(f"[historical] {symbol} OK — {bar_count} bars, latest: {latest_ts}")
                continue

            logger.info(f"[historical] {symbol} insufficient ({bar_count} bars) — fetching...")
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=years * 365)
            bars_df = await asyncio.to_thread(
                fetch_historical_bars,
                symbol=symbol,
                start=start.isoformat(),
                end=end.isoformat(),
                timeframe="1Day",
            )
            logger.info(f"[historical] {symbol} seeded {len(bars_df)} daily bars")
        except Exception as exc:
            logger.error(f"[historical] {symbol} failed: {exc}", exc_info=True)

    logger.info("[historical] Seed check complete")


async def main() -> None:
    """ETL process main coroutine — runs until cancelled."""
    global _http_client

    logger.info("=" * 70)
    logger.info("ETL Process starting...")
    logger.info("=" * 70)

    # Register HTTP broadcaster so bar/trade updates reach the API's ws_manager.
    _http_client = httpx.AsyncClient(timeout=2.0)
    set_ws_broadcaster(_api_broadcaster)
    logger.info("[OK] WS broadcaster wired → API process via HTTP")

    ensure_strategies_registered()
    logger.info("[OK] Strategies registered")

    # Startup archival: clear stale rows from previous run
    try:
        from src.common.utils.container import get_alpaca_dao

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_ARCHIVAL_CUTOFF_MINUTES)
        archived = get_alpaca_dao().archive_live_trades(cutoff_time=cutoff)
        logger.info(f"[startup] archived {archived} stale live trade(s)")
    except Exception as exc:
        logger.warning(f"[startup] archival skipped: {exc}")

    watchlist = app_config.get_watchlist_symbols() or app_config.get("watchlist", default=["AAPL"])

    # Seed historical data before streaming begins (ETL owns market writes).
    try:
        await _ensure_historical_data_loaded(watchlist, years=3)
    except Exception as exc:
        logger.warning(f"[startup] Historical seeding failed: {exc}", exc_info=True)

    archival_task = asyncio.create_task(_run_periodic_archival(), name="live-trades-archival")
    analyst_task = asyncio.create_task(
        _run_periodic_analyst_summaries(watchlist), name="analyst-summaries"
    )
    stream_task = asyncio.create_task(_run_streams(watchlist), name="market-streams")

    logger.info("=" * 70)
    logger.info(f"ETL process running — watchlist: {watchlist}")
    logger.info("=" * 70)

    try:
        await asyncio.gather(archival_task, analyst_task, stream_task)
    except asyncio.CancelledError:
        logger.info("ETL process shutting down...")
        for task in (stream_task, analyst_task, archival_task):
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=10.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
        logger.info("ETL process stopped")

    if _http_client is not None:
        try:
            await _http_client.aclose()
            logger.info("[OK] HTTP broadcast client closed")
        except Exception:
            pass

    try:
        from src.common.db_connections import close_all as _close_db
        _close_db()
        logger.info("[OK] Shared DB connections closed")
    except Exception as exc:
        logger.warning(f"[db_connections] Shutdown error: {exc}")


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
