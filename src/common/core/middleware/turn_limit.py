"""Turn Call Limit Middleware — one call maximum per tool/skill per agent turn.

Two trip-wires:
  1. Loop detection  — a tool name seen for the second time means the agent is
                       looping. Raises TurnLimitReached immediately with
                       reason="loop".
  2. Budget cap      — total unique-tool budget = max_actions_per_turn (defaults
                       to the number of tools registered to the agent). Raises
                       TurnLimitReached with reason="budget" once exhausted.

Skill calls count too: DeepAgents executes skills via the bash tool, which fires
on_tool_start just like any other tool, so a single callback covers both surfaces.

base_agent._invoke_with_middleware catches TurnLimitReached and returns a graceful
short-circuit response to the user.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import threading
from typing import Any, Dict, Optional, Set

from langchain_core.callbacks import BaseCallbackHandler

from src.common.utils import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class TurnLimitReached(Exception):
    """Raised when per-turn execution limit is exceeded or a loop is detected.

    Attributes:
        calls_made: Number of actions taken this turn when limit was hit.
        limit: The configured max_actions_per_turn value.
        reason: "loop" if duplicate tool call detected, "budget" if cap exceeded.
        tool_name: Name of the tool that triggered the limit.
    """

    def __init__(self, calls_made: int, limit: int, reason: str, tool_name: str) -> None:
        self.calls_made = calls_made
        self.limit = limit
        self.reason = reason
        self.tool_name = tool_name
        if reason == "loop":
            msg = (
                f"Loop detected: '{tool_name}' called more than once this turn "
                f"({calls_made} total actions, limit {limit})."
            )
        else:
            msg = (
                f"Per-turn budget exhausted: {calls_made} actions taken "
                f"(max {limit}). Last call: '{tool_name}'."
            )
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Internal LangChain callback
# ---------------------------------------------------------------------------


class _TurnLimitCallback(BaseCallbackHandler):
    """Fires on every on_tool_start event; enforces one-call-per-tool policy.

    Bound to a TurnCallLimitMiddleware instance so they share the same state.
    raise_error = True makes LangChain propagate TurnLimitReached instead of
    swallowing it as a callback warning.
    """

    raise_error: bool = True  # tell LangChain to propagate our exceptions

    def __init__(self, middleware: "TurnCallLimitMiddleware") -> None:
        """Initialize callback bound to the given middleware.

        Args:
            middleware: Parent TurnCallLimitMiddleware that owns call tracking.
        """
        super().__init__()
        self._mw = middleware

    def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        """Check for loops and budget; raise TurnLimitReached if violated.

        Called by LangChain before every tool/skill execution. Protected by a
        per-middleware lock so parallel tool dispatches don't race on the counter.

        Args:
            serialized: Tool metadata dict (contains "name").
            input_str: Input string passed to the tool.
            **kwargs: Additional LangChain callback arguments.

        Raises:
            TurnLimitReached: On duplicate tool call (loop) or budget exceeded.
        """
        tool_name = serialized.get("name", "unknown")

        with self._mw._lock:
            self._mw._actions_this_turn += 1
            count = self._mw._actions_this_turn
            limit = self._mw.max_actions_per_turn

            # Trip-wire 1: loop detection — same tool called a second time
            if tool_name in self._mw._called_tools:
                logger.warning(
                    f"[TURN LIMIT] Loop detected — '{tool_name}' called again "
                    f"(action {count}/{limit}). Short-circuiting."
                )
                raise TurnLimitReached(
                    calls_made=count,
                    limit=limit,
                    reason="loop",
                    tool_name=tool_name,
                )

            self._mw._called_tools.add(tool_name)
            logger.info(f"[TURN LIMIT] Action {count}/{limit}: {tool_name}")

            # Trip-wire 2: budget cap — total unique calls exceeded
            if count > limit:
                logger.warning(
                    f"[TURN LIMIT] Budget exceeded on '{tool_name}' "
                    f"({count}/{limit}). Short-circuiting."
                )
                raise TurnLimitReached(
                    calls_made=count,
                    limit=limit,
                    reason="budget",
                    tool_name=tool_name,
                )


# ---------------------------------------------------------------------------
# Middleware class
# ---------------------------------------------------------------------------


class TurnCallLimitMiddleware:
    """Middleware enforcing one call per tool/skill per agent turn.

    Policy:
    - Each unique tool/skill name may be called at most once per turn.
    - A second call to the same tool triggers loop detection and immediate
      short-circuit regardless of the total budget.
    - Total calls are also capped at max_actions_per_turn as a safety net.
    - base_agent._invoke_with_middleware catches TurnLimitReached and returns
      a graceful response instead of propagating the exception.

    Usage:
        Instantiated automatically by create_middleware_stack().
        Pass max_actions_per_turn to control the budget cap.
        For the graph portfolio agent, pass len(tools) so the cap equals the
        number of registered tools (one call each, declare_dispatch last).
    """

    def __init__(self, max_actions_per_turn: int = 6) -> None:
        """Initialize TurnCallLimitMiddleware.

        Args:
            max_actions_per_turn: Maximum unique tool/skill calls per turn
                before short-circuiting (default: 6).
        """
        self.max_actions_per_turn = max_actions_per_turn
        self._actions_this_turn: int = 0
        self._called_tools: Set[str] = set()

    def reset(self) -> None:
        """Reset all per-turn tracking state."""
        self._actions_this_turn = 0
        self._called_tools = set()
        logger.debug("[TURN LIMIT] State reset for new turn.")

    def before_agent(self, state: dict, runtime: Any) -> Optional[dict]:
        """Reset tracking state at the start of each agent invocation.

        Args:
            state: Current agent state.
            runtime: Agent runtime context.

        Returns:
            None to continue execution unchanged.
        """
        self.reset()
        logger.info(
            f"[TURN LIMIT] Enabled — max {self.max_actions_per_turn} unique "
            f"tool calls per turn; duplicate calls short-circuit immediately."
        )
        return None

    def get_callback(self) -> _TurnLimitCallback:
        """Return a LangChain callback bound to this middleware instance.

        The callback is injected into agent.invoke() via config["callbacks"]
        so it receives all on_tool_start events during agent execution.

        Returns:
            _TurnLimitCallback instance sharing this middleware's state.
        """
        return _TurnLimitCallback(self)

    def after_agent(self, state: dict, runtime: Any) -> Optional[dict]:
        """Log per-turn summary after the agent completes normally.

        Args:
            state: Final agent state.
            runtime: Agent runtime context.

        Returns:
            None (state unchanged).
        """
        logger.info(
            f"[TURN LIMIT] Turn complete — {self._actions_this_turn}/"
            f"{self.max_actions_per_turn} actions, "
            f"tools called: {sorted(self._called_tools)}"
        )
        return None


# ---------------------------------------------------------------------------
# Main block — functional self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("TurnCallLimitMiddleware Self-Test")
    print("=" * 60)

    # Test 1: before_agent resets all state
    print("\n[1/5] before_agent resets state...")
    mw = TurnCallLimitMiddleware(max_actions_per_turn=6)
    mw._actions_this_turn = 99
    mw._called_tools = {"stale_tool"}
    mw.before_agent({}, None)
    assert mw._actions_this_turn == 0, "Counter should be 0"
    assert mw._called_tools == set(), "Called-tools set should be empty"
    print("[OK] All state reset to zero")

    # Test 2: unique calls within budget proceed without error
    print("\n[2/5] Three unique tools within budget...")
    mw2 = TurnCallLimitMiddleware(max_actions_per_turn=6)
    cb = mw2.get_callback()
    cb.on_tool_start({"name": "get_portfolio_status"}, "{}")
    cb.on_tool_start({"name": "get_positions_summary"}, "{}")
    cb.on_tool_start({"name": "check_portfolio_health"}, "{}")
    assert mw2._actions_this_turn == 3
    assert mw2._called_tools == {
        "get_portfolio_status", "get_positions_summary", "check_portfolio_health"
    }
    print("[OK] 3 unique calls, no exception")

    # Test 3: duplicate call raises TurnLimitReached(reason="loop")
    print("\n[3/5] Duplicate tool call → loop detection...")
    try:
        cb.on_tool_start({"name": "get_portfolio_status"}, "{}")
        print("[FAIL] Should have raised TurnLimitReached")
    except TurnLimitReached as e:
        assert e.reason == "loop", f"Expected reason='loop', got '{e.reason}'"
        assert e.tool_name == "get_portfolio_status"
        print(f"[OK] Loop detected: {e}")

    # Test 4: budget cap raises TurnLimitReached(reason="budget")
    print("\n[4/5] Budget cap exceeded → reason='budget'...")
    mw4 = TurnCallLimitMiddleware(max_actions_per_turn=2)
    cb4 = mw4.get_callback()
    cb4.on_tool_start({"name": "tool_a"}, "{}")
    cb4.on_tool_start({"name": "tool_b"}, "{}")
    try:
        cb4.on_tool_start({"name": "tool_c"}, "{}")
        print("[FAIL] Should have raised TurnLimitReached")
    except TurnLimitReached as e:
        assert e.reason == "budget", f"Expected reason='budget', got '{e.reason}'"
        assert e.tool_name == "tool_c"
        print(f"[OK] Budget exceeded: {e}")

    # Test 5: after_agent returns None (no state mutation)
    print("\n[5/5] after_agent logging...")
    mw5 = TurnCallLimitMiddleware(max_actions_per_turn=6)
    mw5._actions_this_turn = 2
    mw5._called_tools = {"get_portfolio_status", "declare_dispatch"}
    result = mw5.after_agent({}, None)
    assert result is None
    print("[OK] after_agent returned None")

    print("\n" + "=" * 60)
    print("All self-tests passed!")
    print("=" * 60)
