"""Test that VWAP strategy registers correctly."""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import the strategy (will trigger registration)
from src.server.skills.quant.vwap_reversion import VWAPReversionSkill

# Import registry
from src.server.registry.strategy_registry import get_registry

def test_vwap_registration():
    """Test that VWAP strategy is registered."""
    registry = get_registry()

    # Check registration
    print(f"Total strategies registered: {registry.count()}")
    print(f"All strategy names: {registry.get_all_names()}")

    # Get VWAP strategy
    vwap_class = registry.get_strategy("vwap-reversion")
    print(f"\nVWAP strategy class: {vwap_class}")
    assert vwap_class is VWAPReversionSkill, "VWAP class mismatch"

    # Get metadata
    metadata = registry.get_metadata("vwap-reversion")
    print(f"\nVWAP Metadata:")
    print(f"  Name: {metadata.name}")
    print(f"  Display: {metadata.display_name}")
    print(f"  Category: {metadata.category}")
    print(f"  Timeframes: {metadata.timeframes}")
    print(f"  Min bars: {metadata.min_bars}")
    print(f"  Parameters: {list(metadata.parameters.keys())}")
    print(f"  Tags: {metadata.tags}")

    assert metadata.name == "vwap-reversion"
    assert metadata.category == "intraday"
    assert metadata.min_bars == 26
    assert "1Min" in metadata.timeframes
    assert "5Min" in metadata.timeframes

    # Test instantiation
    instance = registry.instantiate("vwap-reversion")
    print(f"\nInstantiated: {instance}")
    assert instance is not None
    assert isinstance(instance, VWAPReversionSkill)

    # Test timeframe filtering
    intraday_strategies = registry.list_by_timeframe("1Min")
    print(f"\n1Min strategies: {intraday_strategies}")
    assert "vwap-reversion" in intraday_strategies

    # Test tag filtering
    vwap_strategies = registry.list_by_tag("vwap")
    print(f"VWAP-tagged strategies: {vwap_strategies}")
    assert "vwap-reversion" in vwap_strategies

    print("\n[PASS] All VWAP registration tests passed!")


if __name__ == "__main__":
    test_vwap_registration()
