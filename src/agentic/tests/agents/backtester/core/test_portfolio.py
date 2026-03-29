"""Unit tests for Portfolio class."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from datetime import date

from src.agentic.agents.backtester.core.portfolio import Portfolio


class TestPortfolioInitialization:
    """Test portfolio initialization."""

    def test_init_with_cash(self):
        """Test basic initialization with cash."""
        portfolio = Portfolio(initial_cash=100000.0)
        assert portfolio.get_cash() == 100000.0
        assert len(portfolio.get_all_positions()) == 0

    def test_init_with_starting_positions(self):
        """Test initialization with starting positions."""
        starting_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "quantity": 100,
                "cost_basis": 150.0,
                "side": "long"
            }
        }
        portfolio = Portfolio(initial_cash=50000.0, starting_positions=starting_positions)
        assert portfolio.get_cash() == 50000.0
        assert len(portfolio.get_all_positions()) == 1
        assert portfolio.get_position("AAPL") is not None


class TestPortfolioBuyOperations:
    """Test buy operations."""

    def test_buy_success(self):
        """Test successful buy operation."""
        portfolio = Portfolio(initial_cash=100000.0)
        success = portfolio.apply_buy("AAPL", 100, 150.0)

        assert success is True
        assert portfolio.get_cash() == 85000.0  # 100000 - (100 * 150)

        position = portfolio.get_position("AAPL")
        assert position is not None
        assert position["quantity"] == 100
        assert position["cost_basis"] == 150.0

    def test_buy_insufficient_cash(self):
        """Test buy with insufficient cash."""
        portfolio = Portfolio(initial_cash=1000.0)
        success = portfolio.apply_buy("AAPL", 100, 150.0)  # Needs $15,000

        # Should buy as many as possible (6 shares)
        assert success is True
        assert portfolio.get_position("AAPL")["quantity"] == 6

    def test_buy_cost_basis_averaging(self):
        """Test cost basis averaging on multiple buys."""
        portfolio = Portfolio(initial_cash=100000.0)

        # First buy: 100 shares at $150
        portfolio.apply_buy("AAPL", 100, 150.0)
        assert portfolio.get_position("AAPL")["cost_basis"] == 150.0

        # Second buy: 50 shares at $160
        portfolio.apply_buy("AAPL", 50, 160.0)

        position = portfolio.get_position("AAPL")
        assert position["quantity"] == 150
        # Average cost basis: (100*150 + 50*160) / 150 = 153.33
        assert abs(position["cost_basis"] - 153.33) < 0.01


class TestPortfolioSellOperations:
    """Test sell operations."""

    def test_sell_success(self):
        """Test successful sell operation."""
        portfolio = Portfolio(initial_cash=100000.0)
        portfolio.apply_buy("AAPL", 100, 150.0)

        success, realized_pnl = portfolio.apply_sell("AAPL", 50, 170.0)

        assert success is True
        assert realized_pnl == 1000.0  # (170 - 150) * 50
        assert portfolio.get_cash() == 93500.0  # 85000 + (50 * 170)
        assert portfolio.get_position("AAPL")["quantity"] == 50

    def test_sell_all_shares(self):
        """Test selling all shares removes position."""
        portfolio = Portfolio(initial_cash=100000.0)
        portfolio.apply_buy("AAPL", 100, 150.0)

        portfolio.apply_sell("AAPL", 100, 160.0)

        assert portfolio.get_position("AAPL") is None

    def test_sell_nonexistent_position(self):
        """Test selling position that doesn't exist."""
        portfolio = Portfolio(initial_cash=100000.0)

        success, pnl = portfolio.apply_sell("AAPL", 50, 150.0)

        assert success is False
        assert pnl == 0.0

    def test_sell_more_than_owned(self):
        """Test selling more shares than owned."""
        portfolio = Portfolio(initial_cash=100000.0)
        portfolio.apply_buy("AAPL", 100, 150.0)

        # Try to sell 150, should only sell 100
        success, pnl = portfolio.apply_sell("AAPL", 150, 160.0)

        assert success is True
        assert portfolio.get_position("AAPL") is None  # All shares sold


class TestPortfolioValuation:
    """Test portfolio valuation methods."""

    def test_get_equity(self):
        """Test equity calculation."""
        portfolio = Portfolio(initial_cash=100000.0)
        portfolio.apply_buy("AAPL", 100, 150.0)

        current_prices = {"AAPL": 160.0}
        equity = portfolio.get_equity(current_prices)

        # Cash: 85000 + Position value: 100 * 160 = 101000
        assert equity == 101000.0

    def test_update_position_prices(self):
        """Test updating position prices."""
        portfolio = Portfolio(initial_cash=100000.0)
        portfolio.apply_buy("AAPL", 100, 150.0)

        current_prices = {"AAPL": 165.0}
        portfolio.update_position_prices(current_prices)

        position = portfolio.get_position("AAPL")
        assert position["current_price"] == 165.0
        assert position["market_value"] == 16500.0
        assert position["unrealized_pnl"] == 1500.0

    def test_get_summary(self):
        """Test portfolio summary."""
        portfolio = Portfolio(initial_cash=100000.0)
        portfolio.apply_buy("AAPL", 100, 150.0)

        # Sell some for realized gains
        portfolio.apply_sell("AAPL", 50, 170.0)

        current_prices = {"AAPL": 165.0}
        summary = portfolio.get_summary(current_prices)

        assert summary["cash"] == 93500.0
        assert summary["num_positions"] == 1
        assert summary["realized_pnl"] == 1000.0


class TestPortfolioSnapshot:
    """Test snapshot functionality."""

    def test_get_snapshot(self):
        """Test getting portfolio snapshot."""
        portfolio = Portfolio(initial_cash=100000.0)
        portfolio.apply_buy("AAPL", 100, 150.0)

        snapshot = portfolio.get_snapshot()

        assert snapshot["cash"] == 85000.0
        assert len(snapshot["positions"]) == 1
        assert snapshot["long_positions"] == 1
        assert snapshot["short_positions"] == 0

    def test_snapshot_defensive_copy(self):
        """Test that snapshot is defensive copy."""
        portfolio = Portfolio(initial_cash=100000.0)
        portfolio.apply_buy("AAPL", 100, 150.0)

        snapshot = portfolio.get_snapshot()

        # Modify snapshot
        snapshot["positions"]["AAPL"]["quantity"] = 999

        # Original should be unchanged
        assert portfolio.get_position("AAPL")["quantity"] == 100


class TestPortfolioRealizedGains:
    """Test realized gains tracking."""

    def test_realized_gains_single_symbol(self):
        """Test tracking realized gains for single symbol."""
        portfolio = Portfolio(initial_cash=100000.0)
        portfolio.apply_buy("AAPL", 100, 150.0)
        portfolio.apply_sell("AAPL", 50, 170.0)

        assert portfolio.get_realized_gains("AAPL") == 1000.0

    def test_realized_gains_total(self):
        """Test total realized gains across symbols."""
        portfolio = Portfolio(initial_cash=100000.0)
        portfolio.apply_buy("AAPL", 100, 150.0)
        portfolio.apply_buy("TSLA", 50, 200.0)

        portfolio.apply_sell("AAPL", 50, 170.0)  # +1000
        portfolio.apply_sell("TSLA", 25, 220.0)  # +500

        assert portfolio.get_realized_gains() == 1500.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
