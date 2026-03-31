"""Backtester skill classes for the semi_auto registry.

Three workflow classes, each encapsulating one backtester skill:

    BacktestStrategySkill   — run a strategy backtest (Workflow A)
    SnapshotSkill           — save EOD snapshot + calculate snapshot worth (Workflow B)
    SwapPositionsSkill      — simulate position swaps and forward-value the result (Workflow C)

All implementation code is inlined here so this module has no runtime
dependency on src/agentic/. All src/common/ imports are kept at the call
site to avoid import-order issues with the DAO singleton.
"""

import json
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)


# =============================================================================
# Workflow A — Strategy Backtesting
# =============================================================================

class BacktestStrategySkill:
    """Run trading strategy backtests against historical OHLCV data.

    Supports mean-reversion and buy-and-hold strategies with optional
    persistence to BacktestDAO. Auto-fetches missing market data via
    the Alpaca API when the local database has no bars for the requested
    symbol / date range.
    """

    AVAILABLE_STRATEGIES = ["buy-and-hold", "mean-reversion", "momentum", "value"]

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


# =============================================================================
# Workflow B — EOD Snapshot saving + forward valuation
# =============================================================================

class SnapshotSkill:
    """Save end-of-day portfolio snapshots and calculate their future worth.

    Two methods:
        save_eod   — persist a portfolio snapshot to PortfolioDAO.
        get_worth  — forward-simulate a snapshot to a future date.
    """

    def save_eod(
        self,
        timestamp: str,
        equity: float,
        cash: float,
        buying_power: float,
        positions: List[Dict],
        daily_pnl: Optional[float] = None,
        total_pnl: Optional[float] = None,
        daily_pnl_percent: Optional[float] = None,
        snapshot_source: str = "manual",
    ) -> Dict:
        """Save end-of-day portfolio snapshot with position details.

        Args:
            timestamp: Snapshot timestamp (ISO format or YYYY-MM-DD HH:MM:SS).
            equity: Total portfolio value.
            cash: Available cash balance.
            buying_power: Margin buying power.
            positions: List of position dicts — each must have a ``symbol`` key.
            daily_pnl: Today's profit/loss (optional).
            total_pnl: All-time P&L (optional).
            daily_pnl_percent: Daily % return (optional).
            snapshot_source: Source identifier. Defaults to ``"manual"``.

        Returns:
            Dict with status, message, snapshot_id, date, positions_count.
        """
        logger.info(f"[SnapshotSkill.save_eod] Saving snapshot for {timestamp}")

        try:
            from src.common.dao.portfolio_dao import PortfolioDAO

            if isinstance(timestamp, str):
                try:
                    ts = datetime.fromisoformat(timestamp)
                except ValueError:
                    ts = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            else:
                ts = timestamp

            if not isinstance(positions, list):
                return {"status": "error", "error": "positions must be a list of position dicts"}

            for pos in positions:
                if not isinstance(pos, dict):
                    return {"status": "error", "error": "Each position must be a dict"}
                if "symbol" not in pos:
                    return {"status": "error", "error": "Each position must have 'symbol' field"}

            long_positions = sum(
                1 for p in positions if p.get("side", "long") == "long" and p.get("quantity", 0) > 0
            )
            short_positions = sum(
                1 for p in positions if p.get("side", "long") == "short" and p.get("quantity", 0) != 0
            )

            portfolio_dao = PortfolioDAO()
            portfolio_dao.save_snapshot(
                timestamp=ts,
                equity=equity,
                cash=cash,
                buying_power=buying_power,
                daily_pnl=daily_pnl,
                total_pnl=total_pnl,
                daily_pnl_percent=daily_pnl_percent,
                long_positions=long_positions,
                short_positions=short_positions,
                snapshot_source=snapshot_source,
                positions=positions,
            )
            latest = portfolio_dao.get_latest_snapshot()
            snapshot_id = latest.get("snapshot_id") if latest else None
            portfolio_dao.close()

            logger.info(f"[SnapshotSkill.save_eod] Saved snapshot ID {snapshot_id}")
            return {
                "status": "success",
                "message": f"Portfolio snapshot saved for {ts.date()}",
                "snapshot_id": snapshot_id,
                "date": str(ts.date()),
                "positions_count": len(positions),
                "long_positions": long_positions,
                "short_positions": short_positions,
            }

        except Exception as exc:
            logger.error(f"[SnapshotSkill.save_eod] Error: {exc}", exc_info=True)
            return {"status": "error", "error": f"Failed to save snapshot: {exc}"}

    def get_worth(self, snapshot_date: str, end_date: str) -> Dict:
        """Calculate portfolio snapshot worth at a future date (no swaps).

        Retrieves the portfolio snapshot nearest to ``snapshot_date`` and
        forward-simulates a buy-and-hold hold to ``end_date``.

        Args:
            snapshot_date: Date of the portfolio snapshot (YYYY-MM-DD).
            end_date: Future date to value the portfolio at (YYYY-MM-DD).

        Returns:
            Dict with snapshot_date, end_date, initial_worth, final_worth,
            return_pct, return_dollars, positions_at_end, metrics.
        """
        logger.info(f"[SnapshotSkill.get_worth] {snapshot_date} → {end_date}")

        try:
            from src.common.dao.portfolio_dao import PortfolioDAO
            from src.common.dao.alpaca_dao import AlpacaDAO
            from src.agentic.agents.backtester.core.controller import run_snapshot_forward_simulation

            snap_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

            if end_dt <= snap_date:
                return {"error": f"end_date ({end_date}) must be after snapshot_date ({snapshot_date})"}

            portfolio_dao = PortfolioDAO()
            snapshot_history = portfolio_dao.get_snapshot_history(
                start_date=snap_date - timedelta(days=7), end_date=snap_date
            )
            if snapshot_history.empty:
                portfolio_dao.close()
                return {
                    "error": f"No portfolio snapshot found near {snapshot_date}",
                    "suggestion": "Create a portfolio snapshot first or try a different date",
                }

            snapshot_row = snapshot_history.iloc[0]
            actual_snapshot_date = snapshot_row["date_only"]
            positions_json = snapshot_row.get("positions_json")
            if not positions_json:
                portfolio_dao.close()
                return {
                    "error": f"Snapshot from {actual_snapshot_date} has no position details",
                    "suggestion": "Use newer snapshots with position data.",
                }

            positions_list = (
                json.loads(positions_json) if isinstance(positions_json, str) else positions_json
            )
            positions = {p["symbol"]: p for p in positions_list if p.get("symbol")}

            portfolio_snapshot = {
                "date": actual_snapshot_date,
                "timestamp": snapshot_row["timestamp"],
                "cash": float(snapshot_row["cash"]),
                "equity": float(snapshot_row["equity"]),
                "buying_power": float(snapshot_row.get("buying_power", 0)),
                "positions": positions,
                "long_positions": snapshot_row.get("long_positions", 0),
                "short_positions": snapshot_row.get("short_positions", 0),
            }
            portfolio_dao.close()

            symbols = list(positions.keys())
            if not symbols:
                return {
                    "snapshot_date": str(actual_snapshot_date),
                    "end_date": str(end_dt),
                    "initial_worth": float(snapshot_row["equity"]),
                    "final_worth": float(snapshot_row["cash"]),
                    "return_pct": 0.0,
                    "return_dollars": 0.0,
                    "positions": {},
                    "message": "No positions in snapshot — only cash",
                }

            start_dt_ts = datetime.combine(snap_date, datetime.min.time())
            end_dt_ts = datetime.combine(end_dt, datetime.max.time())

            alpaca_dao = AlpacaDAO()
            bars_list = []
            for sym in symbols:
                sym_bars = alpaca_dao.get_bars(
                    symbol=sym, start=start_dt_ts, end=end_dt_ts, timeframe="1Day"
                )
                if not sym_bars.empty:
                    sym_bars["symbol"] = sym
                    bars_list.append(sym_bars)
            alpaca_dao.close()

            if not bars_list:
                return {
                    "error": f"No historical data for {symbols} from {snapshot_date} to {end_date}",
                    "suggestion": "Ingest market data for these symbols first",
                }

            bars_df = pd.concat(bars_list, ignore_index=True)
            result = run_snapshot_forward_simulation(
                snapshot=portfolio_snapshot, end_date=end_dt, bars_df=bars_df
            )
            logger.info(f"[SnapshotSkill.get_worth] {result.get('return_pct', 0):.2f}% return")
            return result

        except Exception as exc:
            logger.error(f"[SnapshotSkill.get_worth] Error: {exc}", exc_info=True)
            return {"error": f"Failed to calculate snapshot worth: {exc}"}


# =============================================================================
# Workflow C — Position swap simulation
# =============================================================================

class SwapPositionsSkill:
    """Simulate instantaneous position swaps and forward-value the result.

    A "swap" replaces a quantity of one symbol with an equal quantity of
    another at the snapshot date, then holds to end_date — no buy/sell
    transaction costs are modelled.
    """

    def simulate(
        self,
        snapshot_date: str,
        end_date: str,
        tickers: Dict[str, Dict],
    ) -> Dict:
        """Apply position swaps to a snapshot and calculate portfolio worth.

        Args:
            snapshot_date: Date of the portfolio snapshot (YYYY-MM-DD).
            end_date: Future date to value the swapped portfolio (YYYY-MM-DD).
            tickers: Mapping of ``{symbol: {"swap_to": "NEW_SYM", "quantity": N}}``.
                Example: ``{"AAPL": {"swap_to": "TSLA", "quantity": 50}}``.

        Returns:
            Dict with swaps_applied, initial_worth_before_swap, initial_worth,
            final_worth, return_pct, return_dollars, positions_at_end, metrics.
        """
        logger.info(f"[SwapPositionsSkill.simulate] {snapshot_date} → {end_date}, swaps={tickers}")

        try:
            from src.common.dao.portfolio_dao import PortfolioDAO
            from src.common.dao.alpaca_dao import AlpacaDAO
            from src.agentic.agents.backtester.core.controller import run_swap_simulation

            snap_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

            if end_dt <= snap_date:
                return {"error": f"end_date ({end_date}) must be after snapshot_date ({snapshot_date})"}

            # Validate tickers format
            for symbol, swap_info in tickers.items():
                if "swap_to" not in swap_info:
                    return {
                        "error": f"Invalid swap format for {symbol}: missing 'swap_to'",
                        "expected_format": '{"AAPL": {"swap_to": "TSLA", "quantity": 50}}',
                    }
                if "quantity" not in swap_info:
                    return {
                        "error": f"Invalid swap format for {symbol}: missing 'quantity'",
                        "expected_format": '{"AAPL": {"swap_to": "TSLA", "quantity": 50}}',
                    }

            portfolio_dao = PortfolioDAO()
            snapshot_history = portfolio_dao.get_snapshot_history(
                start_date=snap_date - timedelta(days=7), end_date=snap_date
            )
            if snapshot_history.empty:
                portfolio_dao.close()
                return {
                    "error": f"No portfolio snapshot found near {snapshot_date}",
                    "suggestion": "Create a portfolio snapshot first or try a different date",
                }

            snapshot_row = snapshot_history.iloc[0]
            actual_snapshot_date = snapshot_row["date_only"]
            positions_json = snapshot_row.get("positions_json")
            if not positions_json:
                portfolio_dao.close()
                return {
                    "error": f"Snapshot from {actual_snapshot_date} has no position details",
                    "suggestion": "Use newer snapshots with position data",
                }

            positions_list = (
                json.loads(positions_json) if isinstance(positions_json, str) else positions_json
            )
            positions = {p["symbol"]: p for p in positions_list if p.get("symbol")}

            # Validate positions to be swapped exist and have sufficient quantity
            for symbol, swap_info in tickers.items():
                if symbol not in positions:
                    portfolio_dao.close()
                    return {
                        "error": f"Cannot swap {symbol} — not in snapshot",
                        "available_positions": list(positions.keys()),
                    }
                swap_qty = swap_info.get("quantity", 0)
                current_qty = positions[symbol].get("quantity", 0)
                if swap_qty > current_qty:
                    portfolio_dao.close()
                    return {
                        "error": (
                            f"Cannot swap {swap_qty} shares of {symbol} — "
                            f"only {current_qty} available in snapshot"
                        )
                    }

            portfolio_snapshot = {
                "date": actual_snapshot_date,
                "timestamp": snapshot_row["timestamp"],
                "cash": float(snapshot_row["cash"]),
                "equity": float(snapshot_row["equity"]),
                "buying_power": float(snapshot_row.get("buying_power", 0)),
                "positions": positions,
                "long_positions": snapshot_row.get("long_positions", 0),
                "short_positions": snapshot_row.get("short_positions", 0),
            }
            portfolio_dao.close()

            # Collect all symbols (old + new)
            all_symbols = list(positions.keys())
            for swap_info in tickers.values():
                new_sym = swap_info["swap_to"]
                if new_sym not in all_symbols:
                    all_symbols.append(new_sym)

            start_dt_ts = datetime.combine(snap_date, datetime.min.time())
            end_dt_ts = datetime.combine(end_dt, datetime.max.time())

            alpaca_dao = AlpacaDAO()
            bars_list = []
            for sym in all_symbols:
                sym_bars = alpaca_dao.get_bars(
                    symbol=sym, start=start_dt_ts, end=end_dt_ts, timeframe="1Day"
                )
                if not sym_bars.empty:
                    sym_bars["symbol"] = sym
                    bars_list.append(sym_bars)
            alpaca_dao.close()

            if not bars_list:
                return {
                    "error": f"No historical data for {all_symbols} from {snapshot_date} to {end_date}",
                    "suggestion": "Ingest market data for these symbols first",
                }

            bars_df = pd.concat(bars_list, ignore_index=True)
            result = run_swap_simulation(
                snapshot=portfolio_snapshot,
                end_date=end_dt,
                bars_df=bars_df,
                swaps=tickers,
            )
            logger.info(f"[SwapPositionsSkill.simulate] {result.get('return_pct', 0):.2f}% return")
            return result

        except Exception as exc:
            logger.error(f"[SwapPositionsSkill.simulate] Error: {exc}", exc_info=True)
            return {"error": f"Swap simulation failed: {exc}"}


# =============================================================================
# Module-level singleton instances (backward-compat convenience)
# =============================================================================

backtest_skill = BacktestStrategySkill()
snapshot_skill = SnapshotSkill()
swap_skill = SwapPositionsSkill()

# Legacy function aliases so the registry can import them without change
backtest_strategy_core = backtest_skill.run
save_eod_snapshot_core = snapshot_skill.save_eod
snapshot_worth_core = snapshot_skill.get_worth
swap_positions_core = swap_skill.simulate

__all__ = [
    "BacktestStrategySkill",
    "SnapshotSkill",
    "SwapPositionsSkill",
    "backtest_skill",
    "snapshot_skill",
    "swap_skill",
    # Legacy function aliases
    "backtest_strategy_core",
    "save_eod_snapshot_core",
    "snapshot_worth_core",
    "swap_positions_core",
]
