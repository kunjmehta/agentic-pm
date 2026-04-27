"""Unit tests for unified middleware.

Tests market hours, portfolio guards, tracing, and performance tracking.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.common.core.middleware import (
    ToolTracingCallback,
    MarketHoursGuardMiddleware,
    PortfolioGuardMiddleware,
    TracingMiddleware,
    PrettifyMiddleware,
    create_middleware_stack
)


class TestToolTracingCallback:
    """Test ToolTracingCallback with performance tracking."""

    def test_tool_execution_timing(self):
        """Test that tool execution times are captured."""
        callback = ToolTracingCallback()

        # Simulate tool execution
        callback.on_tool_start({"name": "test_tool"}, "test input")
        time.sleep(0.05)  # 50ms delay
        callback.on_tool_end("test output")

        timings = callback.get_tool_timings()

        assert len(timings) == 1
        assert timings[0]["tool"] == "test_tool"
        assert "duration_ms" in timings[0]
        assert timings[0]["duration_ms"] >= 40  # Should be at least 40ms
        assert timings[0]["status"] == "success"

    def test_tool_error_timing(self):
        """Test that tool errors are captured with timing."""
        callback = ToolTracingCallback()

        callback.on_tool_start({"name": "failing_tool"}, "test input")
        time.sleep(0.02)  # 20ms delay
        callback.on_tool_error(Exception("Test error"))

        timings = callback.get_tool_timings()

        assert len(timings) == 1
        assert timings[0]["tool"] == "failing_tool"
        assert "duration_ms" in timings[0]
        assert timings[0]["status"] == "error"
        assert "error" in timings[0]

    def test_multiple_tools(self):
        """Test tracking multiple tool executions."""
        callback = ToolTracingCallback()

        # Execute three tools
        for i in range(3):
            callback.on_tool_start({"name": f"tool_{i}"}, f"input_{i}")
            time.sleep(0.01)
            callback.on_tool_end(f"output_{i}")

        timings = callback.get_tool_timings()

        assert len(timings) == 3
        for i, timing in enumerate(timings):
            assert timing["tool"] == f"tool_{i}"
            assert timing["status"] == "success"
            assert "duration_ms" in timing

    def test_reset(self):
        """Test that reset clears all timings."""
        callback = ToolTracingCallback()

        callback.on_tool_start({"name": "test_tool"}, "input")
        callback.on_tool_end("output")

        assert len(callback.get_tool_timings()) == 1

        callback.reset()
        assert len(callback.get_tool_timings()) == 0


class TestMarketHoursGuardMiddleware:
    """Test MarketHoursGuardMiddleware."""

    def test_backtest_mode_bypasses_check(self):
        """Test that backtest mode bypasses market hours check."""
        guard = MarketHoursGuardMiddleware(backtest_mode=True)
        result = guard.before_agent({}, None)
        assert result is None  # Should allow execution

    @patch('src.common.core.middleware.agent_middleware.datetime')
    def test_market_open_allows_execution(self, mock_datetime):
        """Test that execution is allowed during market hours."""
        # Mock weekday at 2 PM ET
        import pytz
        eastern = pytz.timezone('America/New_York')
        mock_now = datetime(2026, 2, 25, 14, 0, 0, tzinfo=eastern)  # Tuesday 2 PM

        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        guard = MarketHoursGuardMiddleware(backtest_mode=False)

        # Should not raise
        result = guard.before_agent({}, None)
        assert result is None

    @patch('src.common.core.middleware.agent_middleware.datetime')
    def test_market_closed_blocks_execution(self, mock_datetime):
        """Test that execution is blocked outside market hours."""
        # Mock weekday at 6 PM ET (after close)
        import pytz
        eastern = pytz.timezone('America/New_York')
        mock_now = datetime(2026, 2, 25, 18, 0, 0, tzinfo=eastern)

        mock_datetime.now.return_value = mock_now

        guard = MarketHoursGuardMiddleware(backtest_mode=False)

        with pytest.raises(RuntimeError, match="Market is CLOSED"):
            guard.before_agent({}, None)


class TestPortfolioGuardMiddleware:
    """Test PortfolioGuardMiddleware."""

    def test_backtest_mode_bypasses_check(self):
        """Test that backtest mode bypasses portfolio guard."""
        guard = PortfolioGuardMiddleware(backtest_mode=True)
        result = guard.before_agent({}, None)
        assert result is None

    @patch('src.common.dao.PortfolioDAO')
    def test_healthy_portfolio_allows_execution(self, mock_dao_class):
        """Test that healthy portfolio allows execution."""
        # Mock DAO
        mock_dao = MagicMock()
        mock_dao.get_latest_snapshot.return_value = {
            "daily_pnl_percent": -0.02  # -2% loss (within limit)
        }
        mock_dao.get_risk_parameters.return_value = {
            "daily_loss_limit": {"value": 0.05}  # 5% limit
        }
        mock_dao_class.return_value = mock_dao

        guard = PortfolioGuardMiddleware(backtest_mode=False)
        result = guard.before_agent({}, None)

        assert result is None
        mock_dao.close.assert_called_once()

    @patch('src.common.dao.PortfolioDAO')
    def test_loss_limit_exceeded_blocks_execution(self, mock_dao_class):
        """Test that exceeding loss limit blocks execution."""
        # Mock DAO
        mock_dao = MagicMock()
        mock_dao.get_latest_snapshot.return_value = {
            "daily_pnl_percent": -0.06  # -6% loss (exceeds limit)
        }
        mock_dao.get_risk_parameters.return_value = {
            "daily_loss_limit": {"value": 0.05}  # 5% limit
        }
        mock_dao_class.return_value = mock_dao

        guard = PortfolioGuardMiddleware(backtest_mode=False)

        with pytest.raises(RuntimeError, match="Daily loss limit exceeded"):
            guard.before_agent({}, None)

        mock_dao.close.assert_called_once()

    @patch('src.common.dao.PortfolioDAO')
    def test_dao_unavailable_allows_execution(self, mock_dao_class):
        """Test that DAO failure doesn't block execution."""
        # Mock DAO to raise exception
        mock_dao_class.side_effect = Exception("DAO unavailable")

        guard = PortfolioGuardMiddleware(backtest_mode=False)

        # Should not raise - logs warning but continues
        result = guard.before_agent({}, None)
        assert result is None


class TestTracingMiddleware:
    """Test TracingMiddleware."""

    def test_before_model_logs_message_count(self):
        """Test that before_model logs message count."""
        tracer = TracingMiddleware()

        state = {
            "messages": [
                type('Message', (), {'type': 'user', 'content': 'Test'})(),
                type('Message', (), {'type': 'assistant', 'content': 'Response'})()
            ]
        }

        result = tracer.before_model(state, None)
        assert result is None  # Should not modify state

    def test_after_model_extracts_tool_calls(self):
        """Test that after_model extracts tool calls from messages."""
        tracer = TracingMiddleware()

        # Mock message with tool calls
        mock_message = type('Message', (), {
            'type': 'assistant',
            'content': 'Using tools',
            'tool_calls': [
                {
                    "id": "call_123",
                    "name": "test_tool",
                    "args": {"param": "value"}
                }
            ]
        })()

        state = {"messages": [mock_message]}
        result = tracer.after_model(state, None)

        assert result is None
        assert len(tracer.current_tool_calls) == 1
        assert tracer.current_tool_calls[0]["name"] == "test_tool"

    def test_error_handling(self):
        """Test that errors are logged properly."""
        tracer = TracingMiddleware()

        test_error = Exception("Test error")
        result = tracer.on_error({}, None, test_error)

        assert result is None  # Should propagate error


class TestPrettifyMiddleware:
    """Test PrettifyMiddleware."""

    def test_prettify_with_structured_response(self):
        """Test prettification of structured response."""
        prettifier = PrettifyMiddleware()

        state = {
            "structured_response": {
                "status": "success",
                "data": {"value": 123}
            }
        }

        result = prettifier.after_agent(state, None)
        assert result is None  # Should not modify state

    def test_prettify_without_response(self):
        """Test that prettify handles missing response gracefully."""
        prettifier = PrettifyMiddleware()

        state = {}
        result = prettifier.after_agent(state, None)
        assert result is None


class TestCreateMiddlewareStack:
    """Test create_middleware_stack function."""

    def test_quant_stack(self):
        """Test that quant stack has correct middleware."""
        stack = create_middleware_stack(backtest_mode=True, agent_type="quant")

        assert len(stack) == 4
        assert isinstance(stack[1], MarketHoursGuardMiddleware)
        assert isinstance(stack[2], TracingMiddleware)
        assert isinstance(stack[3], PrettifyMiddleware)

    def test_portfolio_stack(self):
        """Test that portfolio stack includes PortfolioGuard."""
        stack = create_middleware_stack(backtest_mode=True, agent_type="portfolio")

        assert len(stack) == 5
        assert isinstance(stack[1], MarketHoursGuardMiddleware)
        assert isinstance(stack[2], PortfolioGuardMiddleware)
        assert isinstance(stack[3], TracingMiddleware)
        assert isinstance(stack[4], PrettifyMiddleware)

    def test_backtest_mode_propagates(self):
        """Test that backtest_mode is passed to guards."""
        stack = create_middleware_stack(backtest_mode=True, agent_type="portfolio")

        # Guards should have backtest_mode=True
        assert stack[1].backtest_mode is True
        assert stack[2].backtest_mode is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
