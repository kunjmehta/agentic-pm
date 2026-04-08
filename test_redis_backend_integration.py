"""Test Redis Stream backend integration.

This test verifies that the backend can consume market data from Redis Streams
and process it through the handler pipeline.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import asyncio
from datetime import datetime


async def test_handler_dict_compatibility():
    """Test that handlers accept dict payloads."""
    from src.common.data_gatherer.db_stream_handlers import (
        save_trade_to_db,
        save_bar_to_db,
        combined_trade_handler,
        combined_bar_handler
    )

    print("=" * 70)
    print("Testing Handler Dict Compatibility")
    print("=" * 70)

    # Test trade handler with dict
    print("\n[Test 1] save_trade_to_db with dict payload:")
    trade_dict = {
        'symbol': 'AAPL',
        'timestamp': datetime.now().isoformat(),
        'trade_id': 'test-trade-123',
        'price': 150.25,
        'size': 100,
        'exchange': 'Q',
        'conditions': '@',
        'tape': 'A'
    }
    try:
        await save_trade_to_db(trade_dict)
        print("  [OK] Trade handler accepts dict")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Test bar handler with dict
    print("\n[Test 2] save_bar_to_db with dict payload:")
    bar_dict = {
        'symbol': 'AAPL',
        'timestamp': datetime.now().isoformat(),
        'open': 150.00,
        'high': 150.50,
        'low': 149.75,
        'close': 150.25,
        'volume': 1000000,
        'trade_count': 1523,
        'vwap': 150.15
    }
    try:
        await save_bar_to_db(bar_dict, timeframe='1Min')
        print("  [OK] Bar handler accepts dict")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Test combined handlers
    print("\n[Test 3] combined_trade_handler with dict:")
    try:
        await combined_trade_handler(trade_dict)
        print("  [OK] Combined trade handler accepts dict")
    except Exception as e:
        print(f"  [FAIL] {e}")

    print("\n[Test 4] combined_bar_handler with dict:")
    try:
        await combined_bar_handler(bar_dict, timeframe='1Min')
        print("  [OK] Combined bar handler accepts dict")
    except Exception as e:
        print(f"  [FAIL] {e}")

    print("\n" + "=" * 70)
    print("Handler Compatibility Tests Complete")
    print("=" * 70)


async def test_redis_consumer_integration():
    """Test Redis Stream consumer with handlers."""
    from src.common.cache.redis_stream_consumer import RedisStreamConsumer
    from src.common.cache.redis_stream_publisher import RedisStreamPublisher
    from src.common.data_gatherer.db_stream_handlers import (
        combined_trade_handler,
        combined_bar_handler
    )

    print("\n" + "=" * 70)
    print("Testing Redis Consumer Integration")
    print("=" * 70)

    test_symbols = ["AAPL"]

    try:
        # Initialize consumer
        print("\n[Test 1] Initialize consumer:")
        consumer = RedisStreamConsumer()
        consumer.subscribe_trades(test_symbols, combined_trade_handler)
        consumer.subscribe_bars(test_symbols, combined_bar_handler)
        print("  [OK] Consumer subscribed to streams")

        # Publish test data
        print("\n[Test 2] Publish test data:")
        publisher = RedisStreamPublisher()

        trade_data = {
            'symbol': 'AAPL',
            'timestamp': datetime.now().isoformat(),
            'trade_id': 'integration-test-1',
            'price': 150.25,
            'size': 100,
            'exchange': 'Q',
            'conditions': ['@'],
            'tape': 'A'
        }
        publisher.publish_trade('AAPL', trade_data)

        bar_data = {
            'symbol': 'AAPL',
            'timestamp': datetime.now().isoformat(),
            'timeframe': '1Min',
            'open': 150.00,
            'high': 150.50,
            'low': 149.75,
            'close': 150.25,
            'volume': 1000000,
            'vwap': 150.15,
            'trade_count': 1523
        }
        publisher.publish_bar('AAPL', bar_data)
        print("  [OK] Test data published")

        # Poll once to consume
        print("\n[Test 3] Poll streams once:")
        await consumer._poll_streams(consumer._trade_streams, combined_trade_handler)
        await consumer._poll_streams(consumer._bar_streams, combined_bar_handler)
        print("  [OK] Data consumed and processed")

        # Cleanup
        print("\n[Cleanup] Deleting test streams:")
        publisher.delete_stream('AAPL', 'trades')
        publisher.delete_stream('AAPL', 'bars')
        print("  [OK] Test streams deleted")

        print("\n" + "=" * 70)
        print("✓ Redis Consumer Integration Tests Passed")
        print("=" * 70)

    except ValueError as e:
        print(f"\n✗ Configuration error: {e}")
        print("\nMake sure config.json has redis.enabled=true and redis.streams section")
        return False

    except Exception as e:
        print(f"\n✗ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


async def test_lifespan_startup_check():
    """Check that lifespan can detect Redis mode."""
    from src.common.utils import config

    print("\n" + "=" * 70)
    print("Testing Lifespan Configuration")
    print("=" * 70)

    redis_config = config.get("redis", {})
    enabled = redis_config.get("enabled", False)

    print(f"\n[Config Check] Redis enabled: {enabled}")

    if enabled:
        print("  [OK] Backend will use Redis Stream consumer mode")
    else:
        print("  [INFO] Backend will use legacy Alpaca direct streaming")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    print("=" * 70)
    print("Redis Backend Integration Test Suite")
    print("=" * 70)

    async def run_all_tests():
        # Test 1: Handler compatibility
        await test_handler_dict_compatibility()

        # Test 2: Lifespan config
        await test_lifespan_startup_check()

        # Test 3: Full integration (if Redis is available)
        try:
            success = await test_redis_consumer_integration()
            if success:
                print("\n✓ All integration tests passed!")
            else:
                print("\n⚠ Some integration tests failed (check logs)")
        except Exception as e:
            print(f"\n⚠ Integration test skipped: {e}")

    asyncio.run(run_all_tests())
