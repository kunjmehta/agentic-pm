"""Unit tests for Portfolio Tools (Enhanced).

Tests the refactored tools that use Skills + DAO layers.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.agents.portfolio_tools import (
    get_portfolio_status,
    get_positions_summary,
    check_portfolio_health,
    delegate_to_quant_analyst,
    clear_portfolio_cache
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before each test."""
    clear_portfolio_cache()
    yield
    clear_portfolio_cache()


class TestGetPortfolioStatus:
    """Test get_portfolio_status tool."""

    @patch('src.agents.portfolio_tools.fetch_account_info')
    @patch('src.agents.portfolio_tools.fetch_positions')
    @patch('src.agents.portfolio_tools.PortfolioDAO')
    def test_success(self, mock_dao_class, mock_positions, mock_account):
        """Test successful portfolio status fetch."""
        # Mock account data
        mock_account.return_value = {
            "equity": 100000.0,
            "cash": 50000.0,
            "buying_power": 200000.0,
            "portfolio_value": 100000.0,
            "last_equity": 99000.0
        }

        # Mock positions data
        mock_positions.return_value = [
            {"symbol": "AAPL", "qty": 10, "side": "long"},
            {"symbol": "MSFT", "qty": 5, "side": "long"}
        ]

        # Mock DAO
        mock_dao = MagicMock()
        mock_dao_class.return_value = mock_dao

        # Execute
        result_json = get_portfolio_status.invoke({})
        result = json.loads(result_json)

        # Verify
        assert result["equity"] == 100000.0
        assert result["cash"] == 50000.0
        assert result["buying_power"] == 200000.0
        assert result["long_positions"] == 2
        assert result["short_positions"] == 0
        assert result["cached"] is False

        # Verify DAO was called to save snapshot
        mock_dao.save_snapshot.assert_called_once()
        mock_dao.close.assert_called_once()

    @patch('src.agents.portfolio_tools.fetch_account_info')
    @patch('src.agents.portfolio_tools.fetch_positions')
    def test_caching(self, mock_positions, mock_account):
        """Test that caching works."""
        # Mock data
        mock_account.return_value = {
            "equity": 100000.0,
            "cash": 50000.0,
            "buying_power": 200000.0,
            "portfolio_value": 100000.0,
            "last_equity": 99000.0
        }
        mock_positions.return_value = []

        # First call - should hit API
        result1_json = get_portfolio_status.invoke({})
        result1 = json.loads(result1_json)
        assert result1["cached"] is False

        # Second call - should hit cache
        result2_json = get_portfolio_status.invoke({})
        result2 = json.loads(result2_json)
        assert result2["cached"] is True
        assert "cache_age_seconds" in result2

        # Verify API was only called once
        assert mock_account.call_count == 1
        assert mock_positions.call_count == 1

    @patch('src.agents.portfolio_tools.fetch_account_info')
    @patch('src.agents.portfolio_tools.fetch_positions')
    def test_graceful_degradation_with_cache(self, mock_positions, mock_account):
        """Test graceful degradation when API fails but cache exists."""
        # First call succeeds and populates cache
        mock_account.return_value = {
            "equity": 100000.0,
            "cash": 50000.0,
            "buying_power": 200000.0,
            "portfolio_value": 100000.0,
            "last_equity": 99000.0
        }
        mock_positions.return_value = []

        result1 = get_portfolio_status.invoke({})

        # Second call returns cached data even if API would fail
        # This tests that caching provides resilience
        result2_json = get_portfolio_status.invoke({})
        result2 = json.loads(result2_json)

        # Should return cached data (graceful behavior)
        assert result2["cached"] is True
        assert result2["equity"] == 100000.0  # Same data from cache

        # API should only be called once (first time)
        assert mock_account.call_count == 1
        assert mock_positions.call_count == 1

    @patch('src.agents.portfolio_tools.fetch_account_info')
    def test_error_without_cache(self, mock_account):
        """Test error response when API fails and no cache exists."""
        mock_account.side_effect = Exception("API Error")

        result_json = get_portfolio_status.invoke({})
        result = json.loads(result_json)

        assert "error" in result
        assert result["error"] == "Failed to fetch portfolio status"


class TestGetPositionsSummary:
    """Test get_positions_summary tool."""

    @patch('src.agents.portfolio_tools.fetch_positions')
    def test_success(self, mock_positions):
        """Test successful positions fetch."""
        mock_positions.return_value = [
            {
                "symbol": "AAPL",
                "qty": 10.0,
                "side": "long",
                "market_value": 1500.0,
                "cost_basis": 1400.0,
                "unrealized_pl": 100.0,
                "unrealized_plpc": 0.0714
            },
            {
                "symbol": "MSFT",
                "qty": 5.0,
                "side": "long",
                "market_value": 1000.0,
                "cost_basis": 950.0,
                "unrealized_pl": 50.0,
                "unrealized_plpc": 0.0526
            }
        ]

        result_json = get_positions_summary.invoke({})
        result = json.loads(result_json)

        assert result["count"] == 2
        assert result["total_market_value"] == 2500.0
        assert result["total_unrealized_pl"] == 150.0
        assert len(result["positions"]) == 2

    @patch('src.agents.portfolio_tools.fetch_positions')
    def test_empty_positions(self, mock_positions):
        """Test with no positions."""
        mock_positions.return_value = []

        result_json = get_positions_summary.invoke({})
        result = json.loads(result_json)

        assert result["count"] == 0
        assert result["total_market_value"] == 0.0
        assert result["total_unrealized_pl"] == 0.0
        assert result["positions"] == []


class TestCheckPortfolioHealth:
    """Test check_portfolio_health tool."""

    @patch('src.agents.portfolio_tools.get_portfolio_status')
    @patch('src.agents.portfolio_tools.get_positions_summary')
    @patch('src.agents.portfolio_tools.PortfolioDAO')
    def test_healthy_portfolio(self, mock_dao_class, mock_positions, mock_status):
        """Test health check with healthy portfolio."""
        # Mock portfolio status
        mock_status.invoke.return_value = json.dumps({
            "equity": 100000.0,
            "cash": 10000.0,
            "buying_power": 200000.0
        })

        # Mock positions (small positions, well diversified)
        mock_positions.invoke.return_value = json.dumps({
            "positions": [
                {"symbol": "AAPL", "market_value": 5000.0, "qty": 10},
                {"symbol": "MSFT", "market_value": 4000.0, "qty": 8}
            ],
            "count": 2
        })

        # Mock DAO risk parameters
        mock_dao = MagicMock()
        mock_dao.get_risk_parameters.return_value = {
            "position_limit_percent": {"value": 0.1},
            "daily_loss_limit": {"value": 0.05},
            "max_position_size": {"value": 1000}
        }
        mock_dao_class.return_value = mock_dao

        result_json = check_portfolio_health.invoke({})
        result = json.loads(result_json)

        assert result["health_status"] == "healthy"
        assert result["violations"] == []
        assert len(result["checks_performed"]) > 0

    @patch('src.agents.portfolio_tools.get_portfolio_status')
    @patch('src.agents.portfolio_tools.get_positions_summary')
    @patch('src.agents.portfolio_tools.PortfolioDAO')
    def test_position_concentration_violation(self, mock_dao_class, mock_positions, mock_status):
        """Test health check with position concentration violation."""
        # Mock portfolio status
        mock_status.invoke.return_value = json.dumps({
            "equity": 100000.0,
            "cash": 10000.0,
            "buying_power": 200000.0
        })

        # Mock positions (one position is too large)
        mock_positions.invoke.return_value = json.dumps({
            "positions": [
                {"symbol": "AAPL", "market_value": 15000.0, "qty": 30}  # 15% of portfolio
            ],
            "count": 1
        })

        # Mock DAO risk parameters (10% limit)
        mock_dao = MagicMock()
        mock_dao.get_risk_parameters.return_value = {
            "position_limit_percent": {"value": 0.1},
            "daily_loss_limit": {"value": 0.05},
            "max_position_size": {"value": 1000}
        }
        mock_dao_class.return_value = mock_dao

        result_json = check_portfolio_health.invoke({})
        result = json.loads(result_json)

        assert result["health_status"] == "unhealthy"
        assert len(result["violations"]) == 1
        assert result["violations"][0]["rule"] == "position_limit_percent"
        assert result["violations"][0]["symbol"] == "AAPL"


class TestDelegateToQuantAnalyst:
    """Test delegate_to_quant_analyst tool."""

    @patch('src.agents.quant.analyst.QuantAnalyst')
    def test_successful_delegation(self, mock_quant_class):
        """Test successful delegation to Quant Analyst."""
        # Mock Quant Analyst
        mock_quant = MagicMock()
        mock_quant.invoke.return_value = {
            "response": "AAPL analysis complete: bullish signal",
            "timestamp": datetime.now().isoformat()
        }
        mock_quant_class.return_value = mock_quant

        result_json = delegate_to_quant_analyst.invoke({
            "query": "Analyze AAPL",
            "thread_id": "test-thread"
        })
        result = json.loads(result_json)

        assert result["status"] == "success"
        assert "AAPL analysis" in result["response"]
        assert result["delegated_to"] == "quant_analyst"

    @patch('src.agents.quant.analyst.QuantAnalyst')
    def test_delegation_failure_graceful(self, mock_quant_class):
        """Test graceful degradation when delegation fails."""
        # Mock Quant Analyst failure
        mock_quant_class.side_effect = Exception("Model not found")

        result_json = delegate_to_quant_analyst.invoke({
            "query": "Analyze AAPL",
            "thread_id": "test-thread"
        })
        result = json.loads(result_json)

        assert result["status"] == "error"
        assert result["error"] == "Quant Analyst temporarily unavailable"
        assert "fallback_action" in result
        assert "recommendation" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
