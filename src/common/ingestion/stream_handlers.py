"""Database-backed stream handlers for Alpaca real-time data.

This module provides async handlers that save stream data (trades, bars) to
the database using DAOs. Handlers can be used standalone or combined with
print/logging for visibility.

Indicator and strategy computation are NOT performed here — they are triggered
via ``IndicatorsETL.trigger_bar_computation`` (see pipeline.py) which uses the
quant skill singletons as the single source of truth.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import asyncio
from datetime import datetime, timedelta, date
from typing import Optional
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from src.common.utils.container import get_alpaca_dao
from src.common.ingestion.trade_cache import get_cache
from src.common.utils import get_logger, config, secrets


# Initialize logger
logger = get_logger(__name__)

# Previous-close cache: symbol -> (close_price, cache_date). Refreshed once per trading day.
_prev_close_cache: dict[str, tuple[float, date]] = {}

# Lazy-loaded ws_manager (to avoid circular import issues)
_ws_manager = None

# IoC callback — injected by lifespan.py / etl_process.py after startup.
_ws_broadcaster = None    # Callable[[dict], Awaitable[None]] | None

# Background flush task handle
_flush_task = None


def set_ws_broadcaster(fn) -> None:
    """Register the WebSocket broadcast callback (called from lifespan / ETL process).

    Args:
        fn: Async callable accepting a dict message, e.g. ``ws_manager.broadcast``.
    """
    global _ws_broadcaster
    _ws_broadcaster = fn
    logger.debug("[stream_handlers] WebSocket broadcaster registered")


def get_ws_manager():
    """Get or create WebSocket manager instance (fallback when IoC not used).

    Returns:
        PortfolioWSManager instance (singleton)
    """
    global _ws_manager
    if _ws_manager is None:
        try:
            from src.server.ws_manager import ws_manager
            _ws_manager = ws_manager
            logger.debug("WebSocket manager loaded for broadcasting")
        except ImportError:
            logger.warning("ws_manager not available - UI broadcasts disabled")
            _ws_manager = None
    return _ws_manager


async def save_trade_to_db(trade):
    """Save trade data directly to database (no caching).

    Args:
        trade: Either Alpaca trade object OR dict with trade data.
               Dict must have keys: symbol, timestamp, trade_id, price, size
               Optional keys: exchange, conditions, tape

    Note: This bypasses the cache. Use save_trade_to_cache() for batched writes.
    """
    try:
        dao = get_alpaca_dao()

        # Duck typing for backward compatibility: accept both dict and Alpaca object
        if isinstance(trade, dict):
            symbol = trade['symbol']
            timestamp = trade['timestamp']
            trade_id = trade['trade_id']
            price = float(trade['price'])
            size = int(trade['size'])
            exchange = trade.get('exchange')
            conditions = trade.get('conditions', '')
            tape = trade.get('tape')
        else:
            symbol = trade.symbol
            timestamp = trade.timestamp
            trade_id = trade.id
            price = float(trade.price)
            size = int(trade.size)
            exchange = trade.exchange if hasattr(trade, 'exchange') else None
            conditions = ','.join(trade.conditions) if hasattr(trade, 'conditions') and trade.conditions else ''
            tape = trade.tape if hasattr(trade, 'tape') else None

        df_data = {
            'symbol': symbol,
            'timestamp': timestamp,
            'trade_id': trade_id,
            'price': price,
            'size': size,
            'exchange': exchange,
            'conditions': conditions,
            'tape': tape
        }
        trade_df = pd.DataFrame([df_data])

        dao.save_trades(trade_df)
        logger.debug(f"Saved trade to DB: {symbol} @ ${price:.2f}")

    except Exception as e:
        logger.error(f"Failed to save trade to DB: {e}", exc_info=True)


async def save_trade_to_cache(trade):
    """Save trade data to cache for batched database writes.

    This is the recommended handler for live WebSocket streams as it reduces
    database write frequency by batching trades in memory.

    Args:
        trade: Either Alpaca trade object OR dict with trade data.
               Dict must have keys: symbol, timestamp, trade_id, price, size
               Optional keys: exchange, conditions, tape
    """
    try:
        cache = get_cache()

        if isinstance(trade, dict):
            symbol = trade['symbol']
            timestamp = trade['timestamp']
            trade_id = trade['trade_id']
            price = float(trade['price'])
            size = int(trade['size'])
            exchange = trade.get('exchange')
            conditions = trade.get('conditions', '')
            tape = trade.get('tape')
        else:
            symbol = trade.symbol
            timestamp = trade.timestamp
            trade_id = trade.id
            price = float(trade.price)
            size = int(trade.size)
            exchange = trade.exchange if hasattr(trade, 'exchange') else None
            conditions = ','.join(trade.conditions) if hasattr(trade, 'conditions') and trade.conditions else ''
            tape = trade.tape if hasattr(trade, 'tape') else None

        normalized_data = {
            'symbol': symbol,
            'timestamp': timestamp,
            'trade_id': trade_id,
            'price': price,
            'size': size,
            'exchange': exchange,
            'conditions': conditions,
            'tape': tape
        }

        should_flush = cache.add_trade(normalized_data)
        logger.debug(f"Added trade to cache: {symbol} @ ${price:.2f}")

        if should_flush:
            await flush_cache_to_db()

    except Exception as e:
        logger.error(f"Failed to save trade to cache: {e}", exc_info=True)


async def handle_trade_correction(correction):
    """Handle trade correction from Alpaca stream.

    Reference: https://docs.alpaca.markets/docs/real-time-stock-pricing-data#trade-corrections

    Args:
        correction: Alpaca trade correction object with original and corrected data
    """
    try:
        cache = get_cache()
        dao = get_alpaca_dao()

        symbol = correction.symbol
        trade_id = correction.id
        corrected_price = float(correction.price)
        corrected_size = int(correction.size)

        correction_data = {
            'symbol': symbol,
            'trade_id': trade_id,
            'price': corrected_price,
            'size': corrected_size,
            'timestamp': correction.timestamp if hasattr(correction, 'timestamp') else None,
            'exchange': correction.exchange if hasattr(correction, 'exchange') else None,
            'conditions': ','.join(correction.conditions) if hasattr(correction, 'conditions') and correction.conditions else '',
            'tape': correction.tape if hasattr(correction, 'tape') else None
        }

        updated_in_cache = cache.update_trade(correction_data)

        if updated_in_cache:
            logger.info(f"Trade correction applied in cache: {symbol} trade_id={trade_id}")
        else:
            logger.info(f"Trade not in cache, updating in live_trades: {symbol} trade_id={trade_id}")
            correction_df = pd.DataFrame([correction_data])
            dao.save_live_trades(correction_df)
            logger.info(f"Trade correction applied in live_trades: {symbol} trade_id={trade_id}")

    except Exception as e:
        logger.error(f"Failed to handle trade correction: {e}", exc_info=True)


async def handle_trade_cancellation(cancellation):
    """Handle trade cancellation/error from Alpaca stream.

    Reference: https://docs.alpaca.markets/docs/real-time-stock-pricing-data#trade-cancelserrors

    Args:
        cancellation: Alpaca trade cancellation object with trade ID to cancel
    """
    try:
        cache = get_cache()
        dao = get_alpaca_dao()

        symbol = cancellation.symbol
        trade_id = cancellation.id

        cancelled_in_cache = cache.cancel_trade(symbol, trade_id)

        if cancelled_in_cache:
            logger.info(f"Trade cancelled in cache: {symbol} trade_id={trade_id}")
        else:
            logger.info(f"Trade not in cache, deleting from live_trades: {symbol} trade_id={trade_id}")
            dao.execute(
                "DELETE FROM live_trades WHERE symbol = ? AND trade_id = ?",
                (symbol, trade_id),
            )
            dao.execute(
                "DELETE FROM historical_trades WHERE symbol = ? AND trade_id = ?",
                (symbol, trade_id),
            )
            logger.info(f"Trade cancellation applied to live_trades and historical_trades: {symbol} trade_id={trade_id}")

    except Exception as e:
        logger.error(f"Failed to handle trade cancellation: {e}", exc_info=True)


async def flush_cache_to_db():
    """Flush cached trades to live_trades table in database.

    This function is called automatically when cache thresholds are met,
    or can be called manually to force a flush.
    """
    try:
        cache = get_cache()
        dao = get_alpaca_dao()

        df = cache.flush()

        if df.empty:
            logger.debug("No trades to flush from cache")
            return

        rows = dao.save_live_trades(df)
        logger.info(f"Flushed {len(df):,} trades to live_trades ({rows} rows affected)")

    except Exception as e:
        logger.error(f"Failed to flush cache to DB: {e}", exc_info=True)


def _get_previous_close_from_alpaca(symbol: str) -> Optional[float]:
    """Helper to fetch previous day close from Alpaca API (synchronous for thread pool).

    Searches back up to 5 days to find the most recent trading day's closing price.
    Results are cached per symbol per calendar day — at most one API call per symbol
    per trading day rather than once per bar arrival.

    Args:
        symbol: Stock ticker symbol

    Returns:
        Previous close price as float, or None if not available
    """
    today = date.today()
    cached = _prev_close_cache.get(symbol)
    if cached is not None and cached[1] == today:
        return cached[0]

    try:
        api_key = secrets.get("alpaca.api_key")
        api_secret = secrets.get("alpaca.secret_key")
        client = StockHistoricalDataClient(api_key, api_secret)

        for days_back in range(1, 6):
            end_date = datetime.now() - timedelta(days=days_back)
            start_date = end_date - timedelta(days=1)

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start_date,
                end=end_date
            )

            bars = client.get_stock_bars(request)
            if symbol in bars and len(bars[symbol]) > 0:
                close_price = float(bars[symbol][-1].close)
                _prev_close_cache[symbol] = (close_price, today)
                logger.debug(f"Previous close for {symbol}: ${close_price:.2f} ({days_back} days back)")
                return close_price

        logger.warning(f"No previous close data found for {symbol} in last 5 days")
        return None

    except Exception as exc:
        logger.warning(f"Failed to fetch previous close for {symbol} from Alpaca: {exc}")
        return None


async def broadcast_bar_to_ui(bar, timeframe: str = '1Min'):
    """Broadcast bar update to connected UI clients with % change from previous close.

    Args:
        bar: Either Alpaca bar object OR dict with bar data
             Dict must have keys: symbol, timestamp, open, high, low, close, volume
             Optional keys: vwap
        timeframe: Bar timeframe string (default: '1Min')
    """
    _broadcast = _ws_broadcaster or (getattr(get_ws_manager(), 'broadcast', None))
    if _broadcast is None:
        return

    try:
        if isinstance(bar, dict):
            symbol = bar['symbol']
            timestamp = bar['timestamp']
            open_price = float(bar['open'])
            high_price = float(bar['high'])
            low_price = float(bar['low'])
            close_price = float(bar['close'])
            volume = int(bar['volume'])
            vwap = float(bar['vwap']) if bar.get('vwap') else None
        else:
            symbol = bar.symbol
            timestamp = bar.timestamp
            open_price = float(bar.open)
            high_price = float(bar.high)
            low_price = float(bar.low)
            close_price = float(bar.close)
            volume = int(bar.volume)
            vwap = float(bar.vwap) if hasattr(bar, 'vwap') and bar.vwap else None

        prev_close = await asyncio.to_thread(_get_previous_close_from_alpaca, symbol)

        pct_change = None
        if prev_close:
            pct_change = ((close_price - prev_close) / prev_close) * 100

        if isinstance(timestamp, str):
            timestamp_str = timestamp
        else:
            timestamp_str = timestamp.isoformat()

        message = {
            "type": "bar_update",
            "symbol": symbol,
            "timestamp": timestamp_str,
            "timeframe": timeframe,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
            "vwap": vwap,
            "prev_close": prev_close,
            "pct_change": round(pct_change, 2) if pct_change else None
        }
        await _broadcast(message)
    except Exception as exc:
        logger.debug(f"Failed to broadcast bar to UI: {exc}")


async def save_bar_to_db(bar, timeframe: str = '1Min'):
    """Save bar data to database, broadcast to UI, and trigger indicator computation.

    Args:
        bar: Either Alpaca bar object OR dict with bar data.
             Dict must have keys: symbol, timestamp, open, high, low, close, volume
             Optional keys: trade_count, vwap
        timeframe: Bar timeframe string (default: '1Min')
    """
    try:
        dao = get_alpaca_dao()

        if isinstance(bar, dict):
            symbol = bar['symbol']
            timestamp = bar['timestamp']
            open_price = float(bar['open'])
            high_price = float(bar['high'])
            low_price = float(bar['low'])
            close_price = float(bar['close'])
            volume = int(bar['volume'])
            trade_count = int(bar.get('trade_count')) if bar.get('trade_count') else None
            vwap = float(bar.get('vwap')) if bar.get('vwap') else None
        else:
            symbol = bar.symbol
            timestamp = bar.timestamp
            open_price = float(bar.open)
            high_price = float(bar.high)
            low_price = float(bar.low)
            close_price = float(bar.close)
            volume = int(bar.volume)
            trade_count = int(bar.trade_count) if hasattr(bar, 'trade_count') else None
            vwap = float(bar.vwap) if hasattr(bar, 'vwap') else None

        df_data = {
            'symbol': symbol,
            'timestamp': timestamp,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume,
            'trade_count': trade_count,
            'vwap': vwap
        }
        bar_df = pd.DataFrame([df_data])

        dao.save_bars(bar_df, timeframe=timeframe)
        logger.debug(f"Saved bar to DB: {symbol} @ {timestamp}")

        # Broadcast to UI
        await broadcast_bar_to_ui(bar, timeframe)

        # Fire-and-forget indicator + signal computation via pipeline singleton.
        # All quant computation goes through IndicatorsETL which calls quant skill
        # singletons — the single source of truth for all indicator/strategy logic.
        etl_enabled = config.get("etl.enabled", default=True)
        if etl_enabled:
            from src.common.ingestion.pipeline import get_indicators_etl
            asyncio.ensure_future(get_indicators_etl().trigger_bar_computation(symbol, timeframe))
        else:
            logger.warning(f"ETL disabled - skipping indicator computation for {symbol}")

    except Exception as e:
        logger.error(f"Failed to save bar to DB: {e}", exc_info=True)


async def combined_trade_handler(trade):
    """Combined handler: log AND save to database (direct, no cache).

    Args:
        trade: Either Alpaca trade object OR dict with trade data

    Note: This bypasses cache. Use combined_trade_cache_handler() for batched writes.
    """
    if isinstance(trade, dict):
        symbol = trade['symbol']
        price = trade['price']
        size = trade['size']
        exchange = trade.get('exchange', 'N/A')
        timestamp = trade['timestamp']
    else:
        symbol = trade.symbol
        price = trade.price
        size = trade.size
        exchange = trade.exchange if hasattr(trade, 'exchange') else 'N/A'
        timestamp = trade.timestamp

    logger.info(f"[TRADE] {symbol} @ ${price:.2f} x {size} | "
                f"Exchange: {exchange} | {timestamp}")

    await save_trade_to_db(trade)


async def broadcast_trade_to_ui(trade):
    """Broadcast trade update to connected UI clients.

    Args:
        trade: Either Alpaca trade object OR dict with trade data
    """
    _broadcast = _ws_broadcaster or getattr(get_ws_manager(), "broadcast", None)
    if _broadcast is None:
        return

    try:
        if isinstance(trade, dict):
            symbol = trade['symbol']
            price = float(trade['price'])
            size = int(trade['size'])
            timestamp = trade['timestamp']
            exchange = trade.get('exchange')
        else:
            symbol = trade.symbol
            price = float(trade.price)
            size = int(trade.size)
            timestamp = trade.timestamp
            exchange = trade.exchange if hasattr(trade, 'exchange') else None

        if isinstance(timestamp, str):
            timestamp_str = timestamp
        else:
            timestamp_str = timestamp.isoformat()

        message = {
            "type": "trade_update",
            "symbol": symbol,
            "price": price,
            "size": size,
            "timestamp": timestamp_str,
            "exchange": exchange,
        }
        await _broadcast(message)
    except Exception as exc:
        logger.debug(f"Failed to broadcast trade to UI: {exc}")


async def combined_trade_cache_handler(trade):
    """Combined handler: log AND save to cache for batched writes.

    This is the recommended handler for live WebSocket streams.

    Args:
        trade: Either Alpaca trade object OR dict with trade data
    """
    if isinstance(trade, dict):
        symbol = trade['symbol']
        price = trade['price']
        size = trade['size']
        exchange = trade.get('exchange', 'N/A')
        timestamp = trade['timestamp']
    else:
        symbol = trade.symbol
        price = trade.price
        size = trade.size
        exchange = trade.exchange if hasattr(trade, 'exchange') else 'N/A'
        timestamp = trade.timestamp

    logger.info(f"[TRADE] {symbol} @ ${price:.2f} x {size} | "
                f"Exchange: {exchange} | {timestamp}")

    await save_trade_to_cache(trade)
    await broadcast_trade_to_ui(trade)


async def combined_bar_handler(bar, timeframe: str = '1Min'):
    """Combined handler: log AND save to database.

    Args:
        bar: Either Alpaca bar object OR dict with bar data
        timeframe: Bar timeframe string (default: '1Min')
    """
    if isinstance(bar, dict):
        symbol = bar['symbol']
        open_price = bar['open']
        high_price = bar['high']
        low_price = bar['low']
        close_price = bar['close']
        volume = bar['volume']
        timestamp = bar['timestamp']
    else:
        symbol = bar.symbol
        open_price = bar.open
        high_price = bar.high
        low_price = bar.low
        close_price = bar.close
        volume = bar.volume
        timestamp = bar.timestamp

    logger.info(f"[BAR] {symbol} | O: ${open_price:.2f} H: ${high_price:.2f} "
                f"L: ${low_price:.2f} C: ${close_price:.2f} | "
                f"Vol: {volume:,} | {timestamp}")

    await save_bar_to_db(bar, timeframe=timeframe)


async def combined_trade_correction_handler(correction):
    """Combined handler: log AND handle trade correction.

    Args:
        correction: Alpaca trade correction object
    """
    logger.info(f"[CORRECTION] {correction.symbol} trade_id={correction.id} | "
                f"New price: ${correction.price:.2f} | Size: {correction.size}")

    await handle_trade_correction(correction)


async def combined_trade_cancellation_handler(cancellation):
    """Combined handler: log AND handle trade cancellation.

    Args:
        cancellation: Alpaca trade cancellation object
    """
    logger.info(f"[CANCEL] {cancellation.symbol} trade_id={cancellation.id} | Trade cancelled/error")

    await handle_trade_cancellation(cancellation)


async def _background_flush_task():
    """Background task that periodically flushes cache to database.

    This task runs in the background and checks the cache every minute.
    If the cache needs flushing (based on time or size thresholds),
    it flushes to the database.

    This task runs indefinitely until cancelled.
    """
    check_interval = 60  # Check every minute

    logger.info("Background flush task started")

    try:
        while True:
            await asyncio.sleep(check_interval)

            cache = get_cache()
            stats = cache.get_stats()

            if stats['current_size'] > 0:
                time_threshold = stats['batch_interval_seconds']
                time_elapsed = stats['time_since_flush_seconds']

                if time_elapsed >= time_threshold:
                    logger.info(
                        f"Background flush triggered: {stats['current_size']:,} trades, "
                        f"{time_elapsed:.0f}s since last flush"
                    )
                    await flush_cache_to_db()

    except asyncio.CancelledError:
        logger.info("Background flush task cancelled")
        await flush_cache_to_db()
        raise
    except Exception as e:
        logger.error(f"Background flush task error: {e}", exc_info=True)


def start_background_flush_task():
    """Start the background flush task.

    Returns:
        asyncio.Task: The background task handle

    Note: Call this once when starting the WebSocket stream.
    """
    global _flush_task

    if _flush_task is not None and not _flush_task.done():
        logger.warning("Background flush task already running")
        return _flush_task

    _flush_task = asyncio.create_task(_background_flush_task())
    logger.info("Background flush task created")

    return _flush_task


async def stop_background_flush_task():
    """Stop the background flush task gracefully.

    This will cancel the task and flush any remaining cached trades.

    Note: Call this when shutting down the WebSocket stream.
    """
    global _flush_task

    if _flush_task is None:
        logger.warning("No background flush task to stop")
        return

    if not _flush_task.done():
        logger.info("Stopping background flush task...")
        _flush_task.cancel()

        try:
            await _flush_task
        except asyncio.CancelledError:
            logger.info("Background flush task stopped")

    _flush_task = None


if __name__ == "__main__":
    """Smoke test — verify module imports and core callables are present."""
    import inspect

    print("=" * 60)
    print("stream_handlers.py smoke test")
    print("=" * 60)

    fns = [
        set_ws_broadcaster, save_trade_to_db, save_trade_to_cache,
        flush_cache_to_db, save_bar_to_db, broadcast_bar_to_ui,
        combined_trade_handler, combined_bar_handler,
        combined_trade_cache_handler, combined_trade_correction_handler,
        combined_trade_cancellation_handler,
        start_background_flush_task, stop_background_flush_task,
    ]

    for fn in fns:
        assert callable(fn), f"Not callable: {fn.__name__}"
        print(f"  [OK] {fn.__name__}")

    print("\n[ALL OK] stream_handlers smoke test passed")
    print("=" * 60)
