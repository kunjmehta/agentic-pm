"""Unified middleware for all agents.

Provides reusable middleware classes for:
- Loop prevention (prevents infinite agent loops)
- Market hours enforcement
- Portfolio risk limits
- Execution tracing
- Output prettification
- Tool performance tracking
"""

from .agent_middleware import (
    ToolTracingCallback,
    MarketHoursGuardMiddleware,
    PortfolioGuardMiddleware,
    TracingMiddleware,
    PrettifyMiddleware,
    create_middleware_stack,
    create_agent_middleware,
)
from .loop_prevention import LoopPreventionMiddleware
from .turn_limit import TurnCallLimitMiddleware, TurnLimitReached

__all__ = [
    'ToolTracingCallback',
    'MarketHoursGuardMiddleware',
    'PortfolioGuardMiddleware',
    'TracingMiddleware',
    'PrettifyMiddleware',
    'LoopPreventionMiddleware',
    'TurnCallLimitMiddleware',
    'TurnLimitReached',
    'create_middleware_stack',
    'create_agent_middleware',
]
