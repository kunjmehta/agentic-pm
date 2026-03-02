"""Middleware stack for Quant Analyst agent.

Provides LangChain-compatible middleware classes for:
- Market hours guard (reject execution outside NYSE hours)
- Tracing (log all function calls and results)
- Prettification (format JSON outputs with Rich library)
- Tool call tracing via callbacks
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime, time
import pytz
from typing import Any, Optional, Dict, List
import json

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from src.utils import get_logger

logger = get_logger(__name__)


class ToolTracingCallback(BaseCallbackHandler):
    """Callback handler to trace tool executions.

    Captures tool calls with inputs and outputs for detailed logging.
    """

    def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        """Log when tool execution starts.

        Args:
            serialized: Tool metadata including name
            input_str: Input string passed to the tool
            **kwargs: Additional arguments
        """
        tool_name = serialized.get("name", "unknown_tool")
        logger.info(f"[TOOL] Calling: {tool_name}")

        # Try to parse input as JSON for better formatting
        try:
            input_data = json.loads(input_str) if isinstance(input_str, str) else input_str
            logger.info(f"[TOOL] Input: {json.dumps(input_data, indent=2, default=str)}")
        except (json.JSONDecodeError, TypeError):
            logger.info(f"[TOOL] Input: {input_str}")

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Log when tool execution ends.

        Args:
            output: Tool output/result
            **kwargs: Additional arguments
        """
        # Truncate long outputs for readability
        if len(str(output)) > 500:
            logger.info(f"[TOOL] Output: {str(output)[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")

    def on_tool_error(
        self, error: Exception, **kwargs: Any
    ) -> None:
        """Log when tool execution fails.

        Args:
            error: Exception that occurred
            **kwargs: Additional arguments
        """
        logger.error(f"[TOOL] Error: {error}", exc_info=True)


class MarketHoursGuardMiddleware:
    """LangChain middleware to reject execution outside market hours.

    Uses before_agent hook to check market hours before agent execution.
    """

    def __init__(self, backtest_mode: bool = False):
        """Initialize market hours guard.

        Args:
            backtest_mode: If True, bypass the check for testing
        """
        self.backtest_mode = backtest_mode

    def before_agent(self, state: dict, runtime: Any) -> Optional[dict]:
        """Check market hours before agent execution.

        Args:
            state: Current agent state
            runtime: Agent runtime context

        Returns:
            None to continue execution, or modified state to skip execution

        Raises:
            RuntimeError: If market is closed and not in backtest mode
        """
        if self.backtest_mode:
            logger.info("Market hours guard bypassed (backtest mode)")
            return None

        # Check if NYSE is open
        eastern = pytz.timezone('America/New_York')
        now_et = datetime.now(eastern)
        current_time = now_et.time()

        # Market hours: 9:30 AM - 4:00 PM ET, Monday-Friday
        market_open = time(9, 30)
        market_close = time(16, 0)

        is_weekday = now_et.weekday() < 5  # Monday=0, Friday=4
        is_market_hours = market_open <= current_time <= market_close

        if not (is_weekday and is_market_hours):
            error_msg = (
                f"Market is CLOSED. Current time: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}. "
                f"Market hours: Mon-Fri 9:30 AM - 4:00 PM ET"
            )
            logger.warning(error_msg)
            raise RuntimeError(error_msg)

        logger.info(f"Market is OPEN. Proceeding at {now_et.strftime('%H:%M:%S %Z')}")
        return None


class TracingMiddleware:
    """LangChain middleware to capture internal thought blocks and tool outputs.

    Uses before_model and after_model hooks for detailed execution tracing.
    Also captures tool calls by inspecting agent messages for tool invocations.
    """

    def __init__(self):
        """Initialize tracing middleware."""
        self.current_tool_calls = []

    def before_model(self, state: dict, runtime: Any) -> Optional[dict]:
        """Log before model call.

        Args:
            state: Current agent state
            runtime: Agent runtime context

        Returns:
            None to continue execution
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
            state: Current agent state with model response
            runtime: Agent runtime context

        Returns:
            None to continue execution
        """
        messages = state.get("messages", [])

        # Log all messages for debugging
        logger.debug(f"[TRACE] Total messages in state: {len(messages)}")

        if messages:
            last_msg = messages[-1]

            # Debug: log message type and check for tool-related attributes
            msg_type = getattr(last_msg, "type", getattr(last_msg, "__class__.__name__", "unknown"))
            logger.debug(f"[TRACE] Last message type: {msg_type}")

            # Check if message contains tool calls
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                for tool_call in last_msg.tool_calls:
                    tool_name = tool_call.get("name", "unknown_tool")
                    tool_args = tool_call.get("args", {})
                    tool_id = tool_call.get("id", "unknown_id")

                    logger.info(f"[TOOL] Calling: {tool_name} (id: {tool_id})")
                    logger.info(f"[TOOL] Input: {json.dumps(tool_args, indent=2, default=str)}")

                    # Store for matching with tool results
                    self.current_tool_calls.append({
                        "id": tool_id,
                        "name": tool_name,
                        "args": tool_args
                    })

            # Check for additional_kwargs which may contain tool calls
            if hasattr(last_msg, "additional_kwargs"):
                additional = last_msg.additional_kwargs
                if isinstance(additional, dict) and "tool_calls" in additional:
                    for tool_call in additional["tool_calls"]:
                        if isinstance(tool_call, dict):
                            tool_name = tool_call.get("function", {}).get("name", "unknown_tool")
                            tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                            tool_id = tool_call.get("id", "unknown_id")

                            try:
                                tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                            except json.JSONDecodeError:
                                tool_args = {"raw": tool_args_str}

                            logger.info(f"[TOOL] Calling: {tool_name} (id: {tool_id})")
                            logger.info(f"[TOOL] Input: {json.dumps(tool_args, indent=2, default=str)}")

                            # Store for matching with tool results
                            self.current_tool_calls.append({
                                "id": tool_id,
                                "name": tool_name,
                                "args": tool_args
                            })

            # Check if message contains tool results
            if hasattr(last_msg, "type") and last_msg.type == "tool":
                tool_call_id = getattr(last_msg, "tool_call_id", None)
                content = getattr(last_msg, "content", "")

                # Find matching tool call
                matching_call = None
                for call in self.current_tool_calls:
                    if call["id"] == tool_call_id:
                        matching_call = call
                        break

                if matching_call:
                    logger.info(f"[TOOL] Result for {matching_call['name']}:")
                    # Truncate long outputs
                    if len(str(content)) > 500:
                        logger.info(f"[TOOL] Output: {str(content)[:500]}... (truncated)")
                    else:
                        logger.info(f"[TOOL] Output: {content}")

                    # Remove from pending
                    self.current_tool_calls.remove(matching_call)
                else:
                    logger.info(f"[TOOL] Result (id: {tool_call_id}):")
                    if len(str(content)) > 500:
                        logger.info(f"[TOOL] Output: {str(content)[:500]}... (truncated)")
                    else:
                        logger.info(f"[TOOL] Output: {content}")

            # Log general model response
            content_preview = str(getattr(last_msg, "content", ""))[:100]
            logger.info(f"[TRACE] Model returned: {content_preview}...")
            logger.debug(f"[TRACE] Message type: {type(last_msg).__name__}")
        return None

    def on_error(self, state: dict, runtime: Any, error: Exception) -> Optional[dict]:
        """Log errors during execution.

        Args:
            state: Current agent state
            runtime: Agent runtime context
            error: Exception that occurred

        Returns:
            None to propagate error
        """
        logger.error(f"[TRACE] Execution failed: {error}", exc_info=True)
        return None


class PrettifyMiddleware:
    """LangChain middleware to format raw JSON tool outputs into Markdown.

    Uses after_agent hook to prettify final output with Rich library.
    """

    def after_agent(self, state: dict, runtime: Any) -> Optional[dict]:
        """Prettify agent output after execution.

        Args:
            state: Final agent state
            runtime: Agent runtime context

        Returns:
            None to continue with original state
        """
        # Check if there's structured output to prettify
        structured_response = state.get("structured_response")

        if structured_response:
            try:
                from rich import print as rprint
                from rich.panel import Panel
                from rich.json import JSON

                # Convert Pydantic model to dict if needed
                if hasattr(structured_response, "model_dump"):
                    output_dict = structured_response.model_dump()
                else:
                    output_dict = structured_response

                # Format as JSON
                json_str = json.dumps(output_dict, indent=2, default=str)

                # Print with Rich
                rprint(Panel(
                    JSON(json_str),
                    title="[bold blue]Agent Output[/bold blue]",
                    border_style="blue"
                ))
            except ImportError:
                # Fallback if Rich not available
                logger.debug("Rich library not available, skipping prettification")

        return None


def create_middleware_stack(backtest_mode: bool = False) -> list:
    """Create standard middleware stack for Quant Analyst.

    Order: MarketHoursGuard → TracingMiddleware → PrettifyMiddleware

    Args:
        backtest_mode: Bypass market hours check if True

    Returns:
        List of middleware instances to pass to create_deep_agent
    """
    return [
        MarketHoursGuardMiddleware(backtest_mode=backtest_mode),
        TracingMiddleware(),
        PrettifyMiddleware()
    ]


if __name__ == "__main__":
    """Test middleware classes."""
    print("="*60)
    print("Testing LangChain Middleware Classes")
    print("="*60)

    # Test 1: Market hours guard
    print("\n[1/3] Testing MarketHoursGuardMiddleware...")
    guard = MarketHoursGuardMiddleware(backtest_mode=False)
    try:
        result = guard.before_agent({}, None)
        print(f"OK: Market is open - guard returned {result}")
    except RuntimeError as e:
        print(f"Expected: Market closed - {e}")

    # Test 2: Backtest mode
    print("\n[2/3] Testing MarketHoursGuardMiddleware with backtest mode...")
    guard_backtest = MarketHoursGuardMiddleware(backtest_mode=True)
    result = guard_backtest.before_agent({}, None)
    print(f"OK: Backtest mode works (bypasses market hours) - returned {result}")

    # Test 3: Tracing middleware
    print("\n[3/3] Testing TracingMiddleware...")
    tracer = TracingMiddleware()

    # Simulate agent state with messages
    test_state = {
        "messages": [
            type('Message', (), {'type': 'user', 'content': 'Test message'})()
        ]
    }

    result_before = tracer.before_model(test_state, None)
    print(f"OK: before_model hook executed - returned {result_before}")

    result_after = tracer.after_model(test_state, None)
    print(f"OK: after_model hook executed - returned {result_after}")

    # Test 4: Create middleware stack
    print("\n[4/4] Testing create_middleware_stack...")
    stack = create_middleware_stack(backtest_mode=True)
    print(f"OK: Created middleware stack with {len(stack)} middleware instances:")
    for i, middleware in enumerate(stack, 1):
        print(f"  {i}. {middleware.__class__.__name__}")

    print("\n" + "="*60)
    print("Middleware tests complete!")
    print("="*60)
