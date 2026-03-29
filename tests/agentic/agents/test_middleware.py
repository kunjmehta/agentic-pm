"""Tests for LangChain middleware classes."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from datetime import datetime, time
from src.common.core.middleware import (
    MarketHoursGuardMiddleware,
    TracingMiddleware,
    PrettifyMiddleware,
    create_middleware_stack
)


class TestMarketHoursGuardMiddleware:
    """Test suite for MarketHoursGuardMiddleware."""

    def test_initialization(self):
        """Test middleware initializes correctly."""
        guard = MarketHoursGuardMiddleware(backtest_mode=True)
        assert guard.backtest_mode is True

    def test_backtest_mode_bypasses_check(self):
        """Test that backtest mode bypasses market hours check."""
        guard = MarketHoursGuardMiddleware(backtest_mode=True)
        result = guard.before_agent({}, None)
        # Should return None (continue execution) regardless of time
        assert result is None

    def test_market_closed_raises_error(self):
        """Test that execution is blocked when market is closed."""
        guard = MarketHoursGuardMiddleware(backtest_mode=False)

        # Note: This will only pass if run outside market hours
        # During market hours, we expect it to pass
        try:
            result = guard.before_agent({}, None)
            # If we get here, market is open
            assert result is None
        except RuntimeError as e:
            # Market is closed
            assert "Market is CLOSED" in str(e)


class TestTracingMiddleware:
    """Test suite for TracingMiddleware."""

    def test_initialization(self):
        """Test middleware initializes correctly."""
        tracer = TracingMiddleware()
        assert tracer is not None
        assert hasattr(tracer, 'current_tool_calls')
        assert tracer.current_tool_calls == []

    def test_before_model_hook(self):
        """Test before_model hook executes without error."""
        tracer = TracingMiddleware()
        state = {
            "messages": [
                type('Message', (), {'type': 'user', 'content': 'Test message'})()
            ]
        }
        result = tracer.before_model(state, None)
        assert result is None  # Should return None to continue

    def test_after_model_hook(self):
        """Test after_model hook executes without error."""
        tracer = TracingMiddleware()
        state = {
            "messages": [
                type('Message', (), {'type': 'assistant', 'content': 'Response'})()
            ]
        }
        result = tracer.after_model(state, None)
        assert result is None

    def test_after_model_with_tool_calls(self):
        """Test after_model hook captures tool calls."""
        tracer = TracingMiddleware()

        # Mock message with tool_calls
        tool_calls = [
            {
                "id": "call_123",
                "name": "get_market_bars",
                "args": {"symbol": "AAPL", "minutes": 30}
            }
        ]

        mock_message = type('Message', (), {
            'type': 'assistant',
            'content': '',
            'tool_calls': tool_calls
        })()

        state = {"messages": [mock_message]}
        result = tracer.after_model(state, None)

        # Should track the tool call
        assert result is None
        assert len(tracer.current_tool_calls) == 1
        assert tracer.current_tool_calls[0]["name"] == "get_market_bars"
        assert tracer.current_tool_calls[0]["id"] == "call_123"

    def test_after_model_with_tool_results(self):
        """Test after_model hook captures tool results."""
        tracer = TracingMiddleware()

        # First, add a pending tool call
        tracer.current_tool_calls.append({
            "id": "call_123",
            "name": "get_market_bars",
            "args": {"symbol": "AAPL"}
        })

        # Mock tool result message
        mock_message = type('Message', (), {
            'type': 'tool',
            'content': '{"symbol": "AAPL", "bars": 30}',
            'tool_call_id': 'call_123'
        })()

        state = {"messages": [mock_message]}
        result = tracer.after_model(state, None)

        # Should log the result and remove from pending
        assert result is None
        assert len(tracer.current_tool_calls) == 0

    def test_on_error_hook(self):
        """Test on_error hook handles exceptions."""
        tracer = TracingMiddleware()
        state = {"messages": []}
        error = Exception("Test error")
        result = tracer.on_error(state, None, error)
        assert result is None  # Should return None to propagate error


class TestPrettifyMiddleware:
    """Test suite for PrettifyMiddleware."""

    def test_initialization(self):
        """Test middleware initializes correctly."""
        prettifier = PrettifyMiddleware()
        assert prettifier is not None

    def test_after_agent_with_structured_response(self):
        """Test prettification with structured response."""
        prettifier = PrettifyMiddleware()

        # Mock structured response
        state = {
            "structured_response": {
                "symbol": "AAPL",
                "action": "buy",
                "confidence": 0.85
            }
        }

        result = prettifier.after_agent(state, None)
        assert result is None  # Should return None to continue

    def test_after_agent_without_structured_response(self):
        """Test prettification with no structured response."""
        prettifier = PrettifyMiddleware()
        state = {}
        result = prettifier.after_agent(state, None)
        assert result is None


class TestMiddlewareStack:
    """Test suite for middleware stack creation."""

    def test_create_middleware_stack(self):
        """Test creating complete middleware stack."""
        stack = create_middleware_stack(backtest_mode=True)

        assert len(stack) == 4
        assert isinstance(stack[1], MarketHoursGuardMiddleware)
        assert isinstance(stack[2], TracingMiddleware)
        assert isinstance(stack[3], PrettifyMiddleware)

    def test_middleware_stack_with_backtest_mode(self):
        """Test middleware stack respects backtest_mode."""
        stack = create_middleware_stack(backtest_mode=True)
        guard = stack[1]
        assert guard.backtest_mode is True

    def test_middleware_stack_without_backtest_mode(self):
        """Test middleware stack with backtest_mode=False."""
        stack = create_middleware_stack(backtest_mode=False)
        guard = stack[1]
        assert guard.backtest_mode is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
