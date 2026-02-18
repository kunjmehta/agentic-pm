"""Alpaca API integration functions for market data and trading.

This module provides functions to interact with Alpaca's REST API and WebSocket streams
for historical and real-time market data.
"""

from datetime import datetime
from typing import Optional
import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockTradesRequest
from alpaca.data.timeframe import TimeFrame
from src.utils import secrets, get_logger


# Initialize logger
logger = get_logger(__name__)

# Initialize Alpaca client with credentials from secrets
API_KEY = secrets.get("alpaca.api_key")
SECRET_KEY = secrets.get("alpaca.secret_key")
BASE_URL = secrets.get("alpaca.base_url")

# Initialize historical data client
historical_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
logger.info("Alpaca historical client initialized")


def fetch_historical_bars(
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1Min"
) -> pd.DataFrame:
    """Fetch historical OHLCV bar data from Alpaca.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        start: Start date in ISO format (e.g., "2024-01-01")
        end: End date in ISO format (e.g., "2024-01-31")
        timeframe: Bar interval - "1Min", "5Min", "15Min", "1Hour", "1Day"

    Returns:
        DataFrame with columns: open, high, low, close, volume, timestamp

    Raises:
        ValueError: If timeframe is invalid
        Exception: If API request fails
    """
    # Map timeframe string to Alpaca TimeFrame enum
    timeframe_map = {
        "1Min": TimeFrame.Minute,
        "5Min": TimeFrame(5, "Min"),
        "15Min": TimeFrame(15, "Min"),
        "1Hour": TimeFrame.Hour,
        "1Day": TimeFrame.Day,
    }

    if timeframe not in timeframe_map:
        error_msg = f"Invalid timeframe: {timeframe}. Must be one of {list(timeframe_map.keys())}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    logger.info(f"Fetching historical bars for {symbol}: {start} to {end}, timeframe={timeframe}")

    try:
        request_params = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe_map[timeframe],
            start=datetime.fromisoformat(start),
            end=datetime.fromisoformat(end)
        )

        bars = historical_client.get_stock_bars(request_params)
        df = bars.df

        # Reset index to make symbol and timestamp columns
        df = df.reset_index()

        logger.info(f"Successfully fetched {len(df)} bars for {symbol}")
        return df

    except Exception as e:
        error_msg = f"Failed to fetch historical bars for {symbol}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg)


def fetch_historical_trades(
    symbol: str,
    start: str,
    end: str,
    limit: Optional[int] = 10000
) -> pd.DataFrame:
    """Fetch historical trade data from Alpaca.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        start: Start date in ISO format (e.g., "2024-01-01")
        end: End date in ISO format (e.g., "2024-01-31")
        limit: Maximum number of trades to fetch (default: 10000)

    Returns:
        DataFrame with columns: price, size, exchange, timestamp, conditions

    Raises:
        Exception: If API request fails
    """
    logger.info(f"Fetching historical trades for {symbol}: {start} to {end}, limit={limit}")

    try:
        request_params = StockTradesRequest(
            symbol_or_symbols=symbol,
            start=datetime.fromisoformat(start),
            end=datetime.fromisoformat(end),
            limit=limit
        )

        trades = historical_client.get_stock_trades(request_params)
        df = trades.df

        # Reset index to make symbol and timestamp columns
        df = df.reset_index()

        logger.info(f"Successfully fetched {len(df)} trades for {symbol}")
        return df

    except Exception as e:
        error_msg = f"Failed to fetch historical trades for {symbol}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg)


def fetch_all(
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1Min",
    include_trades: bool = True,
    trades_limit: int = 10000
) -> dict:
    """Fetch all available historical market data for a symbol.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        start: Start date in ISO format (e.g., "2024-01-01")
        end: End date in ISO format (e.g., "2024-01-31")
        timeframe: Bar interval for OHLCV data - "1Min", "5Min", "15Min", "1Hour", "1Day"
        include_trades: Whether to fetch historical trades (default: True)
        trades_limit: Maximum number of trades to fetch (default: 10000)

    Returns:
        Dictionary containing:
        - symbol: Stock ticker
        - start_date: Start date
        - end_date: End date
        - bars: Historical OHLCV data (DataFrame)
        - trades: Historical trade data (DataFrame) if include_trades=True
        - errors: Dict of any errors encountered

    Raises:
        Exception: If critical data fetch fails
    """
    logger.info(f"Fetching all Alpaca data for {symbol}: {start} to {end}")

    results = {
        "symbol": symbol,
        "start_date": start,
        "end_date": end,
        "timeframe": timeframe,
        "bars": None,
        "trades": None,
        "errors": {}
    }

    # Fetch historical bars
    try:
        results["bars"] = fetch_historical_bars(symbol, start, end, timeframe)
    except Exception as e:
        results["errors"]["bars"] = str(e)
        logger.warning(f"Failed to fetch bars for {symbol}: {e}")

    # Fetch historical trades
    if include_trades:
        try:
            results["trades"] = fetch_historical_trades(symbol, start, end, trades_limit)
        except Exception as e:
            results["errors"]["trades"] = str(e)
            logger.warning(f"Failed to fetch trades for {symbol}: {e}")

    logger.info(f"Completed fetching data for {symbol}: {len(results['errors'])} errors")
    return results


if __name__ == "__main__":
    """Test Alpaca API functions."""
    import asyncio

    print("=" * 60)
    print("Testing Alpaca API Functions")
    print("=" * 60)

    # Test parameters
    test_symbol = "AAPL"
    test_start = "2024-01-02"
    test_end = "2024-01-03"

    # Test 1: Fetch historical bars
    print(f"\n1. Fetching historical bars for {test_symbol}...")
    try:
        bars_df = fetch_historical_bars(test_symbol, test_start, test_end, "1Hour")
        print(f"   ✓ Fetched {len(bars_df)} bars")
        print(f"   Sample data:\n{bars_df.head()}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 2: Fetch historical trades
    print(f"\n2. Fetching historical trades for {test_symbol}...")
    try:
        trades_df = fetch_historical_trades(test_symbol, test_start, test_end, limit=100)
        print(f"   ✓ Fetched {len(trades_df)} trades")
        print(f"   Sample data:\n{trades_df.head()}")
    except Exception as e:
        print(f"   ✗ Error: {e}")


    print("\n" + "=" * 60)
    print("Alpaca API Tests Complete")
    print("=" * 60)
