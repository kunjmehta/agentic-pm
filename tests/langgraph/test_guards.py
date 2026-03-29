"""Unit tests for the guard nodes."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from src.langgraph.nodes.guards import market_hours_guard, portfolio_guard


class TestMarketHoursGuard:
    """Tests for market_hours_guard node."""

    def test_backtest_mode_bypasses_guard(self):
        result = market_hours_guard({"backtest_mode": True})
        assert result == {}

    def test_live_mode_may_block(self):
        result = market_hours_guard({"backtest_mode": False})
        # Either passes (market open) or blocks with routing_error
        if result:
            assert "routing_error" in result
            assert "final_response" in result
            assert "Market" in result["routing_error"]

    def test_block_sets_both_keys(self):
        """Simulate a block and verify both routing keys are present."""
        from unittest.mock import patch

        with patch(
            "src.langgraph.nodes.guards.MarketHoursGuardMiddleware.before_agent",
            side_effect=RuntimeError("Market closed (test)"),
        ):
            result = market_hours_guard({"backtest_mode": False})
            assert "routing_error" in result
            assert "final_response" in result
            assert result["routing_error"] == "Market closed (test)"


class TestPortfolioGuard:
    """Tests for portfolio_guard node."""

    def test_backtest_mode_bypasses_guard(self):
        result = portfolio_guard({"backtest_mode": True})
        assert result == {}

    def test_block_sets_both_keys(self):
        """Simulate a risk limit violation."""
        from unittest.mock import patch

        with patch(
            "src.langgraph.nodes.guards.PortfolioGuardMiddleware.before_agent",
            side_effect=RuntimeError("Daily loss exceeded"),
        ):
            result = portfolio_guard({"backtest_mode": False})
            assert "routing_error" in result
            assert "final_response" in result
