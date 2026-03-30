"""Strategy backtesting skill.

Execute trading strategy backtests with performance analysis and optional
database persistence. Refactored to use core backtesting library.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# When run as a CLI subprocess (by the backtester agent), stdout must contain
# only the JSON result. Redirect stdout→stderr NOW, before any imports trigger
# the logger singleton which hardcodes a StreamHandler(sys.stdout).
_cli_mode = __name__ == "__main__"
if _cli_mode:
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr

from typing import Dict, Optional
from datetime import date, datetime, timedelta
import uuid

from src.common.dao.alpaca_dao import AlpacaDAO
from src.common.dao.backtest_dao import BacktestDAO
from src.agentic.agents.backtester.core.controller import run_backtest
from src.common.utils import get_logger

logger = get_logger(__name__)


def backtest_strategy_core(
    ticker: str,
    start_date: str,
    end_date: str,
    strategy: str = "mean-reversion",
    snapshot: Optional[Dict] = None,
    initial_capital: float = 100000.0,
    save_to_db: bool = False,
    strategy_params: Optional[Dict] = None
) -> Dict:
    """Execute strategy backtest with optional snapshot starting state.

    Args:
        ticker: Stock ticker symbol to backtest
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        strategy: Strategy name (default: "buy-and-hold")
        snapshot: Optional portfolio snapshot to start from
        initial_capital: Starting capital if no snapshot (default: $100,000)
        save_to_db: Whether to persist results to database
        strategy_params: Optional dict of strategy-specific parameters.
            For mean-reversion: z_score_entry, z_score_exit, lookback.
            Defaults to hard-coded values if not provided (backward-compatible).

    Returns:
        Dict with:
            - run_id: Database ID if saved, None otherwise
            - status: "completed" or "failed"
            - strategy: Strategy name
            - symbol: Ticker symbol
            - start_date: Start date
            - end_date: End date
            - trading_days: Number of trading days
            - initial_capital: Starting capital
            - final_capital: Ending capital
            - trades: List of trade records
            - daily_performance: Daily equity snapshots
            - metrics: Performance metrics (Sharpe, drawdown, etc.)
            - summary: Human-readable summary
            - recommendation: Deployment recommendation
            - error: Error message if failed
    """
    logger.info(f"[SKILL] backtest_strategy_core: {strategy} on {ticker}")
    logger.info(f"[SKILL] Date range: {start_date} to {end_date}")

    try:
        # Parse dates
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

        # Validate dates
        if end_dt <= start_dt:
            return {
                "error": f"end_date ({end_date}) must be after start_date ({start_date})"
            }

        # Validate strategy
        available_strategies = ["buy-and-hold", "mean-reversion", "momentum", "value"]
        if strategy not in available_strategies:
            return {
                "error": f"Unknown strategy: {strategy}",
                "available_strategies": available_strategies
            }

        # Handle snapshot (future enhancement)
        if snapshot:
            logger.info(f"[SKILL] Starting from snapshot with positions")
            # TODO: Initialize portfolio from snapshot
            # For now, use initial_capital
            pass

        # Fetch historical bars
        alpaca_dao = AlpacaDAO()

        # Convert dates to datetime for AlpacaDAO
        start_datetime = datetime.combine(start_dt, datetime.min.time())
        end_datetime = datetime.combine(end_dt, datetime.max.time())

        # Get bars for the date range
        bars_df = alpaca_dao.get_bars(
            symbol=ticker,
            start=start_datetime,
            end=end_datetime,
            timeframe="1Min"
        )

        alpaca_dao.close()

        if bars_df.empty:
            return {
                "error": f"No historical data available for {ticker} from {start_date} to {end_date}",
                "suggestion": "Ingest market data for this symbol and date range first"
            }

        logger.info(f"[SKILL] Fetched {len(bars_df)} bars for {ticker}")

        # Load strategy signals function based on strategy name
        from src.agentic.agents.backtester.core.strategies import (
            make_mean_reversion_signals,
            make_buy_and_hold_signals,
        )

        _sp = strategy_params or {}
        strategy_map = {
            "mean-reversion": lambda: make_mean_reversion_signals(
                z_score_entry=_sp.get("z_score_entry", 2.0),
                z_score_exit=_sp.get("z_score_exit", 0.5),
                lookback=int(_sp.get("lookback", 20)),
            ),
            "buy-and-hold": make_buy_and_hold_signals,
        }

        factory = strategy_map.get(strategy, make_buy_and_hold_signals)
        strategy_signals = factory()

        # Run backtest using core library
        result = run_backtest(
            strategy_name=strategy,
            symbol=ticker,
            start_date=start_dt,
            end_date=end_dt,
            initial_capital=initial_capital,
            bars_df=bars_df,
            strategy_signals=strategy_signals,
            save_to_db=False  # We'll handle DB save separately
        )

        # Save to database if requested
        if save_to_db and result.get("status") == "completed":
            logger.info(f"[SKILL] Saving backtest results to database")

            backtest_dao = BacktestDAO()

            # Generate run_id
            run_id = str(uuid.uuid4())

            # Create backtest run
            backtest_dao.create_run(
                strategy_name=strategy,
                start_date=start_dt,
                end_date=end_dt,
                initial_capital=initial_capital,
                symbol=ticker,
                parameters={"strategy": strategy},
                run_id=run_id
            )

            # Save trades (if any)
            for trade in result.get("trades", []):
                if trade.get("status") == "open":
                    # Save open trade
                    backtest_dao.save_trade(
                        run_id=run_id,
                        symbol=trade["symbol"],
                        entry_date=trade["entry_date"],
                        entry_time=trade["entry_time"],
                        entry_price=trade["entry_price"],
                        quantity=trade["quantity"],
                        side=trade["side"],
                        entry_signal=trade.get("entry_signal", {})
                    )
                elif trade.get("status") == "closed":
                    # Save closed trade
                    trade_id = backtest_dao.save_trade(
                        run_id=run_id,
                        symbol=trade["symbol"],
                        entry_date=trade["entry_date"],
                        entry_time=trade["entry_time"],
                        entry_price=trade["entry_price"],
                        quantity=trade["quantity"],
                        side=trade["side"],
                        entry_signal=trade.get("entry_signal", {})
                    )

                    if trade.get("exit_date"):
                        backtest_dao.close_trade(
                            trade_id=trade_id,
                            exit_date=trade["exit_date"],
                            exit_time=trade["exit_time"],
                            exit_price=trade["exit_price"],
                            exit_reason=trade.get("exit_reason", "strategy_signal")
                        )

            # Save daily performance
            for day_perf in result.get("daily_performance", []):
                backtest_dao.save_daily_performance(
                    run_id=run_id,
                    date=day_perf["date"],
                    equity=day_perf["equity"],
                    cash=initial_capital,  # Simplified - should track actual cash
                    positions_value=day_perf["equity"] - initial_capital
                )

            # Update run with metrics
            metrics = result.get("metrics", {})
            backtest_dao.update_run_performance(
                run_id=run_id,
                metrics={
                    "final_capital": result["final_capital"],
                    "total_return_pct": metrics.get("total_return_pct"),
                    "sharpe_ratio": metrics.get("sharpe_ratio"),
                    "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                    "win_rate": metrics.get("win_rate"),
                    "profit_factor": metrics.get("profit_factor"),
                    "total_trades": metrics.get("total_trades"),
                    "winning_trades": metrics.get("winning_trades"),
                    "losing_trades": metrics.get("losing_trades"),
                    "avg_win": metrics.get("avg_win"),
                    "avg_loss": metrics.get("avg_loss")
                }
            )

            # Mark run as completed
            backtest_dao.mark_run_completed(run_id)

            backtest_dao.close()

            # Update result with run_id
            result["run_id"] = run_id

            logger.info(f"[SKILL] Backtest saved with run_id: {run_id}")

        logger.info(f"[SKILL] Backtest complete: {result.get('metrics', {}).get('total_return_pct', 0):.2f}% return")

        return result

    except Exception as e:
        logger.error(f"Error in backtest_strategy_core: {e}", exc_info=True)
        return {
            "status": "failed",
            "error": f"Backtest failed: {str(e)}"
        }


# =============================================================================
# CLI Entry Point (used by deepagents bash skill execution)
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description="backtest_strategy skill — run a trading strategy backtest"
    )
    parser.add_argument("--ticker", required=True, help="Stock ticker symbol (e.g. AAPL)")
    parser.add_argument("--start_date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--strategy",
        default="mean-reversion",
        choices=["buy-and-hold", "mean-reversion", "momentum", "value"],
        help="Strategy to backtest (default: mean-reversion)"
    )
    parser.add_argument(
        "--initial_capital",
        type=float,
        default=100000.0,
        help="Starting capital in USD (default: 100000)"
    )
    parser.add_argument(
        "--save_to_db",
        action="store_true",
        default=False,
        help="Persist results to database"
    )

    args = parser.parse_args()

    result = backtest_strategy_core(
        ticker=args.ticker,
        start_date=args.start_date,
        end_date=args.end_date,
        strategy=args.strategy,
        initial_capital=args.initial_capital,
        save_to_db=args.save_to_db
    )

    # Restore real stdout and write only the JSON result — nothing else.
    sys.stdout = _real_stdout
    print(_json.dumps(result, default=str))
