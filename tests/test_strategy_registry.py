"""Unit tests for strategy registry system.

Tests cover:
- StrategyMetadata validation
- StrategyRegistry singleton behavior
- Strategy registration and lookup
- Filtering by category, timeframe, and tag
- Parameter extraction from metadata
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
from src.server.registry.strategy_metadata import StrategyMetadata
from src.server.registry.strategy_registry import (
    get_registry,
    register_strategy,
    StrategyRegistry,
)
from src.server.registry.register_strategies import (
    register_all_strategies,
    ensure_strategies_registered,
    reset_registration_flag,
)


class TestStrategyMetadata:
    """Test StrategyMetadata dataclass."""

    def test_create_valid_metadata(self):
        """Test creating valid metadata."""
        metadata = StrategyMetadata(
            name="test-strategy",
            display_name="Test Strategy",
            description="Test description",
            category="intraday",
            timeframes=["1Min", "5Min"],
            min_bars=20,
            parameters={"param1": {"type": "float", "default": 1.0}},
            tags=["test", "mock"],
            config_prefix="strategy.test",
        )

        assert metadata.name == "test-strategy"
        assert metadata.display_name == "Test Strategy"
        assert metadata.category == "intraday"
        assert metadata.min_bars == 20
        assert len(metadata.timeframes) == 2
        assert len(metadata.parameters) == 1
        assert len(metadata.tags) == 2

    def test_validation_empty_name(self):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="name is required"):
            StrategyMetadata(name="", display_name="Test")

    def test_validation_empty_display_name(self):
        """Test that empty display_name raises ValueError."""
        with pytest.raises(ValueError, match="display_name is required"):
            StrategyMetadata(name="test", display_name="")

    def test_validation_invalid_min_bars(self):
        """Test that min_bars < 1 raises ValueError."""
        with pytest.raises(ValueError, match="min_bars must be >= 1"):
            StrategyMetadata(
                name="test", display_name="Test", min_bars=0
            )

    def test_validation_empty_timeframes(self):
        """Test that empty timeframes raises ValueError."""
        with pytest.raises(ValueError, match="At least one timeframe is required"):
            StrategyMetadata(
                name="test", display_name="Test", timeframes=[]
            )

    def test_supports_timeframe(self):
        """Test supports_timeframe method."""
        metadata = StrategyMetadata(
            name="test",
            display_name="Test",
            timeframes=["1Min", "5Min"],
        )

        assert metadata.supports_timeframe("1Min") is True
        assert metadata.supports_timeframe("5Min") is True
        assert metadata.supports_timeframe("1Day") is False

    def test_get_parameter_default(self):
        """Test get_parameter_default method."""
        metadata = StrategyMetadata(
            name="test",
            display_name="Test",
            parameters={
                "threshold": {"type": "float", "default": 2.5},
                "period": {"type": "int", "default": 20},
            },
        )

        assert metadata.get_parameter_default("threshold") == 2.5
        assert metadata.get_parameter_default("period") == 20
        assert metadata.get_parameter_default("unknown") is None

    def test_to_dict(self):
        """Test to_dict conversion."""
        metadata = StrategyMetadata(
            name="test",
            display_name="Test",
            description="Test description",
            category="intraday",
        )

        data = metadata.to_dict()
        assert isinstance(data, dict)
        assert data["name"] == "test"
        assert data["display_name"] == "Test"
        assert data["description"] == "Test description"
        assert data["category"] == "intraday"


class TestStrategyRegistry:
    """Test StrategyRegistry singleton and registration."""

    def setup_method(self):
        """Clear registry before each test."""
        registry = get_registry()
        registry.clear()

    def test_singleton_behavior(self):
        """Test that registry is a singleton."""
        registry1 = get_registry()
        registry2 = get_registry()
        assert registry1 is registry2

    def test_register_and_get_strategy(self):
        """Test registering and retrieving a strategy."""

        @register_strategy(
            StrategyMetadata(name="test-strategy", display_name="Test Strategy")
        )
        class TestStrategy:
            pass

        registry = get_registry()
        strategy_class = registry.get_strategy("test-strategy")
        assert strategy_class is TestStrategy

    def test_get_metadata(self):
        """Test retrieving strategy metadata."""

        metadata = StrategyMetadata(
            name="test-strategy",
            display_name="Test Strategy",
            category="intraday",
            min_bars=50,
        )

        @register_strategy(metadata)
        class TestStrategy:
            pass

        registry = get_registry()
        retrieved = registry.get_metadata("test-strategy")
        assert retrieved.name == "test-strategy"
        assert retrieved.display_name == "Test Strategy"
        assert retrieved.category == "intraday"
        assert retrieved.min_bars == 50

    def test_instantiate(self):
        """Test instantiating a strategy."""

        @register_strategy(
            StrategyMetadata(name="test-strategy", display_name="Test Strategy")
        )
        class TestStrategy:
            def __init__(self, param=None):
                self.param = param

        registry = get_registry()
        instance = registry.instantiate("test-strategy", param="test_value")
        assert instance is not None
        assert isinstance(instance, TestStrategy)
        assert instance.param == "test_value"

    def test_get_all_names(self):
        """Test getting all strategy names."""

        @register_strategy(
            StrategyMetadata(name="strategy-1", display_name="Strategy 1")
        )
        class Strategy1:
            pass

        @register_strategy(
            StrategyMetadata(name="strategy-2", display_name="Strategy 2")
        )
        class Strategy2:
            pass

        registry = get_registry()
        names = registry.get_all_names()
        assert len(names) == 2
        assert "strategy-1" in names
        assert "strategy-2" in names
        assert names == sorted(names)  # Should be alphabetically sorted

    def test_list_by_category(self):
        """Test filtering strategies by category."""

        @register_strategy(
            StrategyMetadata(
                name="intraday-1", display_name="Intraday 1", category="intraday"
            )
        )
        class IntradayStrategy:
            pass

        @register_strategy(
            StrategyMetadata(
                name="daily-1", display_name="Daily 1", category="daily"
            )
        )
        class DailyStrategy:
            pass

        registry = get_registry()
        intraday = registry.list_by_category("intraday")
        daily = registry.list_by_category("daily")

        assert "intraday-1" in intraday
        assert "daily-1" in daily
        assert "daily-1" not in intraday
        assert "intraday-1" not in daily

    def test_list_by_timeframe(self):
        """Test filtering strategies by timeframe."""

        @register_strategy(
            StrategyMetadata(
                name="strategy-1",
                display_name="Strategy 1",
                timeframes=["1Min", "5Min"],
            )
        )
        class Strategy1:
            pass

        @register_strategy(
            StrategyMetadata(
                name="strategy-2", display_name="Strategy 2", timeframes=["1Day"]
            )
        )
        class Strategy2:
            pass

        registry = get_registry()
        min1_strategies = registry.list_by_timeframe("1Min")
        day_strategies = registry.list_by_timeframe("1Day")

        assert "strategy-1" in min1_strategies
        assert "strategy-2" in day_strategies
        assert "strategy-2" not in min1_strategies
        assert "strategy-1" not in day_strategies

    def test_list_by_tag(self):
        """Test filtering strategies by tag."""

        @register_strategy(
            StrategyMetadata(
                name="strategy-1",
                display_name="Strategy 1",
                tags=["mean-reversion", "volume"],
            )
        )
        class Strategy1:
            pass

        @register_strategy(
            StrategyMetadata(
                name="strategy-2",
                display_name="Strategy 2",
                tags=["momentum", "breakout"],
            )
        )
        class Strategy2:
            pass

        registry = get_registry()
        mean_rev = registry.list_by_tag("mean-reversion")
        momentum = registry.list_by_tag("momentum")

        assert "strategy-1" in mean_rev
        assert "strategy-2" in momentum
        assert "strategy-2" not in mean_rev
        assert "strategy-1" not in momentum

    def test_count(self):
        """Test counting registered strategies."""
        registry = get_registry()
        assert registry.count() == 0

        @register_strategy(
            StrategyMetadata(name="strategy-1", display_name="Strategy 1")
        )
        class Strategy1:
            pass

        assert registry.count() == 1

        @register_strategy(
            StrategyMetadata(name="strategy-2", display_name="Strategy 2")
        )
        class Strategy2:
            pass

        assert registry.count() == 2


class TestRegisterStrategies:
    """Test centralized strategy registration."""

    def test_register_all_strategies(self):
        """Test that all 8 strategies are registered."""
        # Clear registry
        registry = get_registry()
        registry.clear()
        reset_registration_flag()

        # Register all strategies
        register_all_strategies()

        # Check count
        assert registry.count() == 8

        # Check specific strategies exist
        expected_strategies = [
            "mean-reversion",
            "vwap-reversion",
            "opening-range-breakout",
            "rsi-divergence",
            "momentum-burst",
            "golden-cross",
            "breakout-52w",
            "earnings-drift",
        ]

        for name in expected_strategies:
            assert registry.get_strategy(name) is not None
            assert registry.get_metadata(name) is not None

    def test_ensure_strategies_registered_idempotent(self):
        """Test that ensure_strategies_registered is idempotent."""
        registry = get_registry()
        registry.clear()
        reset_registration_flag()

        # Call multiple times
        ensure_strategies_registered()
        count1 = registry.count()

        ensure_strategies_registered()
        count2 = registry.count()

        ensure_strategies_registered()
        count3 = registry.count()

        # Count should remain stable
        assert count1 == count2 == count3
        assert count1 == 8

    def test_intraday_vs_daily_strategies(self):
        """Test correct categorization of intraday vs daily strategies."""
        registry = get_registry()
        registry.clear()
        reset_registration_flag()
        register_all_strategies()

        intraday = registry.list_by_category("intraday")
        daily = registry.list_by_category("daily")

        # Check counts
        assert len(intraday) == 5
        assert len(daily) == 3

        # Check specific strategies
        assert "mean-reversion" in intraday
        assert "vwap-reversion" in intraday
        assert "golden-cross" in daily
        assert "breakout-52w" in daily

    def test_all_strategies_have_complete_metadata(self):
        """Test that all registered strategies have complete metadata."""
        registry = get_registry()
        registry.clear()
        reset_registration_flag()
        register_all_strategies()

        for name in registry.get_all_names():
            metadata = registry.get_metadata(name)

            # Check required fields
            assert metadata.name
            assert metadata.display_name
            assert metadata.category
            assert len(metadata.timeframes) > 0
            assert metadata.min_bars > 0
            assert isinstance(metadata.parameters, dict)
            assert isinstance(metadata.tags, list)

            # Check that strategy class can be instantiated
            instance = registry.instantiate(name)
            assert instance is not None


if __name__ == "__main__":
    """Run tests with pytest."""
    pytest.main([__file__, "-v", "--tb=short"])
