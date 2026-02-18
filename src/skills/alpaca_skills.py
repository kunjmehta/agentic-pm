"""Alpaca API integration functions for market data and trading.

This module provides functions to interact with Alpaca's REST API and WebSocket streams
for historical and real-time market data.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable
import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockTradesRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.live import StockDataStream


# Load secrets from secret.json
def _load_secrets():
    """Load API credentials from secret.json file."""
    secret_path = Path(__file__).parent.parent.parent / "config" / "secret.json"
    if not secret_path.exists():
        raise FileNotFoundError(
            f"secret.json not found at {secret_path}. "
            "Please create it from secret.json.example"
        )
    with open(secret_path, "r") as f:
        return json.load(f)


secrets = _load_secrets()

# Initialize Alpaca client
API_KEY = secrets["alpaca"]["api_key"]
SECRET_KEY = secrets["alpaca"]["secret_key"]
BASE_URL = secrets["alpaca"]["base_url"]

# Initialize historical data client
historical_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)


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
        raise ValueError(f"Invalid timeframe: {timeframe}. Must be one of {list(timeframe_map.keys())}")

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

        return df

    except Exception as e:
        raise Exception(f"Failed to fetch historical bars for {symbol}: {str(e)}")


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

        return df

    except Exception as e:
        raise Exception(f"Failed to fetch historical trades for {symbol}: {str(e)}")


async def subscribe_to_bars(
    symbol: str,
    callback: Callable[[dict], None],
    timeframe: str = "1Min"
) -> None:
    """Subscribe to real-time bar data via Alpaca WebSocket.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        callback: Function to call when new bar data arrives
        timeframe: Currently only "1Min" supported by Alpaca WebSocket

    Raises:
        Exception: If WebSocket connection fails
    """
    try:
        # Initialize WebSocket stream
        stream = StockDataStream(API_KEY, SECRET_KEY)

        # Define bar handler
        async def bar_handler(data):
            """Process incoming bar data and call user callback."""
            bar_dict = {
                "symbol": data.symbol,
                "timestamp": data.timestamp,
                "open": data.open,
                "high": data.high,
                "low": data.low,
                "close": data.close,
                "volume": data.volume,
            }
            callback(bar_dict)

        # Subscribe to bars
        stream.subscribe_bars(bar_handler, symbol)

        # Run the stream
        await stream.run()

    except Exception as e:
        raise Exception(f"Failed to subscribe to bars for {symbol}: {str(e)}")


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

    # Fetch historical trades
    if include_trades:
        try:
            results["trades"] = fetch_historical_trades(symbol, start, end, trades_limit)
        except Exception as e:
            results["errors"]["trades"] = str(e)

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

    # Test 3: WebSocket subscription (optional, comment out if not needed)
    print(f"\n3. Testing WebSocket subscription (will run for 10 seconds)...")
    print("   (Uncomment to test live streaming)")

    # Uncomment below to test WebSocket
    def on_bar(bar_data):
        print(f"   Bar received: {bar_data}")
    
    async def test_websocket():
        try:
            task = asyncio.create_task(subscribe_to_bars(test_symbol, on_bar))
            await asyncio.sleep(10)  # Run for 10 seconds
            task.cancel()
            print("   ✓ WebSocket test completed")
        except Exception as e:
            print(f"   ✗ Error: {e}")
    
    asyncio.run(test_websocket())

    print("\n" + "=" * 60)
    print("Alpaca API Tests Complete")
    print("=" * 60)
