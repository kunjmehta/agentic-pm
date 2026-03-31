"""Core utilities for the Agentic Portfolio Manager.

This module provides market hours checking, enforcement, and agent middleware.

Usage:
    from src.core import require_market_hours, is_market_open, create_middleware_stack

    # Enforce market hours
    @require_market_hours()
    def execute_trade():
        pass

    # Check market status
    if is_market_open():
        print("Market is open!")

    # Create middleware stack for agents
    middleware = create_middleware_stack(backtest_mode=True, agent_type="quant")
"""

# Market hours exports
from .market_hours import (
    require_market_hours,
    is_market_open,
    is_weekend,
    get_market_hours,
    get_market_status,
    get_next_market_open,
    MarketHoursError,
)

# Middleware exports (Module 6)
from .middleware import (
    ToolTracingCallback,
    MarketHoursGuardMiddleware,
    PortfolioGuardMiddleware,
    TracingMiddleware,
    PrettifyMiddleware,
    create_middleware_stack
)

__all__ = [
    # Market Hours
    "require_market_hours",
    "is_market_open",
    "is_weekend",
    "get_market_hours",
    "get_market_status",
    "get_next_market_open",
    "MarketHoursError",
    # Middleware
    "ToolTracingCallback",
    "MarketHoursGuardMiddleware",
    "PortfolioGuardMiddleware",
    "TracingMiddleware",
    "PrettifyMiddleware",
    "create_middleware_stack",
]
