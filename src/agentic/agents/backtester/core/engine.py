"""Simulation execution engine for backtesting.

Orchestrates bar-by-bar replay of historical data, executes trades based on
strategy signals, and tracks portfolio state throughout the simulation.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Dict, List, Callable, Optional
import pandas as pd
from datetime import date, datetime

try:
    from src.agentic.agents.backtester.core.bt_types import (
        Action, ActionLiteral, TradeRecord, BacktestResult
    )
    from src.agentic.agents.backtester.core.portfolio import Portfolio
    from src.agentic.agents.backtester.core.metrics import calculate_all_metrics
except ModuleNotFoundError:
    from bt_types import Action, ActionLiteral, TradeRecord, BacktestResult
    from portfolio import Portfolio
    from metrics import calculate_all_metrics


class BacktestEngine:
    """Coordinates backtesting simulation workflow.

    Replays historical bars chronologically, applies strategy signals,
    executes trades, and tracks portfolio state throughout the simulation.

    Attributes:
        initial_capital: Starting capital for simulation
        strategy_signals: Callable that returns trading signals
        slippage_pct: Slippage percentage (default: 0.05%)
        portfolio: Portfolio instance tracking state
        trades: List of executed trades
        daily_equity: List of daily equity values
    """

    def __init__(
        self,
        initial_capital: float,
        strategy_signals: Optional[Callable] = None,
        slippage_pct: float = 0.0005
    ):
        """Initialize backtest engine.

        Args:
            initial_capital: Starting capital
            strategy_signals: Optional function that returns signals
            slippage_pct: Slippage as decimal (0.0005 = 0.05%)
        """
        self.initial_capital = initial_capital
        self.strategy_signals = strategy_signals
        self.slippage_pct = slippage_pct

        self.portfolio = Portfolio(initial_cash=initial_capital)
        self.trades: List[TradeRecord] = []
        self.daily_equity: List[float] = []
        self.trade_id_counter = 1

    def run(
        self,
        bars_df: pd.DataFrame,
        start_date: date,
        end_date: date,
        symbol: str
    ) -> BacktestResult:
        """Execute simulation from start to end date using bars data.

        Args:
            bars_df: DataFrame with OHLCV data (columns: timestamp, open, high, low, close, volume)
            start_date: Start date for simulation
            end_date: End date for simulation
            symbol: Primary stock symbol being backtested

        Returns:
            BacktestResult with trades, metrics, and summary
        """
        if bars_df.empty:
            return self._create_error_result(
                "No historical data available for simulation",
                symbol,
                start_date,
                end_date
            )

        # Ensure timestamp column
        if 'timestamp' not in bars_df.columns:
            return self._create_error_result(
                "bars_df must have 'timestamp' column",
                symbol,
                start_date,
                end_date
            )

        # Filter bars to date range
        bars_df = bars_df.copy()
        if not pd.api.types.is_datetime64_any_dtype(bars_df['timestamp']):
            bars_df['timestamp'] = pd.to_datetime(bars_df['timestamp'])

        bars_df = bars_df[
            (bars_df['timestamp'].dt.date >= start_date) &
            (bars_df['timestamp'].dt.date <= end_date)
        ]

        if bars_df.empty:
            return self._create_error_result(
                f"No bars found in date range {start_date} to {end_date}",
                symbol,
                start_date,
                end_date
            )

        # Group by trading day
        bars_df['date'] = bars_df['timestamp'].dt.date
        trading_days = bars_df['date'].unique()

        # Process each trading day
        for trading_day in trading_days:
            day_bars = bars_df[bars_df['date'] == trading_day]
            self._process_day(day_bars, symbol)

            # Record end-of-day equity
            current_prices = {symbol: day_bars.iloc[-1]['close']}
            eod_equity = self.portfolio.get_equity(current_prices)
            self.daily_equity.append(eod_equity)

        # Close any remaining open positions at end of backtest
        if len(trading_days) > 0:
            last_day_bars = bars_df[bars_df["date"] == trading_days[-1]]
            if not last_day_bars.empty:
                last_close = float(last_day_bars.iloc[-1]["close"])
                last_date = trading_days[-1]
                last_timestamp = last_day_bars.iloc[-1]["timestamp"]
                self._close_open_positions_eob(symbol, last_close, last_date, last_timestamp)

                # Refresh final equity after position closure
                self.portfolio.update_position_prices({symbol: last_close})
                final_eod = self.portfolio.get_equity({symbol: last_close})
                if self.daily_equity:
                    self.daily_equity[-1] = final_eod

        # Calculate final capital
        if self.daily_equity:
            final_capital = self.daily_equity[-1]
        else:
            final_capital = self.initial_capital

        # Calculate metrics
        equity_series = pd.Series(self.daily_equity)
        metrics = calculate_all_metrics(
            trades=self.trades,
            daily_equity=equity_series,
            initial_capital=self.initial_capital,
            final_capital=final_capital
        )

        # Generate summary and recommendation
        summary = self._generate_summary(metrics, symbol, start_date, end_date)
        recommendation = self._generate_recommendation(metrics)

        return {
            "run_id": None,  # Will be set if saved to DB
            "status": "completed",
            "strategy": "buy-and-hold",  # Default for now
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "trading_days": len(trading_days),
            "initial_capital": self.initial_capital,
            "final_capital": final_capital,
            "trades": self.trades,
            "daily_performance": [{"date": trading_days[i], "equity": eq} for i, eq in enumerate(self.daily_equity)],
            "metrics": metrics,
            "summary": summary,
            "recommendation": recommendation
        }

    def _process_day(self, day_bars: pd.DataFrame, symbol: str) -> None:
        """Process a single trading day's bars.

        If strategy_signals is provided, calls it with the current day's bars
        and executes buy/sell accordingly.  Falls back to a one-time buy
        (buy-and-hold) when no signals callable is set.

        Args:
            day_bars: DataFrame with bars for one trading day
            symbol: Stock symbol
        """
        if day_bars.empty:
            return

        current_price = float(day_bars.iloc[-1]["close"])
        current_prices = {symbol: current_price}
        current_date = day_bars.iloc[0]["date"]
        current_timestamp = day_bars.iloc[-1]["timestamp"]

        # Update position prices
        self.portfolio.update_position_prices(current_prices)

        if self.strategy_signals is not None:
            signal = self.strategy_signals(symbol, day_bars)
            position = self.portfolio.get_position(symbol)

            if signal == "buy" and position is None and self.portfolio.get_cash() > 0:
                shares_to_buy = int(self.portfolio.get_cash() / current_price)
                if shares_to_buy > 0:
                    entry_price = current_price * (1 + self.slippage_pct)
                    success = self.portfolio.apply_buy(symbol, shares_to_buy, entry_price)
                    if success:
                        trade: TradeRecord = {
                            "trade_id": self.trade_id_counter,
                            "symbol": symbol,
                            "action": "buy",
                            "entry_date": current_date,
                            "entry_time": current_timestamp,
                            "entry_price": entry_price,
                            "quantity": shares_to_buy,
                            "side": "long",
                            "entry_signal": {"signal": "strategy_buy", "price": current_price},
                            "status": "open",
                        }
                        self.trades.append(trade)
                        self.trade_id_counter += 1

            elif signal == "sell" and position is not None:
                exit_price = current_price * (1 - self.slippage_pct)
                success, realized_pnl = self.portfolio.apply_sell(
                    symbol, position["quantity"], exit_price
                )
                if success:
                    for trade in reversed(self.trades):
                        if trade["symbol"] == symbol and trade["status"] == "open":
                            trade["exit_date"] = current_date
                            trade["exit_time"] = current_timestamp
                            trade["exit_price"] = exit_price
                            trade["exit_reason"] = "strategy_signal"
                            trade["pnl"] = realized_pnl
                            entry_cost = trade["entry_price"] * trade["quantity"]
                            trade["pnl_pct"] = (realized_pnl / entry_cost * 100) if entry_cost else 0.0
                            trade["status"] = "closed"
                            trade["exit_signal"] = {"signal": "strategy_sell", "price": current_price}
                            break
        else:
            # Buy-and-hold fallback: buy once on first day
            position = self.portfolio.get_position(symbol)
            if position is None and self.portfolio.get_cash() > 0:
                shares_to_buy = int(self.portfolio.get_cash() / current_price)
                if shares_to_buy > 0:
                    entry_price = current_price * (1 + self.slippage_pct)
                    success = self.portfolio.apply_buy(symbol, shares_to_buy, entry_price)
                    if success:
                        trade: TradeRecord = {
                            "trade_id": self.trade_id_counter,
                            "symbol": symbol,
                            "action": "buy",
                            "entry_date": current_date,
                            "entry_time": current_timestamp,
                            "entry_price": entry_price,
                            "quantity": shares_to_buy,
                            "side": "long",
                            "entry_signal": {"signal": "initial_entry"},
                            "status": "open",
                        }
                        self.trades.append(trade)
                        self.trade_id_counter += 1

    def _close_open_positions_eob(
        self,
        symbol: str,
        exit_price: float,
        exit_date,
        exit_timestamp,
    ) -> None:
        """Close any remaining open positions at end of backtest.

        Called after all trading days are processed to ensure every trade has
        a recorded exit and realized P&L so metrics are computed correctly.

        Args:
            symbol: Stock ticker.
            exit_price: Final EOD close price used as exit.
            exit_date: Last trading day date.
            exit_timestamp: Last bar timestamp.
        """
        position = self.portfolio.get_position(symbol)
        if position is None:
            return

        eob_price = exit_price * (1 - self.slippage_pct)
        success, realized_pnl = self.portfolio.apply_sell(
            symbol, position["quantity"], eob_price
        )
        if success:
            for trade in reversed(self.trades):
                if trade["symbol"] == symbol and trade["status"] == "open":
                    trade["exit_date"] = exit_date
                    trade["exit_time"] = exit_timestamp
                    trade["exit_price"] = eob_price
                    trade["exit_reason"] = "end_of_backtest"
                    trade["pnl"] = realized_pnl
                    entry_cost = trade["entry_price"] * trade["quantity"]
                    trade["pnl_pct"] = (realized_pnl / entry_cost * 100) if entry_cost else 0.0
                    trade["status"] = "closed"
                    trade["exit_signal"] = {"signal": "end_of_backtest"}
                    break

    def _generate_summary(
        self,
        metrics: Dict,
        symbol: str,
        start_date: date,
        end_date: date
    ) -> str:
        """Generate human-readable summary.

        Args:
            metrics: Performance metrics dict
            symbol: Stock symbol
            start_date: Start date
            end_date: End date

        Returns:
            Summary string
        """
        return (
            f"Backtest of {symbol} from {start_date} to {end_date} "
            f"({metrics.get('total_trades', 0)} trades). "
            f"Total return: {metrics.get('total_return_pct', 0):.2f}%, "
            f"Sharpe ratio: {metrics.get('sharpe_ratio', 0):.2f}, "
            f"Max drawdown: {metrics.get('max_drawdown_pct', 0):.2f}%, "
            f"Win rate: {metrics.get('win_rate', 0)*100:.1f}%."
        )

    def _generate_recommendation(self, metrics: Dict) -> str:
        """Generate deployment recommendation based on metrics.

        Args:
            metrics: Performance metrics dict

        Returns:
            Recommendation string
        """
        sharpe = metrics.get('sharpe_ratio', 0)
        max_dd = metrics.get('max_drawdown_pct', 0)
        total_return = metrics.get('total_return_pct', 0)

        if sharpe > 2.0 and max_dd > -10:
            return "STRONG CANDIDATE for live trading - excellent risk-adjusted returns with manageable drawdown"
        elif sharpe > 1.0 and max_dd > -15:
            return "CONSIDER for live trading with careful position sizing and stop-loss discipline"
        elif sharpe > 0 and max_dd > -20:
            return "PROFITABLE but risky - consider reducing position sizes or improving drawdown control"
        elif total_return > 0 and sharpe < 1:
            return "MARGINALLY PROFITABLE - returns don't justify the risk, optimize further"
        else:
            return "NOT RECOMMENDED - strategy shows negative or insufficient risk-adjusted returns"

    def _create_error_result(
        self,
        error_msg: str,
        symbol: str,
        start_date: date,
        end_date: date
    ) -> BacktestResult:
        """Create error result for failed backtest.

        Args:
            error_msg: Error message
            symbol: Stock symbol
            start_date: Start date
            end_date: End date

        Returns:
            BacktestResult with error
        """
        return {
            "run_id": None,
            "status": "failed",
            "strategy": "unknown",
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "trading_days": 0,
            "initial_capital": self.initial_capital,
            "final_capital": self.initial_capital,
            "trades": [],
            "daily_performance": [],
            "metrics": {},  # type: ignore
            "summary": f"Backtest failed: {error_msg}",
            "recommendation": "N/A",
            "error": error_msg
        }


# =============================================================================
# Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Test BacktestEngine."""
    print("=" * 60)
    print("BacktestEngine Tests")
    print("=" * 60)

    # Create sample bars data
    print("\n1. Create Sample Data:")
    dates = pd.date_range(start='2024-01-02', end='2024-01-05', freq='D')
    bars_data = []

    for day in dates:
        # Create bars for trading day (9:30 AM - 4:00 PM)
        for hour in range(10, 16):
            for minute in [0, 30]:
                timestamp = day.replace(hour=hour, minute=minute)
                bars_data.append({
                    'timestamp': timestamp,
                    'open': 150.0 + hour - 10,
                    'high': 151.0 + hour - 10,
                    'low': 149.0 + hour - 10,
                    'close': 150.5 + hour - 10,
                    'volume': 1000000
                })

    bars_df = pd.DataFrame(bars_data)
    print(f"   Created {len(bars_df)} bars across {len(dates)} days")
    print(f"   Date range: {bars_df['timestamp'].min()} to {bars_df['timestamp'].max()}")

    # Test 2: Initialize engine
    print("\n2. Initialize BacktestEngine:")
    engine = BacktestEngine(initial_capital=100000.0)
    print(f"   Initial Capital: ${engine.initial_capital:,.2f}")
    print(f"   Slippage: {engine.slippage_pct*100:.2f}%")

    # Test 3: Run backtest
    print("\n3. Run Backtest:")
    result = engine.run(
        bars_df=bars_df,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 5),
        symbol="AAPL"
    )
    print(f"   Status: {result['status']}")
    print(f"   Trading Days: {result['trading_days']}")
    print(f"   Initial Capital: ${result['initial_capital']:,.2f}")
    print(f"   Final Capital: ${result['final_capital']:,.2f}")
    print(f"   Total Trades: {len(result['trades'])}")

    # Test 4: Check metrics
    print("\n4. Performance Metrics:")
    metrics = result['metrics']
    print(f"   Total Return: {metrics.get('total_return_pct', 0):.2f}%")
    print(f"   Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
    print(f"   Max Drawdown: {metrics.get('max_drawdown_pct', 0):.2f}%")
    print(f"   Win Rate: {metrics.get('win_rate', 0)*100:.1f}%")

    # Test 5: Summary and recommendation
    print("\n5. Summary:")
    print(f"   {result['summary']}")
    print(f"\n6. Recommendation:")
    print(f"   {result['recommendation']}")

    # Test 6: Error handling
    print("\n7. Error Handling (Empty DataFrame):")
    empty_bars = pd.DataFrame()
    error_result = engine.run(
        bars_df=empty_bars,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 5),
        symbol="AAPL"
    )
    print(f"   Status: {error_result['status']}")
    print(f"   Error: {error_result.get('error', 'N/A')}")

    print("\n" + "=" * 60)
    print("BacktestEngine tests completed!")
    print("=" * 60)
