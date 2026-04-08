"""Strategy metadata dataclass for registry system.

This module defines the StrategyMetadata dataclass used to describe strategies
in the decorator-based auto-discovery registry pattern.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class StrategyMetadata:
    """Metadata describing a quantitative trading strategy.

    Used by the @register_strategy decorator to auto-register strategies
    with their configuration and requirements.

    Attributes:
        name: Canonical strategy name (kebab-case, e.g., "vwap-reversion")
        display_name: Human-readable name (e.g., "VWAP Reversion")
        description: Brief description of strategy logic
        category: Strategy category ("intraday", "daily", "swing", etc.)
        timeframes: List of supported timeframes (e.g., ["1Min", "5Min"])
        min_bars: Minimum bars required for analysis
        parameters: Dict of configurable parameters with metadata:
                    {"param_name": {"type": "float", "default": 0.5, "min": 0, "max": 1}}
        tags: List of tags for filtering/search (e.g., ["mean-reversion", "volume"])
        config_prefix: Optional config key prefix (e.g., "strategy.vwap_reversion")
    """

    name: str
    display_name: str
    description: str = ""
    category: str = "intraday"
    timeframes: List[str] = field(default_factory=lambda: ["1Min", "5Min"])
    min_bars: int = 20
    parameters: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    config_prefix: Optional[str] = None

    def __post_init__(self):
        """Validate metadata after initialization."""
        if not self.name:
            raise ValueError("Strategy name is required")
        if not self.display_name:
            raise ValueError("Strategy display_name is required")
        if self.min_bars < 1:
            raise ValueError(f"min_bars must be >= 1, got {self.min_bars}")
        if not self.timeframes:
            raise ValueError("At least one timeframe is required")

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary for API responses.

        Returns:
            Dict representation of metadata
        """
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "timeframes": self.timeframes,
            "min_bars": self.min_bars,
            "parameters": self.parameters,
            "tags": self.tags,
            "config_prefix": self.config_prefix,
        }

    def supports_timeframe(self, timeframe: str) -> bool:
        """Check if strategy supports given timeframe.

        Args:
            timeframe: Timeframe string (e.g., "1Min", "1Day")

        Returns:
            True if timeframe is supported
        """
        return timeframe in self.timeframes

    def get_parameter_default(self, param_name: str) -> Any:
        """Get default value for a parameter.

        Args:
            param_name: Parameter name

        Returns:
            Default value, or None if parameter not found
        """
        param_meta = self.parameters.get(param_name)
        if param_meta:
            return param_meta.get("default")
        return None


if __name__ == "__main__":
    """Test StrategyMetadata creation and validation."""
    print("Testing StrategyMetadata...")

    # Test valid metadata
    metadata = StrategyMetadata(
        name="vwap-reversion",
        display_name="VWAP Reversion",
        description="Mean reversion to VWAP with volume confirmation",
        category="intraday",
        timeframes=["1Min", "5Min"],
        min_bars=26,
        parameters={
            "dev_pct": {"type": "float", "default": 0.005, "min": 0.001, "max": 0.05},
            "vol_mult": {"type": "float", "default": 2.0, "min": 1.0, "max": 5.0},
        },
        tags=["mean-reversion", "volume", "vwap"],
        config_prefix="strategy.vwap_reversion",
    )

    print(f"[OK] Created metadata: {metadata.name}")
    print(f"  Display: {metadata.display_name}")
    print(f"  Category: {metadata.category}")
    print(f"  Timeframes: {metadata.timeframes}")
    print(f"  Min bars: {metadata.min_bars}")
    print(f"  Parameters: {list(metadata.parameters.keys())}")
    print(f"  Tags: {metadata.tags}")

    # Test supports_timeframe
    assert metadata.supports_timeframe("1Min")
    assert metadata.supports_timeframe("5Min")
    assert not metadata.supports_timeframe("1Day")
    print("[OK] Timeframe support check works")

    # Test get_parameter_default
    assert metadata.get_parameter_default("dev_pct") == 0.005
    assert metadata.get_parameter_default("vol_mult") == 2.0
    assert metadata.get_parameter_default("unknown") is None
    print("[OK] Parameter default lookup works")

    # Test to_dict
    metadata_dict = metadata.to_dict()
    assert metadata_dict["name"] == "vwap-reversion"
    assert "parameters" in metadata_dict
    print("[OK] to_dict() conversion works")

    # Test validation failures
    try:
        StrategyMetadata(name="", display_name="Test")
        assert False, "Should have raised ValueError for empty name"
    except ValueError:
        print("[OK] Validation rejects empty name")

    try:
        StrategyMetadata(name="test", display_name="Test", min_bars=0)
        assert False, "Should have raised ValueError for min_bars=0"
    except ValueError:
        print("[OK] Validation rejects min_bars=0")

    print("\n[PASS] All StrategyMetadata tests passed!")
