"""Execution tracing middleware.

Captures internal thought blocks and tool call/result pairs by inspecting
agent messages before and after model invocations.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import json
from typing import Any, List, Optional

from src.common.utils import get_logger

logger = get_logger(__name__)


class TracingMiddleware:
    """Middleware to capture internal thought blocks and tool outputs.

    Uses before_model and after_model hooks for detailed execution tracing.
    Also captures tool calls by inspecting agent messages for tool invocations.
    """

    def __init__(self):
        """Initialize tracing middleware."""
        self.current_tool_calls: List[dict] = []

    def before_model(self, state: dict, runtime: Any) -> Optional[dict]:
        """Log before model call.

        Args:
            state: Current agent state.
            runtime: Agent runtime context.

        Returns:
            None to continue execution.
        """
        messages = state.get("messages", [])
        logger.info(f"[TRACE] Calling model with {len(messages)} messages")
        if messages:
            last_msg = messages[-1]
            msg_type = getattr(last_msg, "type", "unknown")
            logger.debug(f"[TRACE] Last message type: {msg_type}")
        return None

    def after_model(self, state: dict, runtime: Any) -> Optional[dict]:
        """Log after model call and extract tool calls.

        Args:
            state: Current agent state with model response.
            runtime: Agent runtime context.

        Returns:
            None to continue execution.
        """
        messages = state.get("messages", [])
        logger.debug(f"[TRACE] Total messages in state: {len(messages)}")

        if not messages:
            return None

        last_msg = messages[-1]
        msg_type = getattr(last_msg, "type", getattr(last_msg, "__class__.__name__", "unknown"))
        logger.debug(f"[TRACE] Last message type: {msg_type}")

        # Inspect top-level tool_calls attribute
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tool_call in last_msg.tool_calls:
                tool_name = tool_call.get("name", "unknown_tool")
                tool_args = tool_call.get("args", {})
                tool_id = tool_call.get("id", "unknown_id")
                logger.info(f"[TOOL] Calling: {tool_name} (id: {tool_id})")
                logger.info(f"[TOOL] Input: {json.dumps(tool_args, indent=2, default=str)}")
                self.current_tool_calls.append({"id": tool_id, "name": tool_name, "args": tool_args})

        # Inspect additional_kwargs (OpenAI function-calling format)
        if hasattr(last_msg, "additional_kwargs"):
            additional = last_msg.additional_kwargs
            if isinstance(additional, dict) and "tool_calls" in additional:
                for tool_call in additional["tool_calls"]:
                    if not isinstance(tool_call, dict):
                        continue
                    tool_name = tool_call.get("function", {}).get("name", "unknown_tool")
                    tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                    tool_id = tool_call.get("id", "unknown_id")
                    try:
                        tool_args = (
                            json.loads(tool_args_str)
                            if isinstance(tool_args_str, str)
                            else tool_args_str
                        )
                    except json.JSONDecodeError:
                        tool_args = {"raw": tool_args_str}
                    logger.info(f"[TOOL] Calling: {tool_name} (id: {tool_id})")
                    logger.info(f"[TOOL] Input: {json.dumps(tool_args, indent=2, default=str)}")
                    self.current_tool_calls.append({"id": tool_id, "name": tool_name, "args": tool_args})

        # Inspect tool result messages
        if hasattr(last_msg, "type") and last_msg.type == "tool":
            tool_call_id = getattr(last_msg, "tool_call_id", None)
            content = getattr(last_msg, "content", "")
            matching_call = next(
                (c for c in self.current_tool_calls if c["id"] == tool_call_id), None
            )
            label = f"[TOOL] Result for {matching_call['name']}:" if matching_call else f"[TOOL] Result (id: {tool_call_id}):"
            logger.info(label)
            if len(str(content)) > 500:
                logger.info(f"[TOOL] Output: {str(content)[:500]}... (truncated)")
            else:
                logger.info(f"[TOOL] Output: {content}")
            if matching_call:
                self.current_tool_calls.remove(matching_call)

        content_preview = str(getattr(last_msg, "content", ""))[:100]
        logger.info(f"[TRACE] Model returned: {content_preview}...")
        logger.debug(f"[TRACE] Message type: {type(last_msg).__name__}")
        return None

    def on_error(self, state: dict, runtime: Any, error: Exception) -> Optional[dict]:
        """Log errors during execution.

        Args:
            state: Current agent state.
            runtime: Agent runtime context.
            error: Exception that occurred.

        Returns:
            None to propagate error.
        """
        logger.error(f"[TRACE] Execution failed: {error}", exc_info=True)
        return None


if __name__ == "__main__":
    print("=" * 60)
    print("TracingMiddleware Smoke Test")
    print("=" * 60)

    tracer = TracingMiddleware()

    mock_message = type("Message", (), {
        "type": "assistant",
        "content": "Using tools",
        "tool_calls": [{"id": "call_1", "name": "test_tool", "args": {"param": "value"}}],
    })()

    result = tracer.before_model({"messages": [mock_message]}, None)
    assert result is None
    print("[OK] before_model returns None")

    result = tracer.after_model({"messages": [mock_message]}, None)
    assert result is None
    assert len(tracer.current_tool_calls) == 1
    assert tracer.current_tool_calls[0]["name"] == "test_tool"
    print("[OK] after_model extracts tool calls")

    result = tracer.on_error({}, None, Exception("test"))
    assert result is None
    print("[OK] on_error returns None")

    print("\n[ALL OK] TracingMiddleware smoke test complete")
