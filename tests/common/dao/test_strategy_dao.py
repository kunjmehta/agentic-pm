"""Tests for StrategyDAO - Trading strategy results persistence."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from datetime import datetime, timedelta
from src.common.dao.strategy_dao import StrategyDAO


@pytest.fixture
def strategy_dao(tmp_path):
    """Create StrategyDAO instance with temporary database for testing.
    
    Args:
        tmp_path: Pytest fixture providing temporary directory path.
        
    Yields:
        StrategyDAO instance using isolated temporary database.
    """
    test_db_path = tmp_path / "test_strategy.duckdb"
    dao = StrategyDAO(db_path=str(test_db_path))
    yield dao
    dao.close()


@pytest.fixture
def sample_strategy_result():
    """Sample strategy result data."""
    return {
        "symbol": "TEST",
        "strategy_name": "mean-reversion-test",
        "current_price": 150.25,
        "statistics": {"mean": 148.50, "std_dev": 2.35, "z_score": 0.74, "vwap": 149.80},
        "indicators": {"sma_20": 148.75, "sma_50": 147.80, "ema_20": 149.10},
        "signals": {
            "overall_signal": "hold",
            "z_score_signal": "neutral",
            "ma_cross_signal": "bullish"
        },
        "action": "hold",
        "confidence": 0.65,
        "reason": "Price within normal range",
        "current_state": "neutral",
        "parameters": {"lookback": 60, "threshold": 2.0}
    }


class TestStrategyDAO:
    """Test suite for StrategyDAO."""

    def test_initialization(self, strategy_dao):
        """Test DAO initializes correctly."""
        assert strategy_dao is not None
        assert hasattr(strategy_dao, 'save_strategy_result')

    def test_save_strategy_result(self, strategy_dao, sample_strategy_result):
        """Test saving strategy result to database."""
        success = strategy_dao.save_strategy_result(
            symbol=sample_strategy_result["symbol"],
            strategy_name=sample_strategy_result["strategy_name"],
            current_price=sample_strategy_result["current_price"],
            statistics=sample_strategy_result["statistics"],
            indicators=sample_strategy_result["indicators"],
            signals=sample_strategy_result["signals"],
            action=sample_strategy_result["action"],
            confidence=sample_strategy_result["confidence"],
            reason=sample_strategy_result["reason"],
            current_state=sample_strategy_result["current_state"],
            parameters=sample_strategy_result["parameters"]
        )

        assert success is True

    def test_get_latest_signal(self, strategy_dao, sample_strategy_result):
        """Test retrieving latest signal for a symbol."""
        # Save a result first
        strategy_dao.save_strategy_result(
            symbol=sample_strategy_result["symbol"],
            strategy_name=sample_strategy_result["strategy_name"],
            current_price=sample_strategy_result["current_price"],
            statistics=sample_strategy_result["statistics"],
            indicators=sample_strategy_result["indicators"],
            signals=sample_strategy_result["signals"],
            action=sample_strategy_result["action"],
            confidence=sample_strategy_result["confidence"],
            reason=sample_strategy_result["reason"],
            current_state=sample_strategy_result["current_state"],
            parameters=sample_strategy_result["parameters"]
        )

        # Retrieve it
        latest = strategy_dao.get_latest_signal(
            sample_strategy_result["symbol"],
            sample_strategy_result["strategy_name"]
        )

        assert latest is not None
        assert latest["action"] == "hold"
        assert float(latest["confidence"]) == 0.65
        assert float(latest["statistics"]["vwap"]) == 149.80

    def test_get_recent_signals(self, strategy_dao, sample_strategy_result):
        """Test retrieving recent signals."""
        # Save multiple results
        for i in range(3):
            strategy_dao.save_strategy_result(
                symbol=sample_strategy_result["symbol"],
                strategy_name=sample_strategy_result["strategy_name"],
                current_price=150.0 + i,
                statistics=sample_strategy_result["statistics"],
                indicators=sample_strategy_result["indicators"],
                signals=sample_strategy_result["signals"],
                action=sample_strategy_result["action"],
                confidence=0.6 + i * 0.1,
                reason=sample_strategy_result["reason"],
                current_state=sample_strategy_result["current_state"],
                parameters=sample_strategy_result["parameters"]
            )

        # Retrieve them
        recent = strategy_dao.get_recent_signals(
            sample_strategy_result["symbol"],
            sample_strategy_result["strategy_name"],
            limit=5
        )

        assert len(recent) >= 3

    def test_get_actionable_signals(self, strategy_dao):
        """Test retrieving high-confidence actionable signals."""
        # Save high-confidence buy signal
        strategy_dao.save_strategy_result(
            symbol="BUY_TEST",
            strategy_name="mean-reversion-test",
            current_price=100.0,
            statistics={"mean": 105.0, "std_dev": 2.0, "z_score": -2.5},
            indicators={},
            signals={"overall_signal": "strong_buy"},
            action="buy",
            confidence=0.85,
            reason="Strong oversold",
            current_state="oversold",
            parameters={}
        )

        # Retrieve actionable signals
        actionable = strategy_dao.get_actionable_signals(min_confidence=0.7)

        assert len(actionable) > 0
        buy_signals = actionable[actionable['action'] == 'buy']
        assert len(buy_signals) > 0

    def test_get_strategy_performance(self, strategy_dao, sample_strategy_result):
        """Test retrieving strategy performance metrics."""
        # Save some results
        for action in ["buy", "sell", "hold"]:
            strategy_dao.save_strategy_result(
                symbol="PERF_TEST",
                strategy_name="mean-reversion-test",
                current_price=150.0,
                statistics=sample_strategy_result["statistics"],
                indicators=sample_strategy_result["indicators"],
                signals=sample_strategy_result["signals"],
                action=action,
                confidence=0.7,
                reason=f"Test {action}",
                current_state="neutral",
                parameters=sample_strategy_result["parameters"]
            )

        # Get performance
        perf = strategy_dao.get_strategy_performance(
            "mean-reversion-test",
            days=30
        )

        assert perf is not None
        assert "total_signals" in perf
        assert perf["total_signals"] >= 3
        assert "buy_signals" in perf
        assert "sell_signals" in perf
        assert "hold_signals" in perf


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
