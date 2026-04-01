"""Standalone ingestion process: live trade/bar streaming + periodic cache flush.

This process owns AlpacaDataStreamer and TradeCache. It runs independently from
the agent API (src/graph/api.py) and writes to the shared market_data.duckdb
and analysis.duckdb files via short-lived DuckDB connections.

Usage:
    python -m src.common.ingestion_main
    python -m src.common.ingestion_main --symbols AAPL,MSFT
    python -m src.common.ingestion_main --no-historical
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path
from typing import List

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.common.utils.config_loader import config

logger = get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sync_watchlist() -> List[str]:
    """Fetch watchlist from Alpaca, fall back to config.

    Returns:
        List of ticker strings.
    """
    try:
        from src.common.external.alpaca_portfolio import get_all_watchlist_symbols
        from src.common.dao import AlpacaDAO

        alpaca_symbols = get_all_watchlist_symbols()
        if not alpaca_symbols:
            raise ValueError("Empty watchlist from Alpaca")

        dao = AlpacaDAO()
        db_symbols = set(dao.get_watchlist())
        for sym in set(alpaca_symbols) - db_symbols:
            dao.add_to_watchlist(sym)
            logger.info(f"[ingestion_main] Added {sym} to watchlist")
        dao.close()
        logger.info(f"[ingestion_main] Watchlist synced: {alpaca_symbols}")
        return alpaca_symbols
    except Exception as exc:
        fallback = config.get("watchlist", default=["AAPL"])
        logger.warning(
            f"[ingestion_main] Watchlist sync failed ({exc}), "
            f"using config fallback: {fallback}"
        )
        return fallback


def _needs_historical_init(symbol: str) -> bool:
    """Check whether a symbol needs historical bar seeding.

    Counts 1Min bars for the last 30 days. Returns True if fewer than 100
    bars are found (symbol not yet seeded), which is a safe default on error.

    Args:
        symbol: Stock ticker.

    Returns:
        True if seeding is required.
    """
    try:
        from datetime import datetime, timedelta
        from src.common.dao import AlpacaDAO

        end = datetime.now()
        start = end - timedelta(days=30)
        dao = AlpacaDAO()
        df = dao.get_bars(symbol, start=start, end=end, timeframe="1Min")
        dao.close()
        count = len(df) if df is not None and not df.empty else 0
        needs_init = count < 100
        logger.info(
            f"[ingestion_main] {symbol}: {count} 1Min bars found, "
            f"needs_historical_init={needs_init}"
        )
        return needs_init
    except Exception as exc:
        logger.warning(
            f"[ingestion_main] Could not check bar count for {symbol} ({exc}), "
            "assuming historical init is needed"
        )
        return True


# ── Core coroutine ────────────────────────────────────────────────────────────

async def _run_ingestion(symbols: List[str], skip_historical: bool) -> None:
    """Main ingestion loop: historical seed → streaming → graceful shutdown.

    Args:
        symbols: Tickers to stream.
        skip_historical: If True, skip the historical bar seeding step.
    """
    from src.common.data_gatherer.data_coordinator import DataCoordinator
    from src.common.data_gatherer.db_stream_handlers import (
        start_background_flush_task,
        stop_background_flush_task,
        flush_cache_to_db,
    )

    # Shared flag: set to True by SIGINT/SIGTERM handler
    shutdown_requested: List[bool] = [False]

    def _handle_signal(sig, frame):  # noqa: ANN001
        logger.info(f"[ingestion_main] Received signal {sig}, shutting down...")
        shutdown_requested[0] = True

    # Register OS signals (main thread only)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(f"[ingestion_main] Starting ingestion for symbols: {symbols}")

    coordinator = DataCoordinator(symbols=symbols)
    loop = asyncio.get_event_loop()

    # 1. Historical seed (optional, per-symbol)
    if not skip_historical:
        for sym in symbols:
            if _needs_historical_init(sym):
                logger.info(f"[ingestion_main] Seeding historical bars for {sym}...")
                try:
                    await loop.run_in_executor(
                        None,
                        lambda s=sym: coordinator.fetch_historical_market_data(s, days_back=30),
                    )
                    logger.info(f"[ingestion_main] Historical seed complete for {sym}")
                except Exception as exc:
                    logger.error(
                        f"[ingestion_main] Historical seed failed for {sym}: {exc}"
                    )
            else:
                logger.info(f"[ingestion_main] {sym}: sufficient bars already present, skipping seed")

    # 2. Start live streaming (opt-in via config)
    if config.get("data_stream.enabled", default=False):
        for sym in symbols:
            try:
                await coordinator.start_streaming(sym)
                logger.info(f"[ingestion_main] Stream started for {sym}")
            except Exception as exc:
                logger.error(f"[ingestion_main] Failed to start stream for {sym}: {exc}")
    else:
        logger.info("[ingestion_main] data_stream.enabled=false, streaming skipped")

    # 3. Start periodic cache flush background task
    flush_task = None
    try:
        flush_task = start_background_flush_task()
        logger.info("[ingestion_main] Background cache flush task started")
    except Exception as exc:
        logger.warning(f"[ingestion_main] Cache flush task failed to start: {exc}")

    logger.info("[ingestion_main] Ingestion process running — press Ctrl+C to stop")

    # 4. Keep running until shutdown signal
    try:
        await coordinator.run_streaming_loop(shutdown_requested)
    except Exception as exc:
        logger.error(f"[ingestion_main] Streaming loop error: {exc}")
    finally:
        logger.info("[ingestion_main] Shutting down...")

        # Final cache flush before exit
        try:
            await flush_cache_to_db()
            logger.info("[ingestion_main] Final cache flush complete")
        except Exception as exc:
            logger.warning(f"[ingestion_main] Final cache flush failed: {exc}")

        # Stop background flush task
        if flush_task is not None:
            try:
                await stop_background_flush_task()
                logger.info("[ingestion_main] Background flush task stopped")
            except Exception as exc:
                logger.warning(f"[ingestion_main] flush task stop error: {exc}")

        coordinator.stop_all_streaming()
        coordinator.close()
        logger.info("[ingestion_main] Shutdown complete")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Standalone Alpaca ingestion process (streaming + cache flush)."
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated list of tickers (e.g. AAPL,MSFT). "
             "Defaults to Alpaca watchlist or config fallback.",
    )
    parser.add_argument(
        "--no-historical",
        action="store_true",
        default=False,
        help="Skip historical bar seeding step.",
    )
    args = parser.parse_args()

    if args.symbols:
        symbol_list = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        logger.info(f"[ingestion_main] CLI symbols: {symbol_list}")
    else:
        symbol_list = _sync_watchlist()

    asyncio.run(_run_ingestion(symbol_list, skip_historical=args.no_historical))
