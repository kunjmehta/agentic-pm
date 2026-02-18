"""Core utilities for the Agentic Portfolio Manager.

This module provides market hours checking and enforcement.

Usage:
    from src.core import require_market_hours, is_market_open

    # Enforce market hours
    @require_market_hours()
    def execute_trade():
        pass

    # Check market status
    if is_market_open():
        print("Market is open!")
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

__all__ = [
    # Market Hours
    "require_market_hours",
    "is_market_open",
    "is_weekend",
    "get_market_hours",
    "get_market_status",
    "get_next_market_open",
    "MarketHoursError",
]
