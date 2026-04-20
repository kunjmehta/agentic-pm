"""Module-level strategy registry — replaces the StrategyRegistry singleton class.

Two module-level dicts back a thin function API.  The ``get_registry()``
shim returns this module so all existing call sites work without changes:

    registry = get_registry()
    registry.get_metadata("mean-reversion")   # calls this module's get_metadata()
    registry.list_by_timeframe("1Min")        # calls this module's list_by_timeframe()
"""

import sys
import types
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.registry.strategy_metadata import StrategyMetadata
from src.common.utils import get_logger

logger = get_logger(__name__)

# ── Internal storage ──────────────────────────────────────────────────────────

_strategies: Dict[str, Type] = {}
_metadata: Dict[str, StrategyMetadata] = {}


# ── Public API ────────────────────────────────────────────────────────────────

def register(metadata: StrategyMetadata, strategy_class: Type) -> None:
    """Register a strategy class with its metadata.

    Args:
        metadata: StrategyMetadata describing the strategy.
        strategy_class: The strategy class to register.
    """
    name = metadata.name
    if name in _strategies:
        logger.warning(f"Strategy '{name}' already registered, overwriting with {strategy_class.__name__}")
    _strategies[name] = strategy_class
    _metadata[name] = metadata
    logger.debug(
        f"Registered strategy: {name} -> {strategy_class.__name__} "
        f"(timeframes={metadata.timeframes}, min_bars={metadata.min_bars})"
    )


def get_strategy(name: str) -> Optional[Type]:
    """Get strategy class by name.

    Args:
        name: Strategy name (e.g. ``"mean-reversion"``).

    Returns:
        Strategy class, or None if not found.
    """
    return _strategies.get(name)


def get_metadata(name: str) -> Optional[StrategyMetadata]:
    """Get strategy metadata by name.

    Args:
        name: Strategy name.

    Returns:
        StrategyMetadata, or None if not found.
    """
    return _metadata.get(name)


def instantiate(name: str, **kwargs: Any) -> Optional[Any]:
    """Instantiate a strategy by name.

    Args:
        name: Strategy name.
        **kwargs: Arguments passed to the strategy constructor.

    Returns:
        Strategy instance, or None if strategy not found or instantiation fails.
    """
    cls = _strategies.get(name)
    if cls is None:
        logger.error(f"Strategy '{name}' not found in registry")
        return None
    try:
        instance = cls(**kwargs)
        logger.debug(f"Instantiated strategy: {name} ({cls.__name__})")
        return instance
    except Exception as exc:
        logger.error(f"Failed to instantiate strategy '{name}': {exc}", exc_info=True)
        return None


def get_all_names() -> List[str]:
    """Get sorted list of all registered strategy names."""
    return sorted(_strategies.keys())


def get_all_metadata() -> Dict[str, StrategyMetadata]:
    """Get a copy of all registered strategy metadata."""
    return dict(_metadata)


def list_by_category(category: str) -> List[str]:
    """Get strategies filtered by category.

    Args:
        category: Category name (e.g. ``"intraday"``, ``"daily"``).
    """
    return [n for n, m in _metadata.items() if m.category == category]


def list_by_timeframe(timeframe: str) -> List[str]:
    """Get strategies that support the given timeframe.

    Args:
        timeframe: Timeframe string (e.g. ``"1Min"``, ``"1Day"``).
    """
    return [n for n, m in _metadata.items() if m.supports_timeframe(timeframe)]


def list_by_tag(tag: str) -> List[str]:
    """Get strategies filtered by tag.

    Args:
        tag: Tag string (e.g. ``"mean-reversion"``).
    """
    return [n for n, m in _metadata.items() if tag in m.tags]


def count() -> int:
    """Return the number of registered strategies."""
    return len(_strategies)


def clear() -> None:
    """Clear all registered strategies (for testing only)."""
    _strategies.clear()
    _metadata.clear()
    logger.warning("strategy_registry cleared")


# ── Backward-compatible shim ──────────────────────────────────────────────────

def get_registry() -> types.ModuleType:
    """Backward-compatible shim — returns this module.

    Existing call sites use ``registry = get_registry(); registry.get_metadata(name)``.
    Because this module exposes the same names as top-level functions, the call
    pattern continues to work unchanged.
    """
    return sys.modules[__name__]


# ── Decorator (kept for completeness) ────────────────────────────────────────

def register_strategy(metadata: StrategyMetadata) -> Callable:
    """Decorator to register a strategy class with metadata.

    Usage::

        @register_strategy(StrategyMetadata(name="my-strategy", ...))
        class MyStrategy:
            ...

    Args:
        metadata: StrategyMetadata describing the strategy.

    Returns:
        Decorator that registers the class and returns it unchanged.
    """
    def decorator(strategy_class: Type) -> Type:
        register(metadata, strategy_class)
        return strategy_class
    return decorator