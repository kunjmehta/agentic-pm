"""Unit tests for TurnCallLimitMiddleware.

Tests cover:
1. Callback raises TurnLimitReached after the configured limit.
2. Middleware resets counter on before_agent.
3. base_agent._invoke_with_middleware returns a graceful pause response.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from unittest.mock import MagicMock, patch
import pytest

from src.common.core.middleware.turn_limit import (
    TurnCallLimitMiddleware,
    TurnLimitReached,
    _TurnLimitCallback,
)


# ---------------------------------------------------------------------------
# Test 1: callback raises after limit
# ---------------------------------------------------------------------------


def test_callback_raises_after_limit():
    """Third on_tool_start raises TurnLimitReached when limit=2."""
    mw = TurnCallLimitMiddleware(max_actions_per_turn=2)
    cb = mw.get_callback()

    # First two calls should not raise
    cb.on_tool_start({"name": "get_portfolio_status"}, "{}")
    cb.on_tool_start({"name": "check_portfolio_health"}, "{}")
    assert mw._actions_this_turn == 2

    # Third call must raise
    with pytest.raises(TurnLimitReached) as exc_info:
        cb.on_tool_start({"name": "delegate_to_quant_analyst"}, "{}")

    err = exc_info.value
    assert err.calls_made == 3
    assert err.limit == 2


def test_callback_does_not_raise_within_limit():
    """Exactly N calls should succeed with no exception for limit=N."""
    mw = TurnCallLimitMiddleware(max_actions_per_turn=5)
    cb = mw.get_callback()

    for i in range(5):
        cb.on_tool_start({"name": f"tool_{i}"}, "{}")

    assert mw._actions_this_turn == 5  # no exception, all 5 allowed


# ---------------------------------------------------------------------------
# Test 2: middleware resets counter on before_agent
# ---------------------------------------------------------------------------


def test_middleware_resets_on_before_agent():
    """before_agent resets the action counter to 0."""
    mw = TurnCallLimitMiddleware(max_actions_per_turn=2)

    # Simulate previous turn leaving counter dirty
    mw._actions_this_turn = 99

    mw.before_agent({}, None)

    assert mw._actions_this_turn == 0


def test_middleware_reset_allows_new_turn():
    """After reset, another full set of actions can proceed without error."""
    mw = TurnCallLimitMiddleware(max_actions_per_turn=2)
    cb = mw.get_callback()

    # Exhaust first turn
    cb.on_tool_start({"name": "tool_a"}, "{}")
    cb.on_tool_start({"name": "tool_b"}, "{}")

    # Simulate new turn
    mw.before_agent({}, None)
    cb2 = mw.get_callback()  # fresh callback bound to same mw

    # Should succeed again
    cb2.on_tool_start({"name": "tool_a"}, "{}")
    cb2.on_tool_start({"name": "tool_b"}, "{}")
    assert mw._actions_this_turn == 2


# ---------------------------------------------------------------------------
# Test 3: base_agent returns pause response on TurnLimitReached
# ---------------------------------------------------------------------------


def test_base_agent_returns_pause_response_on_turn_limit():
    """_invoke_with_middleware catches TurnLimitReached and returns pause dict."""
    from src.agentic.agents.base_agent import BaseAgent

    # Minimal concrete subclass
    class _TestAgent(BaseAgent):
        def __init__(self):
            self.model = "gpt-5-mini"
            self.middleware_stack = [TurnCallLimitMiddleware(max_actions_per_turn=2)]
            self._agent_instance = None

        def _get_agent(self):
            if self._agent_instance is None:
                mock_agent = MagicMock()
                # Simulate agent.invoke raising TurnLimitReached on 3rd tool call
                mock_agent.invoke.side_effect = TurnLimitReached(calls_made=3, limit=2)
                self._agent_instance = mock_agent
            return self._agent_instance

    agent = _TestAgent()
    state = {"messages": [{"role": "user", "content": "analyze AAPL"}]}
    config = {"configurable": {"thread_id": "test-001"}}

    result = agent._invoke_with_middleware(state, config)

    assert "messages" in result
    last_msg = result["messages"][-1]
    content = last_msg["content"] if isinstance(last_msg, dict) else str(last_msg)
    assert "per-turn limit" in content
    assert "continue" in content.lower()


def test_base_agent_propagates_non_turn_limit_errors():
    """_invoke_with_middleware re-raises non-TurnLimitReached exceptions."""
    from src.agentic.agents.base_agent import BaseAgent

    class _ErrorAgent(BaseAgent):
        def __init__(self):
            self.model = "gpt-5-mini"
            self.middleware_stack = []
            self._agent_instance = None

        def _get_agent(self):
            if self._agent_instance is None:
                mock_agent = MagicMock()
                mock_agent.invoke.side_effect = RuntimeError("API error")
                self._agent_instance = mock_agent
            return self._agent_instance

    agent = _ErrorAgent()
    state = {"messages": [{"role": "user", "content": "test"}]}
    config = {"configurable": {"thread_id": "test-002"}}

    with pytest.raises(RuntimeError, match="API error"):
        agent._invoke_with_middleware(state, config)


# ---------------------------------------------------------------------------
# Main block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest", __file__, "-v"],
        capture_output=False
    )
    sys.exit(result.returncode)
