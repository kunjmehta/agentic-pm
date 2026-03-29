"""Database-backed stream handlers for Alpaca real-time data.

This module provides async handlers that save stream data (trades, bars) to
the database using DAOs. Handlers can be used standalone or combined with
print/logging for visibility.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import asyncio
from src.common.dao import AlpacaDAO
from src.common.data_gatherer.trade_cache import get_cache
from src.common.utils import get_logger, config


# Initialize logger
logger = get_logger(__name__)

# Module-level DAO instance (singleton)
_dao = None

# Background flush task handle
_flush_task = None


def get_dao() -> AlpacaDAO:
    """Get or create DAO instance.

    Returns:
        AlpacaDAO instance (singleton)
    """
    global _dao
    if _dao is None:
        _dao = AlpacaDAO()
        logger.info("AlpacaDAO instance created for stream handlers")
    return _dao


async def save_trade_to_db(trade):
    """Save trade data directly to database (no caching).

    Args:
        trade: Alpaca trade object with attributes: symbol, timestamp, price,
               size, exchange, conditions, id, tape

    Note: This bypasses the cache. Use save_trade_to_cache() for batched writes.
    """
    try:
        dao = get_dao()

        # Convert trade object to DataFrame
        trade_data = pd.DataFrame([{
            'symbol': trade.symbol,
            'timestamp': trade.timestamp,
            'trade_id': trade.id,
            'price': float(trade.price),
            'size': int(trade.size),
            'exchange': trade.exchange if hasattr(trade, 'exchange') else None,
            'conditions': ','.join(trade.conditions) if hasattr(trade, 'conditions') and trade.conditions else '',
            'tape': trade.tape if hasattr(trade, 'tape') else None
        }])

        # Save to database
        dao.save_trades(trade_data)
        logger.debug(f"Saved trade to DB: {trade.symbol} @ ${trade.price:.2f}")

    except Exception as e:
        logger.error(f"Failed to save trade to DB: {e}", exc_info=True)


async def save_trade_to_cache(trade):
    """Save trade data to cache for batched database writes.

    This is the recommended handler for live WebSocket streams as it reduces
    database write frequency by batching trades in memory.

    Args:
        trade: Alpaca trade object with attributes: symbol, timestamp, price,
               size, exchange, conditions, id, tape
    """
    try:
        cache = get_cache()

        # Convert trade object to dict
        trade_data = {
            'symbol': trade.symbol,
            'timestamp': trade.timestamp,
            'trade_id': trade.id,
            'price': float(trade.price),
            'size': int(trade.size),
            'exchange': trade.exchange if hasattr(trade, 'exchange') else None,
            'conditions': ','.join(trade.conditions) if hasattr(trade, 'conditions') and trade.conditions else '',
            'tape': trade.tape if hasattr(trade, 'tape') else None
        }

        # Add to cache
        should_flush = cache.add_trade(trade_data)

        logger.debug(f"Added trade to cache: {trade.symbol} @ ${trade.price:.2f}")

        # Flush if threshold met
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
        dao = get_dao()

        symbol = correction.symbol
        trade_id = correction.id  # Original trade ID
        corrected_price = float(correction.price)
        corrected_size = int(correction.size)

        # Build correction data
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

        # Try to update in cache first
        updated_in_cache = cache.update_trade(correction_data)

        if updated_in_cache:
            logger.info(f"Trade correction applied in cache: {symbol} trade_id={trade_id}")
        else:
            # Trade not in cache - must be already flushed to DB
            # Update directly in database
            logger.info(f"Trade not in cache, updating in database: {symbol} trade_id={trade_id}")

            # Create DataFrame for the correction
            correction_df = pd.DataFrame([correction_data])

            # Update in database (upsert)
            dao.save_trades(correction_df)
            logger.info(f"Trade correction applied in database: {symbol} trade_id={trade_id}")

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
        dao = get_dao()

        symbol = cancellation.symbol
        trade_id = cancellation.id  # Trade ID to cancel

        # Try to cancel in cache first
        cancelled_in_cache = cache.cancel_trade(symbol, trade_id)

        if cancelled_in_cache:
            logger.info(f"Trade cancelled in cache: {symbol} trade_id={trade_id}")
        else:
            # Trade not in cache - must be already flushed to DB
            # Delete from database
            logger.info(f"Trade not in cache, deleting from database: {symbol} trade_id={trade_id}")

            # Execute DELETE query
            query = """
                DELETE FROM historical_trades
                WHERE symbol = ? AND trade_id = ?
            """
            dao.execute(query, (symbol, trade_id))
            logger.info(f"Trade cancelled in database: {symbol} trade_id={trade_id}")

    except Exception as e:
        logger.error(f"Failed to handle trade cancellation: {e}", exc_info=True)


async def flush_cache_to_db():
    """Flush cached trades to live_trades table in database.

    This function is called automatically when cache thresholds are met,
    or can be called manually to force a flush.
    """
    try:
        cache = get_cache()
        dao = get_dao()

        # Get all cached trades
        df = cache.flush()

        if df.empty:
            logger.debug("No trades to flush from cache")
            return

        # Save to live_trades table (staging)
        # Note: We'll need to add this method to AlpacaDAO
        if hasattr(dao, 'save_live_trades'):
            rows = dao.save_live_trades(df)
        else:
            # Fallback: save to historical_trades with source='stream'
            rows = dao.save_trades(df)

        logger.info(f"Flushed {len(df):,} trades to database ({rows} rows affected)")

    except Exception as e:
        logger.error(f"Failed to flush cache to DB: {e}", exc_info=True)


async def save_bar_to_db(bar, timeframe: str = '1Min'):
    """Save bar data to database and automatically compute indicators.

    This function implements the auto-run ETL pipeline:
    1. Save bar to database
    2. Fetch recent bars (lookback window)
    3. Compute indicators
    4. Save computed indicators

    Args:
        bar: Alpaca bar object with attributes: symbol, timestamp, open, high,
             low, close, volume, trade_count, vwap
        timeframe: Bar timeframe string (default: '1Min')
    """
    try:
        dao = get_dao()

        # Convert bar object to DataFrame
        bar_data = pd.DataFrame([{
            'symbol': bar.symbol,
            'timestamp': bar.timestamp,
            'open': float(bar.open),
            'high': float(bar.high),
            'low': float(bar.low),
            'close': float(bar.close),
            'volume': int(bar.volume),
            'trade_count': int(bar.trade_count) if hasattr(bar, 'trade_count') else None,
            'vwap': float(bar.vwap) if hasattr(bar, 'vwap') else None
        }])

        # Save bar to database
        dao.save_bars(bar_data, timeframe=timeframe)
        logger.debug(f"Saved bar to DB: {bar.symbol} @ {bar.timestamp}")

        # Auto-compute indicators if enabled
        etl_enabled = config.get("etl.enabled", default=True)
        if etl_enabled:
            logger.debug(f"Auto-computing indicators for {bar.symbol} {timeframe}")
            await _compute_and_save_indicators(bar.symbol, timeframe, dao)
        else:
            logger.warning(f"ETL disabled - skipping indicator computation for {bar.symbol}")

    except Exception as e:
        logger.error(f"Failed to save bar to DB: {e}", exc_info=True)


async def _compute_and_save_indicators(symbol: str, timeframe: str, dao: AlpacaDAO):
    """Compute indicators for the most recent bar and save to database.

    This runs automatically after each bar is saved, ensuring indicators
    are always up-to-date without needing a separate scheduler.

    Args:
        symbol: Stock symbol
        timeframe: Bar timeframe
        dao: AlpacaDAO instance
    """
    try:
        from src.common.etl.indicators_engine import IndicatorsEngine
        from datetime import datetime, timedelta

        # Get lookback period from config (default 60 days)
        lookback_days = config.get("etl.lookback_days", default=60)

        # Fetch recent bars (lookback window)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)

        bars = dao.get_bars(
            symbol=symbol,
            start=start_date,
            end=end_date,
            timeframe=timeframe
        )

        if bars.empty or len(bars) < 60:
            logger.info(f"⏳ Insufficient data for {symbol} {timeframe} - have {len(bars)} bars, need 60+")
            return

        # Compute indicators
        engine = IndicatorsEngine()

        # Calculate indicators for ALL rows (rolling window)
        indicator_rows = []
        for i in range(60, len(bars) + 1):  # Need minimum 60 bars for mean reversion
            window_data = bars.iloc[:i].copy()
            result = engine.calc_all(window_data)

            # Get the timestamp for this row
            timestamp = window_data.iloc[-1]['timestamp']

            # Flatten result into a single row
            row = {
                'symbol': symbol,
                'timestamp': timestamp,
                'timeframe': timeframe,

                # Momentum
                'macd_value': result['momentum']['macd']['value'],
                'macd_signal': result['momentum']['macd']['signal'],
                'macd_histogram': result['momentum']['macd']['histogram'],
                'rsi': result['momentum']['rsi'],

                # Volatility
                'bb_upper': result['volatility']['upper'],
                'bb_middle': result['volatility']['middle'],
                'bb_lower': result['volatility']['lower'],
                'bb_bandwidth': result['volatility']['bandwidth'],

                # Volume
                'obv': result['volume']['obv'],
                'volume_trend': result['volume']['trend'],
                'avg_volume_10d': result['volume']['avg_volume_10d'],
                'current_vs_avg': result['volume']['current_vs_avg'],

                # Mean reversion
                'z_score': result['mean_reversion']['z_score'],
                'percentile': result['mean_reversion']['percentile'],
                'vwap': result['mean_reversion']['vwap']
            }
            indicator_rows.append(row)

        # Convert to DataFrame
        indicators_df = pd.DataFrame(indicator_rows)

        # Save to database (upsert to handle duplicates)
        if hasattr(dao, 'save_computed_indicators'):
            rows = dao.save_computed_indicators(indicators_df)
            logger.info(f"✓ Computed and saved {rows} indicators for {symbol} {timeframe} (from {len(bars)} bars)")
        else:
            logger.error("❌ AlpacaDAO.save_computed_indicators() method missing - cannot save indicators")

    except Exception as e:
        logger.error(f"❌ Failed to compute/save indicators for {symbol} {timeframe}: {e}", exc_info=True)
        logger.error(f"   Context: {len(bars) if 'bars' in locals() else 'unknown'} bars fetched")


async def combined_trade_handler(trade):
    """Combined handler: print AND save to database (direct, no cache).

    Args:
        trade: Alpaca trade object

    Note: This bypasses cache. Use combined_trade_cache_handler() for batched writes.
    """
    # Log for visibility
    logger.info(f"[TRADE] {trade.symbol} @ ${trade.price:.2f} x {trade.size} | "
          f"Exchange: {trade.exchange} | {trade.timestamp}")

    # Save to database
    await save_trade_to_db(trade)


async def combined_trade_cache_handler(trade):
    """Combined handler: print AND save to cache for batched writes.

    This is the recommended handler for live WebSocket streams.

    Args:
        trade: Alpaca trade object
    """
    # Print for visibility
    print(f"[TRADE] {trade.symbol} @ ${trade.price:.2f} x {trade.size} | "
          f"Exchange: {trade.exchange} | {trade.timestamp}")

    # Save to cache
    await save_trade_to_cache(trade)


async def combined_bar_handler(bar, timeframe: str = '1Min'):
    """Combined handler: print AND save to database.

    Args:
        bar: Alpaca bar object
        timeframe: Bar timeframe string (default: '1Min')
    """
    # Print for visibility
    print(f"[BAR] {bar.symbol} | O: ${bar.open:.2f} H: ${bar.high:.2f} "
          f"L: ${bar.low:.2f} C: ${bar.close:.2f} | "
          f"Vol: {bar.volume:,} | {bar.timestamp}")

    # Save to database
    await save_bar_to_db(bar, timeframe=timeframe)


async def combined_trade_correction_handler(correction):
    """Combined handler: print AND handle trade correction.

    Args:
        correction: Alpaca trade correction object
    """
    # Print for visibility
    print(f"[CORRECTION] {correction.symbol} trade_id={correction.id} | "
          f"New price: ${correction.price:.2f} | Size: {correction.size}")

    # Handle correction (cache or database)
    await handle_trade_correction(correction)


async def combined_trade_cancellation_handler(cancellation):
    """Combined handler: print AND handle trade cancellation.

    Args:
        cancellation: Alpaca trade cancellation object
    """
    # Print for visibility
    print(f"[CANCEL] {cancellation.symbol} trade_id={cancellation.id} | Trade cancelled/error")

    # Handle cancellation (cache or database)
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

            # Check if flush is needed
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
        # Flush remaining trades before exiting
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
    """Test the DB handlers."""
    import asyncio
    from datetime import datetime

    # Mock trade object for testing
    class MockTrade:
        def __init__(self):
            self.symbol = "TEST"
            self.timestamp = datetime.now()
            self.id = 123456789
            self.price = 150.50
            self.size = 100
            self.exchange = "Q"
            self.conditions = ["@"]
            self.tape = "C"

    # Mock bar object for testing
    class MockBar:
        def __init__(self):
            self.symbol = "TEST"
            self.timestamp = datetime.now()
            self.open = 150.00
            self.high = 151.50
            self.low = 149.50
            self.close = 150.50
            self.volume = 1000000
            self.trade_count = 500
            self.vwap = 150.25

    async def test_handlers():
        """Test the handlers with mock data."""
        print("="*60)
        print("Testing DB Stream Handlers")
        print("="*60)

        # Test trade handler
        print("\n1. Testing save_trade_to_db()...")
        mock_trade = MockTrade()
        await save_trade_to_db(mock_trade)
        print("   [OK] Trade saved")

        # Test bar handler
        print("\n2. Testing save_bar_to_db()...")
        mock_bar = MockBar()
        await save_bar_to_db(mock_bar, timeframe='1Min')
        print("   [OK] Bar saved")

        # Test combined handlers
        print("\n3. Testing combined_trade_handler()...")
        await combined_trade_handler(mock_trade)
        print("   [OK] Combined trade handler")

        print("\n4. Testing combined_bar_handler()...")
        await combined_bar_handler(mock_bar, timeframe='1Min')
        print("   [OK] Combined bar handler")

        # Verify data was saved
        print("\n5. Verifying saved data...")
        dao = get_dao()

        from datetime import timedelta
        end = datetime.now()
        start = end - timedelta(minutes=5)

        trades = dao.get_trades("TEST", start=start, end=end)
        bars = dao.get_bars("TEST", start=start, end=end, timeframe='1Min')

        print(f"   [OK] Retrieved {len(trades)} trades from DB")
        print(f"   [OK] Retrieved {len(bars)} bars from DB")

        # Cleanup
        print("\n6. Cleaning up test data...")
        dao.execute("DELETE FROM historical_trades WHERE symbol = 'TEST'")
        dao.execute("DELETE FROM market_bars WHERE symbol = 'TEST'")
        dao.close()
        print("   [OK] Test complete")

        print("\n" + "="*60)

    # Run test
    asyncio.run(test_handlers())
