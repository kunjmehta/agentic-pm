"""Loop Prevention Middleware - Prevents infinite agent loops.

Tracks tool calls and stops execution if:
1. Same tool called more than max_iterations times
2. Total iterations exceed max_total_iterations
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Any, Optional, Dict
from collections import defaultdict
from src.common.utils import get_logger

logger = get_logger(__name__)


class LoopPreventionMiddleware:
    """Prevent infinite loops by limiting tool call iterations.

    Tracks:
    - How many times each tool is called
    - Total number of tool calls
    - Raises exception if limits exceeded
    """

    def __init__(
        self,
        max_iterations_per_tool: int = 2,
        max_total_iterations: int = 10,
        enabled: bool = True
    ):
        """Initialize loop prevention.

        Args:
            max_iterations_per_tool: Max times a single tool can be called (default: 2)
            max_total_iterations: Max total tool calls allowed (default: 10)
            enabled: Whether loop prevention is active (default: True)
        """
        self.max_iterations_per_tool = max_iterations_per_tool
        self.max_total_iterations = max_total_iterations
        self.enabled = enabled

        # Track calls per invocation
        self.tool_call_counts = defaultdict(int)
        self.total_calls = 0
        self.last_tool = None

    def reset(self):
        """Reset counters for new invocation."""
        self.tool_call_counts.clear()
        self.total_calls = 0
        self.last_tool = None
        logger.debug("Loop prevention counters reset")

    def before_agent(self, state: dict, runtime: Any) -> Optional[dict]:
        """Called before agent execution - reset counters.

        Args:
            state: Agent input state
            runtime: Agent runtime context

        Returns:
            Modified state or None
        """
        if not self.enabled:
            return state

        # Reset counters for new agent invocation
        self.reset()
        logger.info(f"[LOOP GUARD] Enabled - Max {self.max_iterations_per_tool} per tool, {self.max_total_iterations} total")
        return state

    def on_tool_start(self, tool_name: str, tool_input: Any) -> None:
        """Track tool call and check limits.

        Args:
            tool_name: Name of the tool being called
            tool_input: Input to the tool

        Raises:
            RuntimeError: If iteration limits exceeded
        """
        if not self.enabled:
            return

        self.total_calls += 1
        self.tool_call_counts[tool_name] += 1

        logger.info(
            f"[LOOP GUARD] Tool call: {tool_name} "
            f"(#{self.tool_call_counts[tool_name]}, "
            f"total: {self.total_calls}/{self.max_total_iterations})"
        )

        # Check per-tool limit
        if self.tool_call_counts[tool_name] > self.max_iterations_per_tool:
            error_msg = (
                f"Loop detected: Tool '{tool_name}' called "
                f"{self.tool_call_counts[tool_name]} times "
                f"(max: {self.max_iterations_per_tool}). "
                f"Agent is stuck in a loop."
            )
            logger.error(f"[LOOP GUARD] {error_msg}")
            raise RuntimeError(error_msg)

        # Check total limit
        if self.total_calls > self.max_total_iterations:
            error_msg = (
                f"Too many tool calls: {self.total_calls} "
                f"(max: {self.max_total_iterations}). "
                f"Agent exceeded iteration limit."
            )
            logger.error(f"[LOOP GUARD] {error_msg}")
            raise RuntimeError(error_msg)

        # Check if repeating same tool consecutively (early warning)
        if self.last_tool == tool_name and self.tool_call_counts[tool_name] > 1:
            logger.warning(
                f"[LOOP GUARD] ⚠️ Repeated tool: {tool_name} called "
                f"{self.tool_call_counts[tool_name]} times consecutively"
            )

        self.last_tool = tool_name

    def after_agent(self, state: dict, runtime: Any) -> Optional[dict]:
        """Called after agent execution - log summary.

        Args:
            state: Agent output state
            runtime: Agent runtime context

        Returns:
            Modified state or None
        """
        if not self.enabled:
            return state

        logger.info(
            f"[LOOP GUARD] Execution complete - "
            f"{self.total_calls} total tool calls, "
            f"{len(self.tool_call_counts)} unique tools"
        )

        # Log tool usage summary
        if self.tool_call_counts:
            logger.debug(f"[LOOP GUARD] Tool usage: {dict(self.tool_call_counts)}")

        return state

    def on_error(self, state: dict, runtime: Any, error: Exception) -> Optional[dict]:
        """Called on error - log state before exit.

        Args:
            state: Current agent state
            runtime: Agent runtime context
            error: Exception that occurred

        Returns:
            Modified state or None
        """
        if not self.enabled:
            return state

        logger.error(
            f"[LOOP GUARD] Error after {self.total_calls} tool calls: {error}"
        )
        return state
