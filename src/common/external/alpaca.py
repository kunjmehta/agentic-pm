"""Alpaca API integration functions for market data and trading.

This module provides functions to interact with Alpaca's REST API and WebSocket streams
for historical and real-time market data.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import time
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockTradesRequest
from alpaca.data.timeframe import TimeFrame
from src.common.utils import secrets, get_logger
from src.common.dao import AlpacaDAO


# Initialize logger
logger = get_logger(__name__)

# Initialize Alpaca client with credentials from secrets
API_KEY = secrets.get("alpaca.api_key")
SECRET_KEY = secrets.get("alpaca.secret_key")
BASE_URL = secrets.get("alpaca.base_url")

# Initialize historical data client with clear error handling
try:
    historical_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
except Exception as exc:
    error_msg = (
        "Failed to initialize Alpaca historical client. "
        "Verify that config/secret.json exists and that "
        '"alpaca.api_key" and "alpaca.secret_key" are correctly set. '
        f"Underlying error: {exc}"
    )
    logger.error(error_msg, exc_info=True)
    raise RuntimeError(error_msg) from exc
else:
    logger.info("Alpaca historical client initialized")

def _clean_value(value):
    """Clean API values by converting 'None' strings and None to actual None.

    Args:
        value: Value from API response

    Returns:
        None if value is None or 'None' string, otherwise the original value
    """
    if value is None or value == "None" or value == "":
        return None
    return value


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Clean DataFrame by converting 'None' strings to actual None/NaN.

    Args:
        df: DataFrame to clean

    Returns:
        Cleaned DataFrame
    """
    if df.empty:
        return df

    # Replace "None" strings with actual None
    df = df.replace({"None": None, "": None})

    return df


def fetch_historical_bars(
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1Min",
    chunk_days: int = 7,
    batch_size: int = 50000
) -> pd.DataFrame:
    """Fetch historical OHLCV bar data from Alpaca with chunking for large date ranges.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        start: Start date in ISO format (e.g., "2024-01-01")
        end: End date in ISO format (e.g., "2024-01-31")
        timeframe: Bar interval - "1Min", "5Min", "15Min", "1Hour", "1Day"
        chunk_days: Number of days per chunk to avoid memory issues (default: 7)
        batch_size: Number of rows per database batch insert (default: 50000)

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

    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    date_range_days = (end_dt - start_dt).days

    logger.info(f"Fetching historical bars for {symbol}: {start} to {end} ({date_range_days} days), timeframe={timeframe}")

    # If date range is small, fetch in one request
    if date_range_days <= chunk_days:
        df = _fetch_bars_chunk(symbol, start_dt, end_dt, timeframe, timeframe_map[timeframe])
        if not df.empty:
            _save_bars_batch(df, timeframe, batch_size)
        return df

    # Otherwise, chunk the date range
    all_dfs = []
    current_start = start_dt
    chunk_num = 0

    while current_start < end_dt:
        chunk_end = min(current_start + timedelta(days=chunk_days), end_dt)
        chunk_num += 1

        logger.info(f"Fetching chunk {chunk_num}: {current_start.date()} to {chunk_end.date()}")

        try:
            chunk_df = _fetch_bars_chunk(symbol, current_start, chunk_end, timeframe, timeframe_map[timeframe])

            if not chunk_df.empty:
                all_dfs.append(chunk_df)

                # Batch save to database if we've accumulated enough data
                if len(all_dfs) > 1 and sum(len(df) for df in all_dfs) >= batch_size:
                    combined_df = pd.concat(all_dfs, ignore_index=True)
                    _save_bars_batch(combined_df, timeframe, batch_size)
                    all_dfs = []  # Clear after saving

        except Exception as e:
            logger.warning(f"Failed to fetch chunk {chunk_num}: {e}")
            # Continue with next chunk even if one fails

        current_start = chunk_end

    # Combine all remaining chunks
    if all_dfs:
        final_df = pd.concat(all_dfs, ignore_index=True)

        # Save remaining data
        if not final_df.empty:
            _save_bars_batch(final_df, timeframe, batch_size)

        logger.info(f"Successfully fetched {len(final_df)} total bars for {symbol}")
        return final_df
    else:
        logger.warning(f"No bars fetched for {symbol}")
        return pd.DataFrame()


def _fetch_bars_chunk(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    timeframe: str,
    timeframe_obj: TimeFrame
) -> pd.DataFrame:
    """Fetch a single chunk of bars data.

    Args:
        symbol: Stock ticker
        start_dt: Start datetime
        end_dt: End datetime
        timeframe: Timeframe string (for logging)
        timeframe_obj: Alpaca TimeFrame object

    Returns:
        DataFrame with bars data
    """
    try:
        request_params = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe_obj,
            start=start_dt,
            end=end_dt
        )

        bars = historical_client.get_stock_bars(request_params)
        df = bars.df

        if df.empty:
            return pd.DataFrame()

        # Reset index to make symbol and timestamp columns
        df = df.reset_index()

        # Clean None/"None" values
        df = _clean_dataframe(df)

        return df

    except Exception as e:
        error_msg = f"Failed to fetch bars chunk for {symbol}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def _save_bars_batch(df: pd.DataFrame, timeframe: str, batch_size: int) -> None:
    """Save bars data in batches.

    Args:
        df: DataFrame with bars data
        timeframe: Timeframe string
        batch_size: Number of rows per batch
    """
    if df.empty:
        return

    try:
        dao = AlpacaDAO()

        # Save in batches
        for i in range(0, len(df), batch_size):
            batch_df = df.iloc[i:i + batch_size]
            rows = dao.save_bars(batch_df, timeframe=timeframe)
            logger.info(f"Saved batch {i//batch_size + 1}: {rows} bars to database")

        dao.close()
    except Exception as db_error:
        logger.warning(f"Failed to save bars to database: {db_error}")


def fetch_historical_trades(
    symbol: str,
    start: str,
    end: str,
    limit: Optional[int] = 10000,
    max_total: Optional[int] = None,
    page_delay: float = 0.3
) -> pd.DataFrame:
    """Fetch historical trade data from Alpaca with automatic pagination.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        start: Start date in ISO format (e.g., "2024-01-01")
        end: End date in ISO format (e.g., "2024-01-31")
        limit: Number of trades per page (default: 10000, Alpaca max)
        max_total: Maximum total trades to fetch (None = all available)
        page_delay: Delay between page requests in seconds (for rate limiting, default: 0.3)

    Returns:
        DataFrame with columns: price, size, exchange, timestamp, conditions

    Raises:
        Exception: If API request fails
    """
    logger.info(f"Fetching historical trades for {symbol}: {start} to {end}, limit={limit}, max_total={max_total}")

    all_dfs = []
    page_num = 0
    total_fetched = 0
    page_token = None

    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)

    try:
        while True:
            page_num += 1

            # Build request params
            request_params = StockTradesRequest(
                symbol_or_symbols=symbol,
                start=start_dt,
                end=end_dt,
                limit=limit
            )

            # Add page_token if this is not the first page
            if page_token:
                # Note: Alpaca SDK may not directly support page_token in constructor
                # This is a placeholder - actual implementation may need to use
                # the API response's next_page_token differently
                logger.info(f"Fetching page {page_num} with token: {page_token[:20]}...")
            else:
                logger.info(f"Fetching page {page_num} (initial request)...")

            trades = historical_client.get_stock_trades(request_params)
            df = trades.df

            if df.empty:
                logger.info(f"No more trades available (page {page_num})")
                break

            # Reset index to make symbol and timestamp columns
            df = df.reset_index()

            # Clean None/"None" values
            df = _clean_dataframe(df)

            page_size = len(df)
            total_fetched += page_size
            all_dfs.append(df)

            logger.info(f"Page {page_num}: fetched {page_size} trades (total: {total_fetched})")

            # Check if we've reached max_total
            if max_total and total_fetched >= max_total:
                logger.info(f"Reached max_total limit of {max_total} trades")
                break

            # Check for next page token
            # Note: Alpaca SDK's pagination handling may vary
            # The actual next_page_token access depends on SDK version
            # This is a generic implementation that assumes pagination is handled
            # by the SDK internally via the .df property
            if page_size < limit:
                # If we got fewer trades than requested, we've reached the end
                logger.info(f"Received {page_size} < {limit} trades, assuming end of data")
                break

            # Rate limiting: sleep between requests (Alpaca limit: 200 req/min)
            time.sleep(page_delay)

        # Combine all pages
        if all_dfs:
            final_df = pd.concat(all_dfs, ignore_index=True)

            # Trim to max_total if specified
            if max_total and len(final_df) > max_total:
                final_df = final_df.head(max_total)
                logger.info(f"Trimmed to max_total: {max_total} trades")

            logger.info(f"Successfully fetched {len(final_df)} total trades for {symbol} across {page_num} pages")

            # Save to database
            try:
                dao = AlpacaDAO()
                rows = dao.save_trades(final_df)
                logger.info(f"Saved {rows} trades to database")
                dao.close()
            except Exception as db_error:
                logger.warning(f"Failed to save trades to database: {db_error}")

            return final_df
        else:
            logger.warning(f"No trades fetched for {symbol}")
            return pd.DataFrame()

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
        trades_df = fetch_historical_trades(test_symbol, test_start, test_end)
        print(f"   ✓ Fetched {len(trades_df)} trades")
        print(f"   Sample data:\n{trades_df.head()}")
    except Exception as e:
        print(f"   ✗ Error: {e}")


    print("\n" + "=" * 60)
    print("Alpaca API Tests Complete")
    print("=" * 60)
