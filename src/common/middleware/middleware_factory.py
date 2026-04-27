"""Middleware factory functions.

Creates the hook-chain middleware stack (create_middleware_stack) and the
LangChain prebuilt middleware tuple (create_agent_middleware) used by agents.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.utils import get_logger
from src.common.middleware.loop_prevention import LoopPreventionMiddleware
from src.common.middleware.market_hours import MarketHoursGuardMiddleware
from src.common.middleware.portfolio_guard import PortfolioGuardMiddleware
from src.common.middleware.tracing import TracingMiddleware
from src.common.middleware.prettify import PrettifyMiddleware

logger = get_logger(__name__)


def create_middleware_stack(
    backtest_mode: bool = False,
    agent_type: str = "quant",
    enable_loop_prevention: bool = True,
    max_iterations_per_tool: int = 2,
    max_total_iterations: int = 10,
    max_actions_per_turn: int = 2,
) -> list:
    """Create the hook-chain middleware stack for agents.

    These middlewares are invoked via BaseAgent._invoke_with_middleware() hooks
    (before_agent, after_agent, on_error). LangChain prebuilt rate-limit
    middleware is handled separately by create_agent_middleware().

    Order: LoopPrevention → MarketHours → [PortfolioGuard] → Tracing → Prettify

    Args:
        backtest_mode: Bypass guards if True.
        agent_type: Type of agent ("quant", "portfolio", or "backtester").
        enable_loop_prevention: Enable LoopPreventionMiddleware (default: True).
        max_iterations_per_tool: Max calls per tool name per run (default: 2).
        max_total_iterations: Max total tool calls per run (default: 10).
        max_actions_per_turn: Unused; kept for call-site compatibility.

    Returns:
        List of hook-chain middleware instances.
    """
    stack = []

    # 0. Loop prevention (always first — halts runaway loops before guards)
    stack.append(LoopPreventionMiddleware(
        max_iterations_per_tool=max_iterations_per_tool,
        max_total_iterations=max_total_iterations,
        enabled=enable_loop_prevention,
    ))

    # 1. Market hours guard
    stack.append(MarketHoursGuardMiddleware(backtest_mode=backtest_mode))

    # 2. Portfolio guard (Portfolio Manager only)
    if agent_type == "portfolio":
        stack.append(PortfolioGuardMiddleware(backtest_mode=backtest_mode))

    # 3. Tracing + prettification
    stack.extend([TracingMiddleware(), PrettifyMiddleware()])

    return stack


def create_agent_middleware(
    model_call_limit: int = 5,
    tool_call_limit: int = 1,
    tool_retry_count: int = 2,
) -> tuple:
    """Create LangChain prebuilt middleware tuple for DeepAgent.

    Pass the returned tuple directly to create_deep_agent(middleware=...).
    Limits are read from config when not explicitly overridden.

    Policy:
    - Each tool may be called at most once per agent run (tool_call_limit=1).
      On a second call the tool returns an error message; the LLM sees the
      error and should call declare_dispatch or wrap up.
    - The model itself is capped at model_call_limit total invocations.
    - Failed tool calls are retried up to tool_retry_count times before the
      error is returned to the LLM.

    Args:
        model_call_limit: Max LLM invocations per agent run (default: 5).
        tool_call_limit: Max calls per unique tool name (default: 1).
        tool_retry_count: Max retries on tool failure (default: 2).

    Returns:
        Tuple of prebuilt middleware instances for create_deep_agent.
    """
    from langchain.agents.middleware import (
        ModelCallLimitMiddleware,
        ToolCallLimitMiddleware,
        ToolRetryMiddleware,
    )
    from src.common.utils.config_loader import config as app_config

    resolved_model_limit = app_config.get("middleware.model_call_limit", model_call_limit)
    resolved_tool_limit = app_config.get("middleware.tool_call_limit", tool_call_limit)
    resolved_retry_count = app_config.get("middleware.tool_retry_count", tool_retry_count)

    logger.info(
        f"[middleware] model_call_limit={resolved_model_limit} "
        f"tool_call_limit={resolved_tool_limit} "
        f"tool_retry_count={resolved_retry_count}"
    )

    return (
        ModelCallLimitMiddleware(run_limit=resolved_model_limit),
        ToolCallLimitMiddleware(run_limit=resolved_tool_limit, exit_behavior="continue"),
        ToolRetryMiddleware(max_retries=resolved_retry_count, on_failure="continue"),
    )

