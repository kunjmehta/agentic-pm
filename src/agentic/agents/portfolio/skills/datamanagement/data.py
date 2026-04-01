"""Data Management Skill - Fetch and verify historical data availability."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import argparse
from datetime import datetime
from typing import Dict

from src.common.external.alpaca import fetch_historical_bars
from src.common.dao import AlpacaDAO
from src.common.utils import get_logger

logger = get_logger(__name__)


def fetch_historical_data_core(symbol: str, start_date: str, end_date: str, timeframe: str = "1Min") -> Dict:
    """Fetch historical market data and save to database.

    Args:
        symbol: Stock ticker
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        timeframe: Bar timeframe

    Returns:
        Dict with fetch status
    """
    # Convert date strings to datetime objects
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date)

    # Validate dates
    now = datetime.now()
    if start_dt > now or end_dt > now:
        return {
            "status": "error",
            "error": "Future dates not allowed",
            "message": f"Start or end date is in the future. Current date: {now.date()}",
            "suggestion": f"Use dates up to {now.date()}"
        }

    # Check if data already exists — close DAO before fetching to avoid DuckDB write lock conflict
    dao = AlpacaDAO()
    existing_bars = dao.get_bars(symbol, start=start_dt, end=end_dt, timeframe=timeframe)
    dao.close()

    if not existing_bars.empty:
        bar_count = len(existing_bars)
        return {
            "status": "success",
            "bars_fetched": bar_count,
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "timeframe": timeframe,
            "message": f"Data already available: {bar_count} bars found in database",
            "data_source": "database_cache"
        }

    # Fetch from API (fetch_historical_bars opens its own DAO to save bars)
    bars_df = fetch_historical_bars(symbol=symbol, start=start_date, end=end_date, timeframe=timeframe)

    if bars_df is None or bars_df.empty:
        return {
            "status": "error",
            "error": "No data returned from API",
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "message": f"Alpaca API returned no data for {symbol}",
            "suggestion": "Verify symbol and date range"
        }

    bar_count = len(bars_df)
    return {
        "status": "success",
        "bars_fetched": bar_count,
        "symbol": symbol,
        "date_range": f"{start_date} to {end_date}",
        "timeframe": timeframe,
        "message": f"Successfully fetched {bar_count} bars from Alpaca API",
        "data_source": "alpaca_api"
    }


def check_data_availability_core(symbol: str, start_date: str, end_date: str, timeframe: str = "1Min") -> Dict:
    """Check if historical data exists in database.

    Args:
        symbol: Stock ticker
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        timeframe: Bar timeframe

    Returns:
        Dict with availability status
    """
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date)

    dao = AlpacaDAO()
    bars_df = dao.get_bars(symbol, start=start_dt, end=end_dt, timeframe=timeframe)

    bar_count = len(bars_df)

    # Calculate expected bars
    trading_days = (end_dt - start_dt).days
    expected_bars = trading_days * 390 if timeframe == "1Min" else trading_days
    coverage_pct = (bar_count / expected_bars * 100) if expected_bars > 0 else 0

    if bar_count == 0:
        return {
            "available": False,
            "bar_count": 0,
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "message": f"No data found for {symbol}",
            "action_needed": "fetch_historical_data"
        }
    elif coverage_pct < 80:
        return {
            "available": "partial",
            "bar_count": bar_count,
            "expected_bars": expected_bars,
            "coverage_pct": round(coverage_pct, 1),
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "message": f"Partial data: {bar_count} bars ({coverage_pct:.1f}% coverage)",
            "action_needed": "fetch_historical_data to fill gaps"
        }
    else:
        return {
            "available": True,
            "bar_count": bar_count,
            "expected_bars": expected_bars,
            "coverage_pct": round(coverage_pct, 1),
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "message": f"Data available: {bar_count} bars",
            "action_needed": "none"
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage historical data")
    parser.add_argument("--action", choices=["fetch", "check"], required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--timeframe", default="1Min")
    args = parser.parse_args()

    try:
        if args.action == "fetch":
            result = fetch_historical_data_core(args.symbol, args.start, args.end, args.timeframe)
        else:
            result = check_data_availability_core(args.symbol, args.start, args.end, args.timeframe)

        print(json.dumps(result, indent=2))

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)
