"""Loop prevention middleware.

Detects and halts runaway agent loops by enforcing per-tool and total
tool-call limits within a single agent invocation.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from collections import defaultdict
from typing import Any, Optional

from src.common.utils import get_logger

logger = get_logger(__name__)


class LoopPreventionMiddleware:
    """Middleware that prevents infinite agent loops.

    Enforces two independent limits per agent invocation:
    - Per-tool limit: max calls to any single tool name.
    - Total limit: max tool calls across all tools.

    Counters reset at the start of each invocation via before_agent.
    When disabled (enabled=False), all calls pass through without tracking.
    """

    def __init__(
        self,
        max_iterations_per_tool: int = 2,
        max_total_iterations: int = 10,
        enabled: bool = True,
    ):
        """Initialize loop prevention middleware.

        Args:
            max_iterations_per_tool: Max calls allowed for any single tool per run.
            max_total_iterations: Max total tool calls allowed per run.
            enabled: If False, bypass all checks (no tracking).
        """
        self.max_iterations_per_tool = max_iterations_per_tool
        self.max_total_iterations = max_total_iterations
        self.enabled = enabled
        self.tool_call_counts: defaultdict = defaultdict(int)
        self.total_calls: int = 0

    def before_agent(self, state: dict, runtime: Any) -> Optional[dict]:
        """Reset counters at the start of each agent invocation.

        Args:
            state: Current agent state.
            runtime: Agent runtime context.

        Returns:
            None to continue execution.
        """
        self.tool_call_counts = defaultdict(int)
        self.total_calls = 0
        return None

    def on_tool_start(self, tool_name: str, args: dict) -> None:
        """Check limits before allowing a tool call.

        Total-limit check runs before incrementing; per-tool check runs after.

        Args:
            tool_name: Name of the tool being invoked.
            args: Arguments passed to the tool.

        Raises:
            RuntimeError: If the total or per-tool call limit is exceeded.
        """
        if not self.enabled:
            return

        # Check total limit BEFORE incrementing
        if self.total_calls >= self.max_total_iterations:
            raise RuntimeError(
                f"Too many tool calls: {self.total_calls} total "
                f"(limit: {self.max_total_iterations})"
            )

        self.tool_call_counts[tool_name] += 1
        self.total_calls += 1

        # Check per-tool limit AFTER incrementing
        if self.tool_call_counts[tool_name] > self.max_iterations_per_tool:
            raise RuntimeError(
                f"Loop detected: {tool_name} called "
                f"{self.tool_call_counts[tool_name]} times "
                f"(limit: {self.max_iterations_per_tool})"
            )


if __name__ == "__main__":
    print("=" * 60)
    print("LoopPreventionMiddleware Smoke Test")
    print("=" * 60)

    # Per-tool limit
    mw = LoopPreventionMiddleware(max_iterations_per_tool=2, max_total_iterations=10)
    mw.before_agent({}, None)
    mw.on_tool_start("fetch_data", {})
    assert mw.tool_call_counts["fetch_data"] == 1
    mw.on_tool_start("fetch_data", {})
    assert mw.tool_call_counts["fetch_data"] == 2
    try:
        mw.on_tool_start("fetch_data", {})
        assert False, "should have raised"
    except RuntimeError as exc:
        assert "Loop detected" in str(exc)
    print("[OK] per-tool limit raises on 3rd call")

    # Total limit
    mw2 = LoopPreventionMiddleware(max_iterations_per_tool=5, max_total_iterations=3)
    mw2.before_agent({}, None)
    mw2.on_tool_start("a", {})
    mw2.on_tool_start("b", {})
    mw2.on_tool_start("c", {})
    assert mw2.total_calls == 3
    try:
        mw2.on_tool_start("d", {})
        assert False, "should have raised"
    except RuntimeError as exc:
        assert "Too many tool calls" in str(exc)
    print("[OK] total limit raises on 4th call")

    # Disabled
    mw3 = LoopPreventionMiddleware(max_iterations_per_tool=1, enabled=False)
    mw3.before_agent({}, None)
    for _ in range(10):
        mw3.on_tool_start("test_tool", {})
    assert mw3.tool_call_counts["test_tool"] == 0
    print("[OK] disabled mode: no tracking, no raises")

    # Reset
    mw4 = LoopPreventionMiddleware(max_iterations_per_tool=2)
    mw4.before_agent({}, None)
    mw4.on_tool_start("fetch_data", {})
    mw4.on_tool_start("fetch_data", {})
    assert mw4.tool_call_counts["fetch_data"] == 2
    mw4.before_agent({}, None)
    assert mw4.tool_call_counts["fetch_data"] == 0
    assert mw4.total_calls == 0
    print("[OK] before_agent resets counters")

    print("\n[ALL OK] LoopPreventionMiddleware smoke test complete")
