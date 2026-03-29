"""Unit tests for valuation functions."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest

from src.agentic.agents.backtester.core.valuation import (
    calculate_position_value,
    calculate_portfolio_value,
    compute_exposures,
    compute_portfolio_summary
)


class TestCalculatePositionValue:
    """Test position value calculation."""

    def test_long_position_profit(self):
        """Test long position with profit."""
        position = calculate_position_value(
            symbol="AAPL",
            quantity=100,
            current_price=160.0,
            cost_basis=150.0,
            side="long"
        )

        assert position["symbol"] == "AAPL"
        assert position["quantity"] == 100
        assert position["market_value"] == 16000.0
        assert position["unrealized_pnl"] == 1000.0
        assert abs(position["unrealized_pnl_pct"] - 6.67) < 0.01

    def test_long_position_loss(self):
        """Test long position with loss."""
        position = calculate_position_value(
            symbol="AAPL",
            quantity=100,
            current_price=140.0,
            cost_basis=150.0,
            side="long"
        )

        assert position["unrealized_pnl"] == -1000.0
        assert position["unrealized_pnl_pct"] < 0

    def test_short_position_profit(self):
        """Test short position with profit."""
        position = calculate_position_value(
            symbol="SPY",
            quantity=-100,
            current_price=450.0,
            cost_basis=460.0,
            side="short"
        )

        assert position["market_value"] == -45000.0
        assert position["unrealized_pnl"] == 1000.0  # Profit from price drop


class TestCalculatePortfolioValue:
    """Test portfolio value calculation."""

    def test_cash_only(self):
        """Test portfolio with only cash."""
        value = calculate_portfolio_value(
            cash=100000.0,
            positions={},
            current_prices={}
        )

        assert value == 100000.0

    def test_cash_and_positions(self):
        """Test portfolio with cash and positions."""
        positions = {
            "AAPL": {
                "quantity": 100,
                "cost_basis": 150.0,
                "side": "long"
            },
            "TSLA": {
                "quantity": 50,
                "cost_basis": 200.0,
                "side": "long"
            }
        }

        prices = {"AAPL": 160.0, "TSLA": 220.0}

        value = calculate_portfolio_value(50000.0, positions, prices)

        # Cash: 50000 + AAPL: 16000 + TSLA: 11000 = 77000
        assert value == 77000.0

    def test_missing_price(self):
        """Test handling missing prices."""
        positions = {
            "AAPL": {"quantity": 100, "cost_basis": 150.0, "side": "long"}
        }

        prices = {}  # No price for AAPL

        value = calculate_portfolio_value(50000.0, positions, prices)

        # Should only count cash
        assert value == 50000.0


class TestComputeExposures:
    """Test exposure calculations."""

    def test_long_only_exposures(self):
        """Test exposures for long-only portfolio."""
        positions = {
            "AAPL": {"quantity": 100, "cost_basis": 150.0, "side": "long"},
            "TSLA": {"quantity": 50, "cost_basis": 200.0, "side": "long"}
        }

        prices = {"AAPL": 160.0, "TSLA": 220.0}

        exposures = compute_exposures(
            cash=50000.0,
            positions=positions,
            current_prices=prices,
            total_equity=77000.0
        )

        assert exposures["long_value"] == 27000.0
        assert exposures["short_value"] == 0.0
        assert exposures["gross_exposure"] == 27000.0
        assert exposures["net_exposure"] == 27000.0
        assert abs(exposures["long_pct"] - 35.06) < 0.1

    def test_mixed_exposures(self):
        """Test exposures with long and short positions."""
        positions = {
            "AAPL": {"quantity": 100, "cost_basis": 150.0, "side": "long"},
            "SPY": {"quantity": -50, "cost_basis": 460.0, "side": "short"}
        }

        prices = {"AAPL": 160.0, "SPY": 450.0}

        exposures = compute_exposures(
            cash=50000.0,
            positions=positions,
            current_prices=prices,
            total_equity=50000.0 + 16000.0 - 22500.0
        )

        assert exposures["long_value"] == 16000.0
        assert exposures["short_value"] == 22500.0
        assert exposures["gross_exposure"] == 38500.0


class TestComputePortfolioSummary:
    """Test portfolio summary calculation."""

    def test_profitable_portfolio(self):
        """Test summary for profitable portfolio."""
        positions = {
            "AAPL": {
                "symbol": "AAPL",
                "quantity": 100,
                "cost_basis": 150.0,
                "current_price": 160.0,
                "market_value": 16000.0,
                "unrealized_pnl": 1000.0,
                "side": "long"
            }
        }

        prices = {"AAPL": 160.0}

        summary = compute_portfolio_summary(
            cash=50000.0,
            positions=positions,
            current_prices=prices,
            initial_capital=60000.0
        )

        assert summary["cash"] == 50000.0
        assert summary["equity"] == 66000.0
        assert summary["return_dollars"] == 6000.0
        assert summary["return_pct"] == 10.0
        assert summary["num_positions"] == 1

    def test_losing_portfolio(self):
        """Test summary for losing portfolio."""
        positions = {
            "AAPL": {
                "quantity": 100,
                "cost_basis": 150.0,
                "side": "long"
            }
        }

        prices = {"AAPL": 140.0}

        summary = compute_portfolio_summary(
            cash=50000.0,
            positions=positions,
            current_prices=prices,
            initial_capital=70000.0
        )

        assert summary["equity"] == 64000.0
        assert summary["return_dollars"] == -6000.0
        assert abs(summary["return_pct"] - (-8.57)) < 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
