"""Unit tests for Portfolio DAO.

Tests portfolio snapshots, agent interactions, risk parameters, and thread cleanup.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import tempfile
import os
from datetime import datetime, date, timedelta
from src.common.dao.portfolio_dao import PortfolioDAO


@pytest.fixture
def dao():
    """Create a test PortfolioDAO instance with temporary database."""
    # Get a temporary path without creating the file
    # DuckDB will create the database itself
    db_path = os.path.join(tempfile.gettempdir(), f"test_portfolio_{os.getpid()}.duckdb")

    # Remove if it exists from a previous run
    if os.path.exists(db_path):
        os.remove(db_path)

    dao = PortfolioDAO(db_path=db_path)
    yield dao
    dao.close()

    # Clean up temp file
    if os.path.exists(db_path):
        os.remove(db_path)


class TestPortfolioSnapshots:
    """Test portfolio snapshot methods."""

    def test_save_snapshot(self, dao):
        """Test saving a portfolio snapshot."""
        now = datetime.now()
        rows = dao.save_snapshot(
            timestamp=now,
            equity=100000.0,
            cash=50000.0,
            buying_power=100000.0,
            daily_pnl=1000.0,
            total_pnl=5000.0,
            daily_pnl_percent=0.01,
            long_positions=5,
            short_positions=0,
            snapshot_source="alpaca"
        )
        assert rows == 1

    def test_get_latest_snapshot(self, dao):
        """Test retrieving latest snapshot."""
        # Save two snapshots
        dao.save_snapshot(
            timestamp=datetime.now() - timedelta(days=1),
            equity=99000.0,
            cash=50000.0,
            buying_power=100000.0
        )
        dao.save_snapshot(
            timestamp=datetime.now(),
            equity=100000.0,
            cash=51000.0,
            buying_power=102000.0
        )

        latest = dao.get_latest_snapshot()
        assert latest is not None
        assert latest['equity'] == 100000.0
        assert latest['cash'] == 51000.0

    def test_get_snapshot_history(self, dao):
        """Test retrieving snapshot history."""
        # Save snapshots over 3 days
        for i in range(3):
            dao.save_snapshot(
                timestamp=datetime.now() - timedelta(days=2-i),
                equity=100000.0 + (i * 1000),
                cash=50000.0,
                buying_power=100000.0
            )

        start_date = date.today() - timedelta(days=7)
        end_date = date.today()
        history = dao.get_snapshot_history(start_date, end_date)

        assert len(history) == 3
        # Should be ordered DESC
        assert history.iloc[0]['equity'] == 102000.0


class TestAgentInteractions:
    """Test agent interaction logging methods."""

    def test_save_interaction(self, dao):
        """Test saving an agent interaction."""
        tool_sequence = [
            {"tool": "get_portfolio_status", "executed": True},
            {"tool": "check_portfolio_health", "executed": True}
        ]
        tool_timings = [
            {"tool": "get_portfolio_status", "duration_ms": 150, "status": "success"},
            {"tool": "check_portfolio_health", "duration_ms": 75, "status": "success"}
        ]

        rows = dao.save_interaction(
            thread_id="test-thread-001",
            agent_name="portfolio_manager",
            user_query="What's my portfolio status?",
            tool_sequence=tool_sequence,
            agent_response="Your portfolio is healthy.",
            model_used="gpt-5-mini",
            token_count=450,
            execution_time_ms=225,
            tool_timings=tool_timings,
            delegated_to=None,
            delegation_result=None
        )
        assert rows == 1

    def test_get_interaction_history_by_thread(self, dao):
        """Test retrieving interaction history by thread_id."""
        # Save interactions for two different threads
        for i in range(3):
            dao.save_interaction(
                thread_id="thread-001",
                agent_name="portfolio_manager",
                user_query=f"Query {i}",
                tool_sequence=[],
                agent_response=f"Response {i}",
                model_used="gpt-5-mini"
            )

        dao.save_interaction(
            thread_id="thread-002",
            agent_name="portfolio_manager",
            user_query="Different query",
            tool_sequence=[],
            agent_response="Different response",
            model_used="gpt-5-mini"
        )

        history = dao.get_interaction_history(thread_id="thread-001", limit=10)
        assert len(history) == 3

    def test_get_interaction_history_by_agent(self, dao):
        """Test retrieving interaction history by agent_name."""
        dao.save_interaction(
            thread_id="thread-001",
            agent_name="portfolio_manager",
            user_query="Portfolio query",
            tool_sequence=[],
            agent_response="Portfolio response",
            model_used="gpt-5-mini"
        )
        dao.save_interaction(
            thread_id="thread-001",
            agent_name="quant_analyst",
            user_query="Quant query",
            tool_sequence=[],
            agent_response="Quant response",
            model_used="gpt-5-mini"
        )

        history = dao.get_interaction_history(agent_name="portfolio_manager", limit=10)
        assert len(history) == 1
        assert history[0]['agent_name'] == "portfolio_manager"

    def test_get_performance_stats(self, dao):
        """Test retrieving performance statistics."""
        # Save interactions with varying execution times
        for i in range(3):
            dao.save_interaction(
                thread_id="thread-001",
                agent_name="portfolio_manager",
                user_query=f"Query {i}",
                tool_sequence=[],
                agent_response=f"Response {i}",
                model_used="gpt-5-mini",
                token_count=400 + (i * 50),
                execution_time_ms=200 + (i * 50)
            )

        stats = dao.get_performance_stats("portfolio_manager", days=7)
        assert stats is not None
        assert stats['total_interactions'] == 3
        assert stats['avg_execution_time'] == 250.0  # (200 + 250 + 300) / 3
        assert stats['max_execution_time'] == 300
        assert stats['min_execution_time'] == 200


class TestRiskParameters:
    """Test risk parameter methods."""

    def test_get_risk_parameters(self, dao):
        """Test retrieving all risk parameters."""
        params = dao.get_risk_parameters()
        assert isinstance(params, dict)
        # Should have seed values from schema
        assert 'max_position_size' in params
        assert 'daily_loss_limit' in params

    def test_update_risk_parameter(self, dao):
        """Test updating a risk parameter."""
        new_value = {"value": 2000, "unit": "shares"}
        dao.update_risk_parameter("max_position_size", new_value)

        params = dao.get_risk_parameters()
        assert params['max_position_size'] == new_value

    def test_update_risk_parameter_upsert(self, dao):
        """Test that update_risk_parameter upserts correctly."""
        # First update
        dao.update_risk_parameter("custom_param", {"value": 100})
        params = dao.get_risk_parameters()
        assert params['custom_param'] == {"value": 100}

        # Second update (should upsert)
        dao.update_risk_parameter("custom_param", {"value": 200})
        params = dao.get_risk_parameters()
        assert params['custom_param'] == {"value": 200}


class TestThreadCleanup:
    """Test thread cleanup methods."""

    def test_cleanup_expired_threads_dry_run(self, dao):
        """Test dry run cleanup."""
        result = dao.cleanup_expired_threads(dry_run=True)
        assert result['dry_run'] is True
        assert 'would_delete' in result

    def test_cleanup_expired_threads(self, dao):
        """Test actual cleanup of expired threads."""
        # Save interaction that expires immediately
        past_expiry = datetime.now() - timedelta(days=1)
        dao.save_interaction(
            thread_id="expired-thread",
            agent_name="test_agent",
            user_query="Test query",
            tool_sequence=[],
            agent_response="Test response",
            model_used="gpt-5-mini"
        )

        # Manually update expires_at to past
        dao.execute(
            "UPDATE agent_interactions SET expires_at = ? WHERE thread_id = ?",
            (past_expiry, "expired-thread")
        )

        # Cleanup
        result = dao.cleanup_expired_threads(dry_run=False)
        assert result['deleted'] == 1

    def test_extend_thread_expiry(self, dao):
        """Test extending thread expiration."""
        # Save an interaction
        dao.save_interaction(
            thread_id="extend-thread",
            agent_name="test_agent",
            user_query="Test query",
            tool_sequence=[],
            agent_response="Test response",
            model_used="gpt-5-mini"
        )

        # Extend expiry
        rows = dao.extend_thread_expiry("extend-thread", days=60)
        assert rows == 1

        # Verify expiry was extended
        result = dao.fetch_one(
            "SELECT expires_at FROM agent_interactions WHERE thread_id = ?",
            ("extend-thread",)
        )
        assert result is not None
        # DuckDB returns datetime objects directly, not strings
        expires_at = result['expires_at']
        assert isinstance(expires_at, datetime)

        # Should be ~60 days from now (give or take a few seconds)
        expected_expiry = datetime.now() + timedelta(days=60)
        diff = abs((expires_at - expected_expiry).total_seconds())
        assert diff < 10  # Within 10 seconds


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
