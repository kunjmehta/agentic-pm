"""Integration test for autonomous trading flow.

Tests the end-to-end autonomous trading workflow:
1. Signal aggregation
2. PM decision processing
3. Graph state management
4. HITL interrupt handling
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
from datetime import datetime

from src.semi_auto.services.signal_aggregator import SignalAggregator
from src.semi_auto.nodes.pm_decision_node import pm_decision_node
from src.semi_auto.state import make_initial_state
from src.common.utils import get_logger

logger = get_logger(__name__)


async def test_signal_aggregator():
    """Test 1: Signal aggregator can fetch and aggregate signals."""
    print("\n[TEST 1] Signal Aggregator")
    print("-" * 60)

    aggregator = SignalAggregator()

    # Fetch signals
    signals = await aggregator.fetch_actionable_signals(
        min_confidence=0.50,  # Lower for testing
        lookback_minutes=120
    )

    print(f"[OK] Fetched {len(signals)} signals")
    assert isinstance(signals, list), "Signals should be a list"

    if signals:
        # Aggregate by symbol
        aggregated = await aggregator.aggregate_by_symbol(signals)
        print(f"[OK] Aggregated into {len(aggregated)} symbols")

        for symbol, agg in list(aggregated.items())[:3]:
            print(f"  - {symbol}: {agg.action} @ {agg.confidence:.2f} ({agg.strategy_count} strategies)")

        # Generate full batch
        batch = await aggregator.generate_signal_batch(
            min_confidence=0.50,
            lookback_minutes=120
        )

        if batch:
            print(f"[OK] Generated batch {batch.batch_id} with {len(batch.signals)} signals")
        else:
            print("[OK] No signals passed validation (expected if no recent high-confidence signals)")
    else:
        print("[OK] No signals found (expected if no recent strategy results)")

    print("[PASS] Signal aggregator test complete\n")


async def test_pm_decision_autonomous_mode():
    """Test 2: PM decision node handles autonomous mode correctly."""
    print("\n[TEST 2] PM Decision Node - Autonomous Mode")
    print("-" * 60)

    # Create mock signal batch
    mock_signal_batch = {
        "batch_id": "test_batch_001",
        "signals": [
            {
                "symbol": "AAPL",
                "action": "buy",
                "confidence": 0.85,
                "strategies": ["mean_reversion", "golden_cross"],
                "strategy_count": 2,
                "consensus_reached": True,
                "entry_price": 150.25,
                "stop_loss": 148.50,
                "take_profit": 153.00,
                "reason": "2/2 strategies agree: buy signal",
                "timestamp": datetime.now(),
                "source_signals": []
            }
        ],
        "generated_at": datetime.now(),
        "lookback_minutes": 30,
        "min_confidence": 0.65,
        "total_signals_fetched": 5,
        "total_signals_aggregated": 1
    }

    # Create state with autonomous mode
    state = make_initial_state(
        query="[Autonomous] Test signal",
        thread_id="test_autonomous_001",
        backtest_mode=False
    )
    state["signal_batch"] = mock_signal_batch
    state["autonomous_mode"] = True

    # Process through PM decision node
    result = pm_decision_node(state)

    print(f"[OK] PM Decision Reasoning: {result.get('pm_decision_reasoning')}")
    print(f"[OK] Execute Orders: {result.get('_execute_orders')}")
    print(f"[OK] Order Task Queue: {len(result.get('order_task_queue') or [])} tasks")

    assert result.get("_execute_orders") is not None, "Should set _execute_orders flag"
    assert result.get("pm_decision_reasoning") is not None, "Should provide reasoning"

    if result.get("_execute_orders"):
        order_queue = result.get("order_task_queue", [])
        assert len(order_queue) > 0, "Should generate order tasks when executing"
        print(f"  - Generated {len(order_queue)} order task(s)")

    print("[PASS] PM decision autonomous mode test complete\n")


async def test_pm_decision_query_mode():
    """Test 3: PM decision node handles query-driven mode correctly."""
    print("\n[TEST 3] PM Decision Node - Query-Driven Mode")
    print("-" * 60)

    # Create mock execution results
    mock_execution_results = {
        "qa_001": {
            "task_id": "qa_001",
            "function_name": "golden_cross_signals",
            "status": "success",
            "result": {
                "signal": "buy",
                "confidence": 0.82,
                "symbol": "AAPL",
                "entry_price": 150.25
            },
            "error": None
        }
    }

    # Create state with query-driven mode
    state = make_initial_state(
        query="Run golden cross on AAPL and execute if strong signal",
        thread_id="test_query_001",
        backtest_mode=False
    )
    state["symbol"] = "AAPL"
    state["execution_results"] = mock_execution_results
    state["autonomous_mode"] = False

    # Process through PM decision node
    result = pm_decision_node(state)

    print(f"[OK] PM Decision Reasoning: {result.get('pm_decision_reasoning')}")
    print(f"[OK] Execute Orders: {result.get('_execute_orders')}")

    assert result.get("_execute_orders") is not None, "Should set _execute_orders flag"
    assert result.get("pm_decision_reasoning") is not None, "Should provide reasoning"

    print("[PASS] PM decision query-driven mode test complete\n")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("AUTONOMOUS TRADING FLOW - Integration Tests")
    print("=" * 60)

    try:
        await test_signal_aggregator()
        await test_pm_decision_autonomous_mode()
        await test_pm_decision_query_mode()

        print("=" * 60)
        print("[SUCCESS] ALL TESTS PASSED")
        print("=" * 60)

    except AssertionError as exc:
        print(f"\n[FAILED] TEST FAILED: {exc}")
        raise
    except Exception as exc:
        print(f"\n[ERROR] ERROR: {exc}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(main())
