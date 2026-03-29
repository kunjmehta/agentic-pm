"""Unit tests for metrics calculations."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import pandas as pd
import numpy as np

from src.agentic.agents.backtester.core.metrics import (
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_trade_statistics,
    calculate_all_metrics
)


class TestSharpeRatio:
    """Test Sharpe ratio calculation."""

    def test_positive_returns(self):
        """Test Sharpe with positive returns."""
        returns = pd.Series([0.01, 0.02, 0.015, 0.012, 0.018])
        sharpe = calculate_sharpe_ratio(returns, risk_free_rate=0.0)

        assert sharpe > 0

    def test_negative_returns(self):
        """Test Sharpe with negative returns."""
        returns = pd.Series([-0.01, -0.02, -0.015, -0.012, -0.018])
        sharpe = calculate_sharpe_ratio(returns, risk_free_rate=0.0)

        assert sharpe < 0

    def test_zero_volatility(self):
        """Test Sharpe with zero volatility."""
        returns = pd.Series([0.01, 0.01, 0.01, 0.01, 0.01])
        sharpe = calculate_sharpe_ratio(returns, risk_free_rate=0.0)

        # Should return 0 for zero volatility
        assert sharpe == 0.0

    def test_empty_returns(self):
        """Test Sharpe with empty returns."""
        returns = pd.Series([])
        sharpe = calculate_sharpe_ratio(returns)

        assert sharpe == 0.0


class TestSortinoRatio:
    """Test Sortino ratio calculation."""

    def test_mixed_returns(self):
        """Test Sortino with mixed returns."""
        returns = pd.Series([0.02, -0.01, 0.03, -0.015, 0.025])
        sortino = calculate_sortino_ratio(returns, risk_free_rate=0.0)

        assert sortino > 0

    def test_no_negative_returns(self):
        """Test Sortino with all positive returns."""
        returns = pd.Series([0.01, 0.02, 0.015, 0.012])
        sortino = calculate_sortino_ratio(returns, risk_free_rate=0.0)

        # Should return 0 when no downside
        assert sortino == 0.0


class TestMaxDrawdown:
    """Test max drawdown calculation."""

    def test_drawdown_calculation(self):
        """Test drawdown with typical equity curve."""
        equity = pd.Series([100000, 105000, 103000, 108000, 102000, 106000])
        max_dd, peak_date, trough_date = calculate_max_drawdown(equity)

        # Peak at 108000 (index 3), trough at 102000 (index 4)
        # Drawdown: (102000 - 108000) / 108000 = -5.56%
        assert max_dd < 0
        assert abs(max_dd - (-5.56)) < 0.1

    def test_no_drawdown(self):
        """Test with continuously increasing equity."""
        equity = pd.Series([100000, 105000, 110000, 115000])
        max_dd, _, _ = calculate_max_drawdown(equity)

        assert max_dd == 0.0

    def test_empty_equity(self):
        """Test with empty equity series."""
        equity = pd.Series([])
        max_dd, peak_date, trough_date = calculate_max_drawdown(equity)

        assert max_dd == 0.0
        assert peak_date is None
        assert trough_date is None


class TestWinRate:
    """Test win rate calculation."""

    def test_mixed_trades(self):
        """Test win rate with winning and losing trades."""
        trades = [
            {"pnl": 100.0},
            {"pnl": -50.0},
            {"pnl": 200.0},
            {"pnl": -30.0},
            {"pnl": 150.0}
        ]

        win_rate = calculate_win_rate(trades)

        # 3 winners out of 5 = 0.6
        assert win_rate == 0.6

    def test_all_winners(self):
        """Test win rate with all winning trades."""
        trades = [{"pnl": 100.0}, {"pnl": 50.0}, {"pnl": 75.0}]
        win_rate = calculate_win_rate(trades)

        assert win_rate == 1.0

    def test_all_losers(self):
        """Test win rate with all losing trades."""
        trades = [{"pnl": -100.0}, {"pnl": -50.0}]
        win_rate = calculate_win_rate(trades)

        assert win_rate == 0.0

    def test_empty_trades(self):
        """Test win rate with no trades."""
        trades = []
        win_rate = calculate_win_rate(trades)

        assert win_rate == 0.0


class TestProfitFactor:
    """Test profit factor calculation."""

    def test_profitable_strategy(self):
        """Test profit factor for profitable strategy."""
        trades = [
            {"pnl": 300.0},
            {"pnl": -100.0},
            {"pnl": 200.0},
            {"pnl": -50.0}
        ]

        pf = calculate_profit_factor(trades)

        # Gross profit: 500, Gross loss: 150
        # PF = 500 / 150 = 3.33
        assert abs(pf - 3.33) < 0.1

    def test_no_losses(self):
        """Test profit factor with no losses."""
        trades = [{"pnl": 100.0}, {"pnl": 200.0}]
        pf = calculate_profit_factor(trades)

        # Should return infinity
        assert pf == float('inf')

    def test_no_profits(self):
        """Test profit factor with no profits."""
        trades = [{"pnl": -100.0}, {"pnl": -50.0}]
        pf = calculate_profit_factor(trades)

        assert pf == 0.0


class TestTradeStatistics:
    """Test trade statistics calculation."""

    def test_comprehensive_stats(self):
        """Test complete trade statistics."""
        trades = [
            {"pnl": 150.0},
            {"pnl": -50.0},
            {"pnl": 200.0},
            {"pnl": -30.0},
            {"pnl": 100.0}
        ]

        stats = calculate_trade_statistics(trades)

        assert stats["total_trades"] == 5
        assert stats["winning_trades"] == 3
        assert stats["losing_trades"] == 2
        assert stats["avg_win"] == 150.0  # (150 + 200 + 100) / 3
        assert stats["avg_loss"] == -40.0  # (-50 + -30) / 2
        assert stats["largest_win"] == 200.0
        assert stats["largest_loss"] == -50.0


class TestCalculateAllMetrics:
    """Test comprehensive metrics calculation."""

    def test_complete_metrics(self):
        """Test calculating all metrics together."""
        trades = [
            {"pnl": 150.0},
            {"pnl": -50.0},
            {"pnl": 200.0}
        ]

        equity = pd.Series([100000, 100150, 100100, 100300])

        metrics = calculate_all_metrics(
            trades=trades,
            daily_equity=equity,
            initial_capital=100000.0,
            final_capital=100300.0
        )

        assert "total_return_pct" in metrics
        assert "sharpe_ratio" in metrics
        assert "max_drawdown_pct" in metrics
        assert "win_rate" in metrics
        assert "profit_factor" in metrics
        assert metrics["total_trades"] == 3
        assert metrics["winning_trades"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
