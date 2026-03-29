"""Tests for Backtester agent."""

import pytest
from src.agentic.agents.backtester.backtester import Backtester


def test_backtester_initialization():
    """Test backtester initializes correctly."""
    backtester = Backtester(model="gpt-5-mini")

    assert backtester.model == "gpt-5-mini"
    assert backtester.backtest_mode is True
    assert len(backtester.tools) == 5


def test_backtester_tools_loaded():
    """Test all tools are loaded."""
    backtester = Backtester()

    tool_names = [t.name for t in backtester.tools]

    assert "fetch_backtest_run" in tool_names
    assert "fetch_backtest_trades" in tool_names
    assert "fetch_backtest_performance_history" in tool_names
    assert "fetch_historical_bars_for_backtest" in tool_names
    assert "save_backtest_run_to_db" in tool_names


def test_backtester_invoke_structure():
    """Test invoke returns proper structure (without API call)."""
    backtester = Backtester()

    # This will fail without API key in real test, but structure should be correct
    # For unit tests, would need to mock the agent
    assert hasattr(backtester, 'invoke')
    assert callable(backtester.invoke)
