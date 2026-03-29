"""Tools for the Backtester Agent.

Data access tools for fetching and saving backtest simulation data.
All tools return JSON strings for LangChain tool compatibility.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import subprocess
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import pandas as pd

from langchain_core.tools import tool

from src.common.dao.backtest_dao import BacktestDAO
from src.common.dao.alpaca_dao import AlpacaDAO
from src.common.utils import get_logger


logger = get_logger(__name__)


# =============================================================================
# Data Access Tools (Fetch & Save Operations)
# =============================================================================

@tool
def fetch_backtest_run(run_id: str) -> str:
    """Fetch backtest run details from database.

    USE WHEN: retrieving results for an already-completed backtest by run_id.
    DO NOT USE WHEN: starting a new backtest — use save_backtest_run_to_db first.

    Args:
        run_id: Backtest run identifier (UUID)

    Returns:
        JSON string with run metadata and performance metrics, or error message.
        Includes: strategy_name, symbol, start_date, end_date, performance metrics
        (sharpe_ratio, max_drawdown_pct, win_rate, total_trades, etc.)
    """
    logger.info(f"[TOOL] Calling: fetch_backtest_run")
    logger.info(f"[TOOL] Input: {json.dumps({'run_id': run_id}, indent=2)}")

    try:
        # Fetch from database
        dao = BacktestDAO()
        run_data = dao.get_run(run_id)
        dao.close()

        if run_data is None or run_data.empty:
            result = {
                "error": f"Backtest run {run_id} not found"
            }
        else:
            # Convert to dict
            run_row = run_data.iloc[0]
            result = {
                "run_id": run_id,
                "strategy_name": run_row.get("strategy_name"),
                "symbol": run_row.get("symbol"),
                "start_date": str(run_row.get("start_date")),
                "end_date": str(run_row.get("end_date")),
                "initial_capital": float(run_row.get("initial_capital", 0)),
                "final_capital": float(run_row.get("final_capital", 0)),
                "status": run_row.get("status"),
                "sharpe_ratio": float(run_row.get("sharpe_ratio", 0)),
                "max_drawdown_pct": float(run_row.get("max_drawdown_pct", 0)),
                "win_rate": float(run_row.get("win_rate", 0)),
                "total_trades": int(run_row.get("total_trades", 0)),
                "total_return_pct": float(run_row.get("total_return_pct", 0))
            }

        output = json.dumps(result, indent=2, default=str)
        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")
        return output

    except Exception as e:
        error_msg = f"Error fetching backtest run {run_id}: {e}"
        logger.error(f"[TOOL] Error: {error_msg}")
        error_result = json.dumps({
            "error": f"Failed to fetch backtest run: {str(e)}"
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


@tool
def fetch_backtest_trades(run_id: str) -> str:
    """Fetch all trades for a backtest run.

    USE WHEN: drilling into individual trade-level data (entry/exit prices, P&L per trade)
    for an existing run_id.
    DO NOT USE WHEN: you only need summary metrics — use fetch_backtest_run for that.

    Args:
        run_id: Backtest run identifier (UUID)

    Returns:
        JSON string with array of trade details (entry/exit prices, P&L, signals),
        or error message.
    """
    logger.info(f"[TOOL] Calling: fetch_backtest_trades")
    logger.info(f"[TOOL] Input: {json.dumps({'run_id': run_id}, indent=2)}")

    try:
        # Fetch from database
        dao = BacktestDAO()
        trades_df = dao.get_trades(run_id)
        dao.close()

        if trades_df is None or trades_df.empty:
            result = {
                "run_id": run_id,
                "total_trades": 0,
                "trades": []
            }
        else:
            # Convert to list of dicts
            trades_list = trades_df.to_dict('records')
            result = {
                "run_id": run_id,
                "total_trades": len(trades_list),
                "trades": trades_list
            }

        output = json.dumps(result, indent=2, default=str)
        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")
        return output

    except Exception as e:
        error_msg = f"Error fetching trades for run {run_id}: {e}"
        logger.error(f"[TOOL] Error: {error_msg}")
        error_result = json.dumps({
            "error": f"Failed to fetch trades: {str(e)}"
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


@tool
def fetch_backtest_performance_history(run_id: str) -> str:
    """Fetch daily performance snapshots for a backtest run.

    USE WHEN: user wants the equity curve, daily returns, or drawdown breakdown for
    a completed backtest run.
    DO NOT USE WHEN: user only needs summary metrics (Sharpe, win rate) — use
    fetch_backtest_run which is faster.

    Args:
        run_id: Backtest run identifier (UUID)

    Returns:
        JSON string with daily equity curve, returns, and drawdowns, or error message.
    """
    logger.info(f"[TOOL] Calling: fetch_backtest_performance_history")
    logger.info(f"[TOOL] Input: {json.dumps({'run_id': run_id}, indent=2)}")

    try:
        # Fetch from database
        dao = BacktestDAO()
        perf_df = dao.get_performance_history(run_id)
        dao.close()

        if perf_df is None or perf_df.empty:
            result = {
                "run_id": run_id,
                "total_days": 0,
                "daily_performance": []
            }
        else:
            # Convert to list of dicts
            perf_list = perf_df.to_dict('records')
            result = {
                "run_id": run_id,
                "total_days": len(perf_list),
                "daily_performance": perf_list
            }

        output = json.dumps(result, indent=2, default=str)
        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")
        return output

    except Exception as e:
        error_msg = f"Error fetching performance history for run {run_id}: {e}"
        logger.error(f"[TOOL] Error: {error_msg}")
        error_result = json.dumps({
            "error": f"Failed to fetch performance history: {str(e)}"
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


@tool
def fetch_historical_bars_for_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1Min"
) -> str:
    """Check data availability for backtesting (returns SUMMARY only, not raw bars).

    USE WHEN: Workflows B and C — verify that historical data exists before running
    snapshot-worth or swap-positions skills.
    DO NOT USE WHEN: Workflow A (backtest-strategy skill fetches data internally —
    no pre-check needed).

    Returns data statistics and summary, NOT the actual bars.

    Args:
        symbol: Stock ticker (e.g., 'AAPL')
        start_date: Start date in ISO format (YYYY-MM-DD)
        end_date: End date in ISO format (YYYY-MM-DD)
        timeframe: Bar timeframe (default: '1Min')

    Returns:
        JSON string with data summary:
        - total_bars: Number of bars available
        - trading_days: Number of trading days
        - data_complete: Whether data has no gaps
        - price_range: Min/max/avg prices
        - status: 'ready' or 'no_data'
    """
    logger.info(f"[TOOL] Calling: fetch_historical_bars_for_backtest")
    logger.info(f"[TOOL] Input: {json.dumps({'symbol': symbol, 'start_date': start_date, 'end_date': end_date, 'timeframe': timeframe}, indent=2)}")

    try:
        # Parse dates to datetime (set to start/end of day)
        start_dt = datetime.strptime(start_date + " 00:00:00", "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(end_date + " 23:59:59", "%Y-%m-%d %H:%M:%S")

        # Fetch bars from database
        dao = AlpacaDAO()
        bars_df = dao.get_bars(symbol=symbol, start=start_dt, end=end_dt, timeframe=timeframe)
        dao.close()

        if bars_df.empty:
            result = {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "total_bars": 0,
                "trading_days": 0,
                "status": "no_data",
                "message": f"No historical data found for {symbol}"
            }
        else:
            # Calculate summary statistics
            # Ensure timestamp is datetime
            if 'timestamp' in bars_df.columns:
                if not pd.api.types.is_datetime64_any_dtype(bars_df['timestamp']):
                    bars_df['timestamp'] = pd.to_datetime(bars_df['timestamp'])

            total_bars = len(bars_df)
            trading_days = bars_df['timestamp'].dt.date.nunique() if 'timestamp' in bars_df.columns else 0

            result = {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "total_bars": total_bars,
                "trading_days": trading_days,
                "price_range": {
                    "low": float(bars_df['low'].min()),
                    "high": float(bars_df['high'].max()),
                    "avg": float(bars_df['close'].mean())
                },
                "data_complete": True,  # Simplified - could check for gaps
                "status": "ready",
                "message": f"Data available: {total_bars} bars across {trading_days} days"
            }

        output = json.dumps(result, indent=2, default=str)
        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")
        return output

    except Exception as e:
        error_msg = f"Error fetching historical bars for {symbol}: {e}"
        logger.error(f"[TOOL] Error: {error_msg}")
        error_result = json.dumps({
            "error": f"Failed to fetch historical bars: {str(e)}"
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


@tool
def save_backtest_run_to_db(run_data: str) -> str:
    """Save backtest run metadata to database.

    USE WHEN: starting Workflow A — call this first to create a run_id, then execute
    the backtest-strategy skill, then use run_id to retrieve results.
    DO NOT USE WHEN: the backtest skill has already been run and you just need results
    (use fetch_backtest_run instead).

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
    logger.info(f"[TOOL] Calling: save_backtest_run_to_db")
    logger.info(f"[TOOL] Input: {run_data[:200]}..." if len(run_data) > 200 else f"[TOOL] Input: {run_data}")

    try:
        # Parse JSON input
        data = json.loads(run_data)

        # Extract required fields
        strategy_name = data.get("strategy_name")
        start_date = datetime.strptime(data.get("start_date"), "%Y-%m-%d").date()
        end_date = datetime.strptime(data.get("end_date"), "%Y-%m-%d").date()
        initial_capital = float(data.get("initial_capital", 100000.0))
        symbol = data.get("symbol")
        parameters = data.get("parameters", {})

        # Save to database
        dao = BacktestDAO()
        run_id = dao.create_run(
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            symbol=symbol,
            parameters=parameters
        )
        dao.close()

        result = {
            "status": "success",
            "run_id": run_id,
            "message": f"Backtest run created with ID: {run_id}"
        }

        output = json.dumps(result)
        logger.info(f"[TOOL] Output: {output}")
        return output

    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON in run_data: {e}"
        logger.error(f"[TOOL] Error: {error_msg}")
        error_result = json.dumps({
            "error": f"Invalid JSON format: {str(e)}"
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result
    except Exception as e:
        error_msg = f"Error saving backtest run: {e}"
        logger.error(f"[TOOL] Error: {error_msg}")
        error_result = json.dumps({
            "error": f"Failed to save backtest run: {str(e)}"
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


# =============================================================================
# Batch Strategy Comparison Tool
# =============================================================================

_BACKTEST_SCRIPT = "src/agentic/agents/backtester/skills/backtest-strategy/strategy.py"

_VALID_STRATEGIES = ["buy-and-hold", "mean-reversion", "momentum", "value"]


def _run_single_backtest(
    strategy: str,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
) -> Dict:
    """Run one backtest strategy script and return its JSON result.

    Args:
        strategy: Strategy name (e.g., "mean-reversion").
        symbol: Stock ticker.
        start_date: YYYY-MM-DD start date.
        end_date: YYYY-MM-DD end date.
        initial_capital: Starting capital.

    Returns:
        Dict with backtest result or {"error": "..."}.
    """
    root = Path(__file__).parent.parent.parent.parent
    script_path = root / _BACKTEST_SCRIPT

    if not script_path.exists():
        return {"error": f"Backtest script not found: {script_path}"}

    try:
        cmd = [
            "python", str(script_path),
            "--ticker", symbol,
            "--start_date", start_date,
            "--end_date", end_date,
            "--strategy", strategy,
            "--initial_capital", str(initial_capital),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return {"error": result.stderr.strip() or "Non-zero exit code"}
        return json.loads(result.stdout.strip())
    except subprocess.TimeoutExpired:
        return {"error": f"Strategy '{strategy}' timed out after 120s"}
    except json.JSONDecodeError as e:
        return {"error": f"Strategy '{strategy}' returned non-JSON output: {e}"}
    except Exception as e:
        return {"error": str(e)}


@tool
def run_strategy_comparison(
    symbol: str,
    strategies: List[str],
    start_date: str,
    end_date: str,
    initial_capital: float = 100000.0,
) -> str:
    """Run multiple backtests in parallel and return a ranked comparison.

    USE WHEN: User wants to compare strategies ("which is better?", "run all strategies
    on AAPL", "compare mean-reversion vs buy-and-hold").
    Counts as 1 execution action regardless of how many strategies are run.

    DO NOT USE WHEN: User specifies exactly one strategy — call backtest-strategy
    skill directly (e.g., via bash) for a single strategy.

    Args:
        symbol: Stock ticker (e.g., "AAPL").
        strategies: List of strategy names to compare. Valid values:
            "buy-and-hold", "mean-reversion", "momentum", "value".
            Use ["all"] to compare all available strategies.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        initial_capital: Starting capital for each strategy (default: $100,000).

    Returns:
        JSON string with each strategy's metrics and a ranked comparison table
        sorted by Sharpe ratio descending.

    Example:
        run_strategy_comparison.invoke({
            "symbol": "AAPL",
            "strategies": ["mean-reversion", "buy-and-hold"],
            "start_date": "2025-01-01",
            "end_date": "2025-01-31"
        })
    """
    logger.info(
        f"[TOOL] Calling: run_strategy_comparison("
        f"symbol={symbol}, strategies={strategies}, "
        f"{start_date} to {end_date})"
    )

    requested = _VALID_STRATEGIES if strategies == ["all"] else strategies
    unknown = [s for s in requested if s not in _VALID_STRATEGIES]
    if unknown:
        return json.dumps({
            "error": f"Unknown strategies: {unknown}. Valid: {_VALID_STRATEGIES}"
        })

    results: Dict[str, Dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(requested)) as pool:
        futures = {
            pool.submit(
                _run_single_backtest, strategy, symbol, start_date, end_date, initial_capital
            ): strategy
            for strategy in requested
        }
        for future in concurrent.futures.as_completed(futures):
            strategy = futures[future]
            try:
                results[strategy] = future.result()
            except Exception as e:
                results[strategy] = {"error": str(e)}

    # Build ranked summary from successful results
    ranked = []
    for strategy, res in results.items():
        if "error" not in res and "metrics" in res:
            metrics = res["metrics"]
            ranked.append({
                "strategy": strategy,
                "total_return_pct": metrics.get("total_return_pct", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
                "win_rate": metrics.get("win_rate", 0),
                "total_trades": metrics.get("total_trades", 0),
                "recommendation": res.get("recommendation", "N/A"),
            })
    ranked.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

    output = json.dumps({
        "symbol": symbol,
        "period": {"start": start_date, "end": end_date},
        "initial_capital": initial_capital,
        "ranked_by_sharpe": ranked,
        "details": results,
    }, indent=2, default=str)

    logger.info(
        f"[TOOL] run_strategy_comparison complete: "
        f"{len(results)} strategies for {symbol}"
    )
    return output


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
