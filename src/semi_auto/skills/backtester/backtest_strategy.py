"""BacktestStrategySkill — run a strategy backtest (Workflow A)."""

import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)


class BacktestStrategySkill:
    """Run trading strategy backtests against historical OHLCV data.

    Supports mean-reversion and buy-and-hold strategies with optional
    persistence to BacktestDAO. Auto-fetches missing market data via
    the Alpaca API when the local database has no bars for the requested
    symbol / date range.
    """

    AVAILABLE_STRATEGIES = [
        # Existing
        "buy-and-hold",
        "mean-reversion",
        "momentum",
        "value",
        # Day trading
        "vwap-reversion",
        "opening-range-breakout",
        "rsi-divergence",
        "momentum-burst",
        # Swing
        "golden-cross",
        "breakout-52w",
        "mean-reversion-daily",
        "earnings-drift",
    ]

    def run(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        strategy: str = "mean-reversion",
        snapshot: Optional[Dict] = None,
        initial_capital: float = 100_000.0,
        save_to_db: bool = False,
        strategy_params: Optional[Dict] = None,
    ) -> Dict:
        """Execute a strategy backtest over a historical date range.

        Args:
            ticker: Stock ticker symbol to backtest (e.g. "AAPL").
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
            strategy: Strategy name — one of ``AVAILABLE_STRATEGIES``.
                Defaults to ``"mean-reversion"``.
            snapshot: Optional portfolio snapshot dict to start from.
                Currently unused (reserved for future enhancement).
            initial_capital: Starting capital in USD. Defaults to 100 000.
            save_to_db: Persist results to BacktestDAO when True.
            strategy_params: Optional strategy-specific parameter overrides.
                For mean-reversion: ``z_score_entry``, ``z_score_exit``,
                ``lookback``.

        Returns:
            Dict containing:
                - status: "completed" or "failed"
                - strategy / symbol / start_date / end_date
                - trades: list of trade record dicts
                - metrics: performance metrics dict
                - summary: human-readable summary string
                - recommendation: deployment recommendation string
                - run_id: DB run ID when save_to_db is True
                - error: error message on failure
        """
        logger.info(f"[BacktestStrategySkill] {strategy} on {ticker} [{start_date} → {end_date}]")

        try:
            from src.common.dao.alpaca_dao import AlpacaDAO
            from src.common.dao.backtest_dao import BacktestDAO
            from src.agentic.agents.backtester.core.controller import run_backtest
            from src.agentic.agents.backtester.core.strategies import (
                make_buy_and_hold_signals,
                make_mean_reversion_signals,
            )
            from src.semi_auto.skills.quant.skills import (
                make_vwap_reversion_signals,
                make_opening_range_breakout_signals,
                make_rsi_divergence_signals,
                make_momentum_burst_signals,
                make_golden_cross_signals,
                make_breakout_52w_signals,
                make_mean_reversion_daily_signals,
                make_earnings_drift_signals,
            )

            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

            if end_dt <= start_dt:
                return {"error": f"end_date ({end_date}) must be after start_date ({start_date})"}

            if strategy not in self.AVAILABLE_STRATEGIES:
                return {
                    "error": f"Unknown strategy: {strategy}",
                    "available_strategies": self.AVAILABLE_STRATEGIES,
                }

            # Convert to datetime for AlpacaDAO
            start_dt_ts = datetime.combine(start_dt, datetime.min.time())
            end_dt_ts = datetime.combine(end_dt, datetime.max.time())

            # Fetch local bars
            alpaca_dao = AlpacaDAO()
            bars_df = alpaca_dao.get_bars(
                symbol=ticker, start=start_dt_ts, end=end_dt_ts, timeframe="1Min"
            )
            alpaca_dao.close()

            # Auto-fetch from API if local DB is empty
            if bars_df.empty:
                logger.info(f"[BacktestStrategySkill] No local data for {ticker} — auto-fetching")
                try:
                    from src.agentic.agents.portfolio.skills.datamanagement.data import (
                        fetch_historical_data_core,
                    )
                    fetch_result = fetch_historical_data_core(
                        symbol=ticker,
                        start_date=start_date,
                        end_date=end_date,
                        timeframe="1Min",
                    )
                    if fetch_result.get("status") != "success":
                        return {
                            "status": "failed",
                            "error": (
                                f"No data for {ticker} ({start_date} → {end_date}) and "
                                f"auto-fetch failed: "
                                f"{fetch_result.get('error', fetch_result.get('message', 'unknown'))}"
                            ),
                            "suggestion": "Verify symbol and date range are valid Alpaca market data.",
                        }
                    logger.info(
                        f"[BacktestStrategySkill] Auto-fetched {fetch_result.get('bars_fetched', '?')} "
                        f"bars for {ticker}"
                    )
                except Exception as fetch_exc:
                    return {
                        "status": "failed",
                        "error": f"No data for {ticker} and auto-fetch raised: {fetch_exc}",
                    }

                # Retry query after fetch
                alpaca_dao = AlpacaDAO()
                bars_df = alpaca_dao.get_bars(
                    symbol=ticker, start=start_dt_ts, end=end_dt_ts, timeframe="1Min"
                )
                alpaca_dao.close()
                if bars_df.empty:
                    return {
                        "status": "failed",
                        "error": (
                            f"Auto-fetch succeeded but bars still empty for {ticker} — "
                            "data may be outside market hours or symbol is invalid."
                        ),
                    }

            logger.info(f"[BacktestStrategySkill] {len(bars_df)} bars fetched for {ticker}")

            # Build strategy signals
            _sp = strategy_params or {}
            strategy_map = {
                "mean-reversion": lambda: make_mean_reversion_signals(
                    z_score_entry=float(_sp.get("z_score_entry", 2.0)),
                    z_score_exit=float(_sp.get("z_score_exit", 0.5)),
                    lookback=int(_sp.get("lookback", 20)),
                ),
                "buy-and-hold": make_buy_and_hold_signals,
                # Day trading strategies
                "vwap-reversion": lambda: make_vwap_reversion_signals(
                    dev_pct=float(_sp.get("dev_pct", 0.005)),
                    vol_mult=float(_sp.get("vol_mult", 2.0)),
                ),
                "opening-range-breakout": lambda: make_opening_range_breakout_signals(
                    range_bars=int(_sp.get("range_bars", 15)),
                ),
                "rsi-divergence": lambda: make_rsi_divergence_signals(
                    lookback=int(_sp.get("lookback", 20)),
                    oversold=float(_sp.get("oversold", 35.0)),
                ),
                "momentum-burst": lambda: make_momentum_burst_signals(
                    vol_mult=float(_sp.get("vol_mult", 3.0)),
                    min_move=float(_sp.get("min_move", 0.005)),
                ),
                # Swing strategies
                "golden-cross": lambda: make_golden_cross_signals(
                    fast=int(_sp.get("fast", 50)),
                    slow=int(_sp.get("slow", 200)),
                ),
                "breakout-52w": lambda: make_breakout_52w_signals(
                    lookback=int(_sp.get("lookback", 252)),
                    vol_mult=float(_sp.get("vol_mult", 1.5)),
                ),
                "mean-reversion-daily": lambda: make_mean_reversion_daily_signals(
                    lookback=int(_sp.get("lookback", 20)),
                    threshold=float(_sp.get("threshold", 2.5)),
                ),
                "earnings-drift": lambda: make_earnings_drift_signals(
                    min_move=float(_sp.get("min_move", 0.04)),
                    hold_days=int(_sp.get("hold_days", 5)),
                ),
            }
            factory = strategy_map.get(strategy, make_buy_and_hold_signals)
            strategy_signals = factory()

            result = run_backtest(
                strategy_name=strategy,
                symbol=ticker,
                start_date=start_dt,
                end_date=end_dt,
                initial_capital=initial_capital,
                bars_df=bars_df,
                strategy_signals=strategy_signals,
                save_to_db=False,
            )

            # Persist to DB when requested
            if save_to_db and result.get("status") == "completed":
                result = self._persist_result(
                    result, ticker, strategy, start_dt, end_dt, initial_capital, strategy_params
                )

            logger.info(
                f"[BacktestStrategySkill] Complete: "
                f"{result.get('metrics', {}).get('total_return_pct', 0):.2f}% return"
            )
            return result

        except Exception as exc:
            logger.error(f"[BacktestStrategySkill] Error: {exc}", exc_info=True)
            return {"status": "failed", "error": f"Backtest failed: {exc}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _persist_result(
        self,
        result: Dict,
        ticker: str,
        strategy: str,
        start_dt: date,
        end_dt: date,
        initial_capital: float,
        strategy_params: Optional[Dict],
    ) -> Dict:
        """Save backtest result to BacktestDAO and embed run_id in result.

        Args:
            result: Completed backtest result dict from run_backtest.
            ticker: Ticker symbol.
            strategy: Strategy name.
            start_dt: Start date.
            end_dt: End date.
            initial_capital: Starting capital.
            strategy_params: Optional strategy params for metadata.

        Returns:
            Updated result dict with run_id key added.
        """
        from src.common.dao.backtest_dao import BacktestDAO

        backtest_dao = BacktestDAO()
        run_id = str(uuid.uuid4())

        backtest_dao.create_run(
            strategy_name=strategy,
            start_date=start_dt,
            end_date=end_dt,
            initial_capital=initial_capital,
            symbol=ticker,
            parameters={"strategy": strategy, **(strategy_params or {})},
            run_id=run_id,
        )

        for trade in result.get("trades", []):
            if trade.get("status") == "open":
                backtest_dao.save_trade(
                    run_id=run_id,
                    symbol=trade["symbol"],
                    entry_date=trade["entry_date"],
                    entry_time=trade["entry_time"],
                    entry_price=trade["entry_price"],
                    quantity=trade["quantity"],
                    side=trade["side"],
                    action=trade.get("action", "buy"),
                    entry_signal=trade.get("entry_signal", {}),
                )
            elif trade.get("status") == "closed":
                trade_id = backtest_dao.save_trade(
                    run_id=run_id,
                    symbol=trade["symbol"],
                    entry_date=trade["entry_date"],
                    entry_time=trade["entry_time"],
                    entry_price=trade["entry_price"],
                    quantity=trade["quantity"],
                    side=trade["side"],
                    action=trade.get("action", "buy"),
                    entry_signal=trade.get("entry_signal", {}),
                )
                if trade.get("exit_date"):
                    backtest_dao.close_trade(
                        trade_id=trade_id,
                        exit_date=trade["exit_date"],
                        exit_time=trade["exit_time"],
                        exit_price=trade["exit_price"],
                        exit_reason=trade.get("exit_reason", "strategy_signal"),
                    )

        for day_perf in result.get("daily_performance", []):
            backtest_dao.save_daily_performance(
                run_id=run_id,
                date=day_perf["date"],
                equity=day_perf["equity"],
                cash=initial_capital,
                positions_value=day_perf["equity"] - initial_capital,
            )

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
                "avg_loss": metrics.get("avg_loss"),
            },
        )
        backtest_dao.mark_run_completed(run_id)
        backtest_dao.close()

        result["run_id"] = run_id
        logger.info(f"[BacktestStrategySkill] Saved to DB with run_id: {run_id}")
        return result


# Singleton
backtest_skill = BacktestStrategySkill()

# Legacy function alias
backtest_strategy_core = backtest_skill.run

__all__ = ["BacktestStrategySkill", "backtest_skill", "backtest_strategy_core"]
