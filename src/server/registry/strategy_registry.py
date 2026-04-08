"""Decorator-based strategy registry for auto-discovery pattern.

This module provides a singleton StrategyRegistry that allows strategies to
self-register using the @register_strategy decorator. This eliminates the need
for hardcoded strategy dispatch logic across multiple files.
"""

import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Type, Callable

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.server.registry.strategy_metadata import StrategyMetadata
from src.common.utils import get_logger

logger = get_logger(__name__)


class StrategyRegistry:
    """Singleton registry for quantitative trading strategies.

    Strategies register themselves at import time using the @register_strategy
    decorator. The registry provides methods to lookup, instantiate, and list
    registered strategies.

    Usage:
        # In a strategy file:
        @register_strategy(StrategyMetadata(name="my-strategy", ...))
        class MyStrategy:
            ...

        # Lookup a strategy:
        registry = get_registry()
        strategy_class = registry.get_strategy("my-strategy")
        instance = registry.instantiate("my-strategy")

        # List all strategies:
        all_names = registry.get_all_names()
        all_metadata = registry.get_all_metadata()
    """

    _instance: Optional["StrategyRegistry"] = None
    _initialized: bool = False

    def __new__(cls):
        """Ensure only one instance exists (singleton pattern)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the registry (only once)."""
        if not StrategyRegistry._initialized:
            self._strategies: Dict[str, Type] = {}
            self._metadata: Dict[str, StrategyMetadata] = {}
            StrategyRegistry._initialized = True
            logger.info("StrategyRegistry initialized")

    def register(
        self,
        metadata: StrategyMetadata,
        strategy_class: Type,
    ) -> None:
        """Register a strategy class with its metadata.

        Called by @register_strategy decorator at import time.

        Args:
            metadata: StrategyMetadata describing the strategy
            strategy_class: The strategy class to register

        Raises:
            ValueError: If strategy name already registered
        """
        name = metadata.name

        if name in self._strategies:
            logger.warning(
                f"Strategy '{name}' already registered, overwriting with {strategy_class.__name__}"
            )

        self._strategies[name] = strategy_class
        self._metadata[name] = metadata

        logger.debug(
            f"Registered strategy: {name} -> {strategy_class.__name__} "
            f"(timeframes={metadata.timeframes}, min_bars={metadata.min_bars})"
        )

    def get_strategy(self, name: str) -> Optional[Type]:
        """Get strategy class by name.

        Args:
            name: Strategy name (e.g., "vwap-reversion")

        Returns:
            Strategy class, or None if not found
        """
        return self._strategies.get(name)

    def get_metadata(self, name: str) -> Optional[StrategyMetadata]:
        """Get strategy metadata by name.

        Args:
            name: Strategy name

        Returns:
            StrategyMetadata, or None if not found
        """
        return self._metadata.get(name)

    def instantiate(self, name: str, **kwargs) -> Optional[Any]:
        """Instantiate a strategy by name.

        Args:
            name: Strategy name
            **kwargs: Arguments to pass to strategy constructor

        Returns:
            Strategy instance, or None if strategy not found
        """
        strategy_class = self.get_strategy(name)
        if strategy_class is None:
            logger.error(f"Strategy '{name}' not found in registry")
            return None

        try:
            instance = strategy_class(**kwargs)
            logger.debug(f"Instantiated strategy: {name} ({strategy_class.__name__})")
            return instance
        except Exception as exc:
            logger.error(
                f"Failed to instantiate strategy '{name}': {exc}",
                exc_info=True,
            )
            return None

    def get_all_names(self) -> List[str]:
        """Get list of all registered strategy names.

        Returns:
            List of strategy names (sorted alphabetically)
        """
        return sorted(self._strategies.keys())

    def get_all_metadata(self) -> Dict[str, StrategyMetadata]:
        """Get all registered strategy metadata.

        Returns:
            Dict mapping strategy name to StrategyMetadata
        """
        return self._metadata.copy()

    def list_by_category(self, category: str) -> List[str]:
        """Get strategies filtered by category.

        Args:
            category: Category name (e.g., "intraday", "daily")

        Returns:
            List of strategy names in that category
        """
        return [
            name
            for name, meta in self._metadata.items()
            if meta.category == category
        ]

    def list_by_timeframe(self, timeframe: str) -> List[str]:
        """Get strategies that support given timeframe.

        Args:
            timeframe: Timeframe string (e.g., "1Min", "1Day")

        Returns:
            List of strategy names supporting that timeframe
        """
        return [
            name
            for name, meta in self._metadata.items()
            if meta.supports_timeframe(timeframe)
        ]

    def list_by_tag(self, tag: str) -> List[str]:
        """Get strategies filtered by tag.

        Args:
            tag: Tag string (e.g., "mean-reversion", "volume")

        Returns:
            List of strategy names with that tag
        """
        return [
            name for name, meta in self._metadata.items() if tag in meta.tags
        ]

    def count(self) -> int:
        """Get count of registered strategies.

        Returns:
            Number of registered strategies
        """
        return len(self._strategies)

    def clear(self) -> None:
        """Clear all registered strategies (for testing)."""
        self._strategies.clear()
        self._metadata.clear()
        logger.warning("StrategyRegistry cleared")


# Singleton accessor
def get_registry() -> StrategyRegistry:
    """Get the singleton StrategyRegistry instance.

    Returns:
        StrategyRegistry instance
    """
    return StrategyRegistry()


# Decorator for strategy registration
def register_strategy(metadata: StrategyMetadata) -> Callable:
    """Decorator to register a strategy class with metadata.

    Usage:
        @register_strategy(StrategyMetadata(
            name="vwap-reversion",
            display_name="VWAP Reversion",
            timeframes=["1Min", "5Min"],
            min_bars=26,
        ))
        class VWAPReversionSkill:
            ...

    Args:
        metadata: StrategyMetadata describing the strategy

    Returns:
        Decorator function that registers the class
    """

    def decorator(strategy_class: Type) -> Type:
        """Register the strategy class and return it unchanged."""
        registry = get_registry()
        registry.register(metadata, strategy_class)
        return strategy_class

    return decorator


if __name__ == "__main__":
    """Test StrategyRegistry and @register_strategy decorator."""
    print("Testing StrategyRegistry...")

    # Clear registry for testing
    registry = get_registry()
    registry.clear()

    # Test registration via decorator
    @register_strategy(
        StrategyMetadata(
            name="test-strategy-1",
            display_name="Test Strategy 1",
            category="intraday",
            timeframes=["1Min", "5Min"],
            min_bars=20,
            tags=["test", "mean-reversion"],
        )
    )
    class TestStrategy1:
        def __init__(self):
            self.name = "TestStrategy1"

    @register_strategy(
        StrategyMetadata(
            name="test-strategy-2",
            display_name="Test Strategy 2",
            category="daily",
            timeframes=["1Day"],
            min_bars=50,
            tags=["test", "momentum"],
        )
    )
    class TestStrategy2:
        def __init__(self, param=None):
            self.name = "TestStrategy2"
            self.param = param

    # Test registry methods
    print(f"[OK] Registered {registry.count()} strategies")
    assert registry.count() == 2

    # Test get_all_names
    names = registry.get_all_names()
    assert names == ["test-strategy-1", "test-strategy-2"]
    print(f"[OK] get_all_names: {names}")

    # Test get_strategy
    strategy_class = registry.get_strategy("test-strategy-1")
    assert strategy_class == TestStrategy1
    print("[OK] get_strategy returns correct class")

    # Test get_metadata
    metadata = registry.get_metadata("test-strategy-1")
    assert metadata.name == "test-strategy-1"
    assert metadata.category == "intraday"
    assert metadata.min_bars == 20
    print("[OK] get_metadata returns correct metadata")

    # Test instantiate
    instance = registry.instantiate("test-strategy-1")
    assert instance is not None
    assert instance.name == "TestStrategy1"
    print("[OK] instantiate creates instance")

    # Test instantiate with args
    instance2 = registry.instantiate("test-strategy-2", param="test_value")
    assert instance2 is not None
    assert instance2.param == "test_value"
    print("[OK] instantiate with kwargs works")

    # Test list_by_category
    intraday = registry.list_by_category("intraday")
    assert intraday == ["test-strategy-1"]
    daily = registry.list_by_category("daily")
    assert daily == ["test-strategy-2"]
    print(f"[OK] list_by_category: intraday={intraday}, daily={daily}")

    # Test list_by_timeframe
    min1_strategies = registry.list_by_timeframe("1Min")
    assert min1_strategies == ["test-strategy-1"]
    day_strategies = registry.list_by_timeframe("1Day")
    assert day_strategies == ["test-strategy-2"]
    print(f"[OK] list_by_timeframe: 1Min={min1_strategies}, 1Day={day_strategies}")

    # Test list_by_tag
    mean_rev = registry.list_by_tag("mean-reversion")
    assert mean_rev == ["test-strategy-1"]
    momentum = registry.list_by_tag("momentum")
    assert momentum == ["test-strategy-2"]
    print(f"[OK] list_by_tag: mean-reversion={mean_rev}, momentum={momentum}")

    # Test get_all_metadata
    all_metadata = registry.get_all_metadata()
    assert len(all_metadata) == 2
    assert "test-strategy-1" in all_metadata
    assert "test-strategy-2" in all_metadata
    print("[OK] get_all_metadata returns all metadata")

    # Test singleton behavior
    registry2 = get_registry()
    assert registry2 is registry
    assert registry2.count() == 2
    print("[OK] Singleton pattern works")

    print("\n[PASS] All StrategyRegistry tests passed!")
