"""Test loop prevention middleware."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from src.common.core.middleware.loop_prevention import LoopPreventionMiddleware


def test_loop_prevention_per_tool_limit():
    """Test that loop prevention stops repeated tool calls."""
    middleware = LoopPreventionMiddleware(
        max_iterations_per_tool=2,
        max_total_iterations=10,
        enabled=True
    )

    # Reset for new invocation
    middleware.before_agent({}, None)

    # First call - OK
    middleware.on_tool_start("fetch_data", {"symbol": "AAPL"})
    assert middleware.tool_call_counts["fetch_data"] == 1

    # Second call - OK (at limit)
    middleware.on_tool_start("fetch_data", {"symbol": "AAPL"})
    assert middleware.tool_call_counts["fetch_data"] == 2

    # Third call - Should raise
    with pytest.raises(RuntimeError, match="Loop detected"):
        middleware.on_tool_start("fetch_data", {"symbol": "AAPL"})


def test_loop_prevention_total_limit():
    """Test that total iteration limit works."""
    middleware = LoopPreventionMiddleware(
        max_iterations_per_tool=5,
        max_total_iterations=3,  # Low total limit
        enabled=True
    )

    middleware.before_agent({}, None)

    # Call different tools up to limit
    middleware.on_tool_start("tool_a", {})
    middleware.on_tool_start("tool_b", {})
    middleware.on_tool_start("tool_c", {})
    assert middleware.total_calls == 3

    # Fourth call - Should raise (total limit)
    with pytest.raises(RuntimeError, match="Too many tool calls"):
        middleware.on_tool_start("tool_d", {})


def test_loop_prevention_disabled():
    """Test that middleware can be disabled."""
    middleware = LoopPreventionMiddleware(
        max_iterations_per_tool=1,
        enabled=False  # Disabled
    )

    middleware.before_agent({}, None)

    # Should allow unlimited calls when disabled
    for i in range(10):
        middleware.on_tool_start("test_tool", {})

    assert middleware.tool_call_counts["test_tool"] == 0  # Not tracked when disabled


def test_loop_prevention_reset():
    """Test that counters reset between invocations."""
    middleware = LoopPreventionMiddleware(
        max_iterations_per_tool=2,
        enabled=True
    )

    # First invocation
    middleware.before_agent({}, None)
    middleware.on_tool_start("fetch_data", {})
    middleware.on_tool_start("fetch_data", {})
    assert middleware.tool_call_counts["fetch_data"] == 2

    # Second invocation - counters should reset
    middleware.before_agent({}, None)
    assert middleware.tool_call_counts["fetch_data"] == 0
    assert middleware.total_calls == 0

    # Should be able to call twice again
    middleware.on_tool_start("fetch_data", {})
    middleware.on_tool_start("fetch_data", {})
    assert middleware.tool_call_counts["fetch_data"] == 2


if __name__ == "__main__":
    print("=" * 60)
    print("Loop Prevention Middleware Tests")
    print("=" * 60)

    try:
        test_loop_prevention_per_tool_limit()
        print("✓ Per-tool limit test passed")
    except AssertionError as e:
        print(f"✗ Per-tool limit test failed: {e}")

    try:
        test_loop_prevention_total_limit()
        print("✓ Total limit test passed")
    except AssertionError as e:
        print(f"✗ Total limit test failed: {e}")

    try:
        test_loop_prevention_disabled()
        print("✓ Disabled mode test passed")
    except AssertionError as e:
        print(f"✗ Disabled mode test failed: {e}")

    try:
        test_loop_prevention_reset()
        print("✓ Reset test passed")
    except AssertionError as e:
        print(f"✗ Reset test failed: {e}")

    print("=" * 60)
    print("All tests completed!")
    print("=" * 60)
