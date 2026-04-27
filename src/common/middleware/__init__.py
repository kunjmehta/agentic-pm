"""Middleware stack for all agentic trading agents.

Provides hook-chain middleware classes and LangGraph guard nodes:
- LoopPreventionMiddleware — halts runaway tool-call loops
- MarketHoursGuardMiddleware — rejects execution outside NYSE hours
- PortfolioGuardMiddleware — enforces daily P&L loss limits
- TracingMiddleware — captures thought blocks and tool call/result pairs
- PrettifyMiddleware — formats JSON outputs with Rich
- ToolTracingCallback — LangChain callback for per-tool performance tracking
- create_middleware_stack — builds the full hook-chain stack
- create_agent_middleware — builds LangChain prebuilt middleware tuple
- market_hours_guard, portfolio_guard — LangGraph node wrappers
"""

from src.common.middleware.loop_prevention import LoopPreventionMiddleware
from src.common.middleware.market_hours import MarketHoursGuardMiddleware
from src.common.middleware.portfolio_guard import PortfolioGuardMiddleware
from src.common.middleware.tracing import TracingMiddleware
from src.common.middleware.prettify import PrettifyMiddleware
from src.common.middleware.tool_tracing import ToolTracingCallback
from src.common.middleware.middleware_factory import create_middleware_stack, create_agent_middleware
from src.common.middleware.guards import market_hours_guard, portfolio_guard

__all__ = [
    "LoopPreventionMiddleware",
    "MarketHoursGuardMiddleware",
    "PortfolioGuardMiddleware",
    "TracingMiddleware",
    "PrettifyMiddleware",
    "ToolTracingCallback",
    "create_middleware_stack",
    "create_agent_middleware",
    "market_hours_guard",
    "portfolio_guard",
]
