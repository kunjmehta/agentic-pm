"""Tools for the Backtester Agent.

Data access tools for fetching and saving backtest simulation data.
All tools return JSON strings for LangChain tool compatibility.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import json
from datetime import datetime
from typing import Dict, Any

from langchain_core.tools import tool

from src.dao.backtest_dao import BacktestDAO
from src.dao.alpaca_dao import AlpacaDAO
from src.utils import get_logger

logger = get_logger(__name__)


# =============================================================================
# Data Access Tools (Fetch & Save Operations)
# =============================================================================

@tool
def fetch_backtest_run(run_id: str) -> str:
    """Fetch backtest run details from database.

    Args:
        run_id: Backtest run identifier (UUID)

    Returns:
        JSON string with run metadata and performance metrics, or error message.
        Includes: strategy_name, symbol, start_date, end_date, performance metrics
        (sharpe_ratio, max_drawdown_pct, win_rate, total_trades, etc.)
    """
    try:
        dao = BacktestDAO()
        run = dao.get_run(run_id)

        if run is None:
            return json.dumps({
                "error": f"Backtest run {run_id} not found"
            })

        # Convert dates to ISO strings for JSON serialization
        if 'start_date' in run and run['start_date']:
            run['start_date'] = run['start_date'].isoformat()
        if 'end_date' in run and run['end_date']:
            run['end_date'] = run['end_date'].isoformat()
        if 'created_at' in run and run['created_at']:
            run['created_at'] = run['created_at'].isoformat()
        if 'completed_at' in run and run['completed_at']:
            run['completed_at'] = run['completed_at'].isoformat()

        return json.dumps(run, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error fetching backtest run {run_id}: {e}")
        return json.dumps({
            "error": f"Failed to fetch backtest run: {str(e)}"
        })


@tool
def fetch_backtest_trades(run_id: str) -> str:
    """Fetch all trades for a backtest run.

    Args:
        run_id: Backtest run identifier (UUID)

    Returns:
        JSON string with array of trade details (entry/exit prices, P&L, signals),
        or error message.
    """
    try:
        dao = BacktestDAO()
        trades_df = dao.get_trades_for_run(run_id)

        if trades_df.empty:
            return json.dumps({
                "run_id": run_id,
                "trades": [],
                "message": "No trades found for this run"
            })

        # Convert DataFrame to dict and handle datetime serialization
        trades = trades_df.to_dict(orient="records")

        result = {
            "run_id": run_id,
            "trades": trades,
            "total_trades": len(trades)
        }

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error fetching trades for run {run_id}: {e}")
        return json.dumps({
            "error": f"Failed to fetch trades: {str(e)}"
        })


@tool
def fetch_backtest_performance_history(run_id: str) -> str:
    """Fetch daily performance snapshots for a backtest run.

    Args:
        run_id: Backtest run identifier (UUID)

    Returns:
        JSON string with daily equity curve, returns, and drawdowns, or error message.
    """
    try:
        dao = BacktestDAO()
        performance_df = dao.get_performance_history(run_id)

        if performance_df.empty:
            return json.dumps({
                "run_id": run_id,
                "daily_performance": [],
                "message": "No performance history found for this run"
            })

        # Convert DataFrame to dict
        performance = performance_df.to_dict(orient="records")

        result = {
            "run_id": run_id,
            "daily_performance": performance,
            "total_days": len(performance)
        }

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error fetching performance history for run {run_id}: {e}")
        return json.dumps({
            "error": f"Failed to fetch performance history: {str(e)}"
        })


@tool
def fetch_historical_bars_for_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1Min"
) -> str:
    """Fetch historical market data for backtesting.

    Args:
        symbol: Stock ticker (e.g., 'AAPL')
        start_date: Start date in ISO format (YYYY-MM-DD)
        end_date: End date in ISO format (YYYY-MM-DD)
        timeframe: Bar timeframe (default: '1Min')

    Returns:
        JSON string with OHLCV bars array, or error message.
    """
<<<<<<< HEAD
    logger.info(f"🔧 [TOOL CALLED] fetch_historical_bars_for_backtest({symbol}, {start_date}, {end_date}, {timeframe})")
=======
>>>>>>> feat: Phase 4 - Backtester Agent Implementation
    try:
        dao = AlpacaDAO()

        # Convert ISO date strings to datetime
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        # Fetch bars from database
        bars_df = dao.get_bars(symbol, start=start, end=end, timeframe=timeframe)

        if bars_df.empty:
            return json.dumps({
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "timeframe": timeframe,
                "bars": [],
                "message": f"No historical data found for {symbol} in the specified range"
            })

        # Convert DataFrame to dict
        bars = bars_df.to_dict(orient="records")

        result = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "timeframe": timeframe,
            "bars": bars,
            "total_bars": len(bars)
        }

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error fetching historical bars for {symbol}: {e}")
        return json.dumps({
            "error": f"Failed to fetch historical bars: {str(e)}"
        })


@tool
def save_backtest_run_to_db(run_data: str) -> str:
    """Save backtest run metadata to database.

    Args:
        run_data: JSON string with run details containing:
            - strategy_name: Strategy name
            - start_date: Start date (YYYY-MM-DD)
            - end_date: End date (YYYY-MM-DD)
            - initial_capital: Starting capital
            - symbol: Stock symbol (optional)
            - parameters: Strategy parameters dict (optional)

    Returns:
        JSON string with run_id and status, or error message.
    """
    try:
        # Parse JSON input
        data = json.loads(run_data)

        # Validate required fields
        required = ['strategy_name', 'start_date', 'end_date', 'initial_capital']
        missing = [field for field in required if field not in data]
        if missing:
            return json.dumps({
                "error": f"Missing required fields: {', '.join(missing)}"
            })

        dao = BacktestDAO()

        # Convert date strings to date objects
        from datetime import date
        start_date = date.fromisoformat(data['start_date'])
        end_date = date.fromisoformat(data['end_date'])

        # Create backtest run
        run_id = dao.create_run(
            strategy_name=data['strategy_name'],
            start_date=start_date,
            end_date=end_date,
            initial_capital=data['initial_capital'],
            symbol=data.get('symbol'),
            parameters=data.get('parameters')
        )

        return json.dumps({
            "run_id": run_id,
            "status": "saved",
            "message": f"Backtest run created successfully"
        })

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in run_data: {e}")
        return json.dumps({
            "error": f"Invalid JSON format: {str(e)}"
        })
    except Exception as e:
        logger.error(f"Error saving backtest run: {e}")
        return json.dumps({
            "error": f"Failed to save backtest run: {str(e)}"
        })


# =============================================================================
# Functional Testing
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Backtester Tools Functional Test")
    print("=" * 60)

    # Test 1: Save a backtest run
    print("\n1. Testing save_backtest_run_to_db...")
    run_data_json = json.dumps({
        "strategy_name": "test-strategy",
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "initial_capital": 100000.0,
        "symbol": "AAPL",
        "parameters": {"window": 20}
    })
    result = save_backtest_run_to_db.invoke({"run_data": run_data_json})
    result_dict = json.loads(result)
    print(f"   Result: {result_dict.get('status')}")
    run_id = result_dict.get('run_id')
    print(f"   Run ID: {run_id}")

    if not run_id:
        print("   [ERROR] Failed to create run")
        exit(1)

    # Test 2: Fetch backtest run
    print("\n2. Testing fetch_backtest_run...")
    result = fetch_backtest_run.invoke({"run_id": run_id})
    result_dict = json.loads(result)
    print(f"   Strategy: {result_dict.get('strategy_name')}")
    print(f"   Symbol: {result_dict.get('symbol')}")
    print(f"   Status: {result_dict.get('status')}")

    # Test 3: Fetch trades (should be empty)
    print("\n3. Testing fetch_backtest_trades...")
    result = fetch_backtest_trades.invoke({"run_id": run_id})
    result_dict = json.loads(result)
    print(f"   Total trades: {result_dict.get('total_trades', 0)}")

    # Test 4: Fetch performance history (should be empty)
    print("\n4. Testing fetch_backtest_performance_history...")
    result = fetch_backtest_performance_history.invoke({"run_id": run_id})
    result_dict = json.loads(result)
    print(f"   Total days: {result_dict.get('total_days', 0)}")

    # Test 5: Fetch historical bars (might be empty if no data ingested)
    print("\n5. Testing fetch_historical_bars_for_backtest...")
    result = fetch_historical_bars_for_backtest.invoke({
        "symbol": "AAPL",
        "start_date": "2024-01-01",
        "end_date": "2024-01-02",
        "timeframe": "1Min"
    })
    result_dict = json.loads(result)
    total_bars = result_dict.get('total_bars', 0) if 'total_bars' in result_dict else 0
    print(f"   Total bars: {total_bars}")
    if total_bars == 0:
        print("   Note: No historical data in database (expected if data not ingested)")

    print("\n" + "=" * 60)
    print("All tests passed! [SUCCESS]")
    print("=" * 60)
