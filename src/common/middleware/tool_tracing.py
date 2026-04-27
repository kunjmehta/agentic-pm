"""Tool execution tracing with performance tracking.

Captures tool calls with inputs, outputs, and execution times via LangChain
BaseCallbackHandler hooks.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import json
import time as time_module
from typing import Any, Dict, List

from langchain_core.callbacks import BaseCallbackHandler

from src.common.utils import get_logger

logger = get_logger(__name__)


class ToolTracingCallback(BaseCallbackHandler):
    """Callback handler to trace tool executions with performance tracking.

    Captures tool calls with inputs, outputs, and execution times.
    Enhanced for Improvement #2: Performance tracking with tool_timings.
    """

    def __init__(self):
        """Initialize the callback handler."""
        super().__init__()
        self.tool_calls: List[Dict] = []
        self.tool_timings: List[Dict] = []

    def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        """Log when tool execution starts and record start time.

        Args:
            serialized: Tool metadata including name.
            input_str: Input string passed to the tool.
            **kwargs: Additional arguments.
        """
        tool_name = serialized.get("name", "unknown_tool")
        logger.info(f"[TOOL] Calling: {tool_name}")

        try:
            input_data = json.loads(input_str) if isinstance(input_str, str) else input_str
            logger.info(f"[TOOL] Input: {json.dumps(input_data, indent=2, default=str)}")
        except (json.JSONDecodeError, TypeError):
            logger.info(f"[TOOL] Input: {input_str}")

        self.tool_timings.append({
            "tool": tool_name,
            "start_time": time_module.time(),
            "input": input_str[:100] if isinstance(input_str, str) else str(input_str)[:100],
        })

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Log when tool execution ends and record duration.

        Args:
            output: Tool output/result.
            **kwargs: Additional arguments.
        """
        if self.tool_timings:
            timing = self.tool_timings[-1]
            duration_ms = int((time_module.time() - timing["start_time"]) * 1000)
            timing["duration_ms"] = duration_ms
            timing["status"] = "success"
            timing.pop("start_time")
            logger.info(f"[TOOL] Completed in {duration_ms}ms")

        if len(str(output)) > 500:
            logger.info(f"[TOOL] Output: {str(output)[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")

    def on_tool_error(self, error: Exception, **kwargs: Any) -> None:
        """Log when tool execution fails and record error.

        Args:
            error: Exception that occurred.
            **kwargs: Additional arguments.
        """
        if self.tool_timings:
            timing = self.tool_timings[-1]
            duration_ms = int((time_module.time() - timing["start_time"]) * 1000)
            timing["duration_ms"] = duration_ms
            timing["status"] = "error"
            timing["error"] = str(error)
            timing.pop("start_time")

        logger.error(f"[TOOL] Error: {error}", exc_info=True)

    def get_tool_timings(self) -> List[Dict]:
        """Get performance timings for all executed tools.

        Returns:
            List of dicts with tool performance data.
        """
        return self.tool_timings

    def reset(self) -> None:
        """Reset tool timings for new interaction."""
        self.tool_calls.clear()
        self.tool_timings.clear()


if __name__ == "__main__":
    import time

    print("=" * 60)
    print("ToolTracingCallback Smoke Test")
    print("=" * 60)

    callback = ToolTracingCallback()
    callback.on_tool_start({"name": "test_tool"}, "test input")
    time.sleep(0.05)
    callback.on_tool_end("test output")

    timings = callback.get_tool_timings()
    assert len(timings) == 1
    assert timings[0]["tool"] == "test_tool"
    assert "duration_ms" in timings[0]
    assert timings[0]["status"] == "success"
    print(f"[OK] timing captured: {timings[0]['duration_ms']}ms")

    callback.reset()
    assert len(callback.get_tool_timings()) == 0
    print("[OK] reset works")

    print("\n[ALL OK] ToolTracingCallback smoke test complete")
