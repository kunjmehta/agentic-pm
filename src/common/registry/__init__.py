"""Shared strategy registry — importable by both API and ETL processes."""

from src.common.registry.strategy_metadata import StrategyMetadata
from src.common.registry.strategy_registry import (
    clear,
    count,
    get_all_metadata,
    get_all_names,
    get_metadata,
    get_registry,
    get_strategy,
    instantiate,
    list_by_category,
    list_by_tag,
    list_by_timeframe,
    register,
    register_strategy,
)

__all__ = [
    "StrategyMetadata",
    "clear",
    "count",
    "get_all_metadata",
    "get_all_names",
    "get_metadata",
    "get_registry",
    "get_strategy",
    "instantiate",
    "list_by_category",
    "list_by_tag",
    "list_by_timeframe",
    "register",
    "register_strategy",
]
