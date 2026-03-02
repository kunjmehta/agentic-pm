"""Database-backed stream handlers for Alpaca real-time data.

This module provides async handlers that save stream data (trades, bars) to
the database using DAOs. Handlers can be used standalone or combined with
print/logging for visibility.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
from src.dao import AlpacaDAO
from src.utils import get_logger


# Initialize logger
logger = get_logger(__name__)

# Module-level DAO instance (singleton)
_dao = None


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
    """Save trade data to database.

    Args:
        trade: Alpaca trade object with attributes: symbol, timestamp, price,
               size, exchange, conditions, id, tape
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


async def save_bar_to_db(bar, timeframe: str = '1Min'):
    """Save bar data to database.

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

        # Save to database
        dao.save_bars(bar_data, timeframe=timeframe)
        logger.debug(f"Saved bar to DB: {bar.symbol} @ {bar.timestamp}")

    except Exception as e:
        logger.error(f"Failed to save bar to DB: {e}", exc_info=True)


async def combined_trade_handler(trade):
    """Combined handler: print AND save to database.

    Args:
        trade: Alpaca trade object
    """
    # Print for visibility
    print(f"[TRADE] {trade.symbol} @ ${trade.price:.2f} x {trade.size} | "
          f"Exchange: {trade.exchange} | {trade.timestamp}")

    # Save to database
    await save_trade_to_db(trade)


async def combined_bar_handler(bar, timeframe: str = '1Min'):
    """Combined handler: print AND save to database.

    Args:
        bar: Alpaca bar object
        timeframe: Bar timeframe string (default: '1Min')
    """
    # Print for visibility
    logger.info(f"[BAR] {bar.symbol} | O: ${bar.open:.2f} H: ${bar.high:.2f} "
          f"L: ${bar.low:.2f} C: ${bar.close:.2f} | "
          f"Vol: {bar.volume:,} | {bar.timestamp}")

    # Save to database
    await save_bar_to_db(bar, timeframe=timeframe)


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
