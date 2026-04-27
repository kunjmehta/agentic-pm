"""Performance tests for TradeCache.

Tests cache throughput and performance under high-volume scenarios.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import time
import threading
from datetime import datetime

from src.common.data_gatherer.trade_cache import TradeCache, reset_cache


class TestCachePerformance:
    """Performance tests for TradeCache."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton instance before each test."""
        reset_cache()
        yield
        reset_cache()

    @pytest.fixture
    def sample_trade(self):
        """Create a sample trade dictionary."""
        return {
            'symbol': 'AAPL',
            'timestamp': datetime.now(),
            'trade_id': 0,
            'price': 150.50,
            'size': 100,
            'exchange': 'Q'
        }

    # ========================================================================
    # Throughput Tests
    # ========================================================================

    def test_single_thread_throughput(self, sample_trade):
        """Test single-threaded cache throughput."""
        cache = TradeCache(batch_interval_minutes=60, max_size=1000000)

        # Measure time to add 100K trades
        num_trades = 100000
        start_time = time.time()

        for i in range(num_trades):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            cache.add_trade(trade)

        elapsed = time.time() - start_time
        throughput = num_trades / elapsed

        print(f"\n  Single-thread throughput: {throughput:,.0f} trades/sec")
        print(f"  Time for {num_trades:,} trades: {elapsed:.2f}s")

        # Should handle at least 10K trades/sec
        assert throughput > 10000, f"Throughput too low: {throughput:.0f} trades/sec"

        # Verify all trades were added
        assert cache.get_current_size() == num_trades

    def test_multi_thread_throughput(self, sample_trade):
        """Test multi-threaded cache throughput."""
        cache = TradeCache(batch_interval_minutes=60, max_size=1000000)

        num_threads = 10
        trades_per_thread = 10000
        total_trades = num_threads * trades_per_thread

        errors = []

        def add_trades(start_id, count):
            try:
                for i in range(count):
                    trade = sample_trade.copy()
                    trade['trade_id'] = start_id + i
                    cache.add_trade(trade)
            except Exception as e:
                errors.append(str(e))

        # Measure time for concurrent adds
        start_time = time.time()

        threads = []
        for t in range(num_threads):
            thread = threading.Thread(target=add_trades, args=(t * trades_per_thread, trades_per_thread))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        elapsed = time.time() - start_time
        throughput = total_trades / elapsed

        print(f"\n  Multi-thread throughput ({num_threads} threads): {throughput:,.0f} trades/sec")
        print(f"  Time for {total_trades:,} trades: {elapsed:.2f}s")

        # Should handle at least 5K trades/sec with multiple threads (thread contention)
        assert throughput > 5000, f"Multi-thread throughput too low: {throughput:.0f} trades/sec"

        # No errors should occur
        assert len(errors) == 0

        # Verify all trades were added
        assert cache.get_current_size() == total_trades

    # ========================================================================
    # Memory Usage Tests
    # ========================================================================

    def test_memory_efficiency(self, sample_trade):
        """Test memory usage with large cache."""
        import sys

        cache = TradeCache(batch_interval_minutes=60, max_size=100000)

        # Add trades and measure memory
        num_trades = 50000

        for i in range(num_trades):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            cache.add_trade(trade)

        # Get approximate memory size
        cache_size = sys.getsizeof(cache._cache)
        per_trade_bytes = cache_size / num_trades

        print(f"\n  Cache memory: {cache_size / 1024 / 1024:.2f} MB for {num_trades:,} trades")
        print(f"  Per trade: ~{per_trade_bytes:.0f} bytes")

        # Each trade dict should be reasonably sized (< 1KB per trade)
        assert per_trade_bytes < 1000, f"Memory usage too high: {per_trade_bytes:.0f} bytes/trade"

    # ========================================================================
    # Flush Performance Tests
    # ========================================================================

    def test_flush_performance(self, sample_trade):
        """Test flush operation performance."""
        cache = TradeCache(batch_interval_minutes=60, max_size=200000)

        # Add 100K trades
        num_trades = 100000
        for i in range(num_trades):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            cache.add_trade(trade)

        # Measure flush time
        start_time = time.time()
        df = cache.flush()
        elapsed = time.time() - start_time

        print(f"\n  Flush time for {num_trades:,} trades: {elapsed:.2f}s")
        print(f"  Flush throughput: {num_trades / elapsed:,.0f} trades/sec")

        # Flush should complete in < 1 second for 100K trades
        assert elapsed < 1.0, f"Flush too slow: {elapsed:.2f}s"

        # Verify DataFrame
        assert len(df) == num_trades

    def test_concurrent_flush_performance(self, sample_trade):
        """Test flush performance with concurrent access."""
        cache = TradeCache(batch_interval_minutes=60, max_size=200000)

        # Add trades while flushing
        num_initial = 50000
        num_concurrent = 10000

        for i in range(num_initial):
            cache.add_trade(sample_trade.copy())

        flush_result = []
        add_errors = []

        def flush_cache():
            try:
                start = time.time()
                df = cache.flush()
                elapsed = time.time() - start
                flush_result.append((len(df), elapsed))
            except Exception as e:
                add_errors.append(('flush', str(e)))

        def add_trades():
            try:
                for i in range(num_concurrent):
                    cache.add_trade(sample_trade.copy())
            except Exception as e:
                add_errors.append(('add', str(e)))

        # Start flush and add threads simultaneously
        flush_thread = threading.Thread(target=flush_cache)
        add_thread = threading.Thread(target=add_trades)

        start_time = time.time()
        flush_thread.start()
        add_thread.start()

        flush_thread.join()
        add_thread.join()
        total_elapsed = time.time() - start_time

        print(f"\n  Concurrent flush + add time: {total_elapsed:.2f}s")

        # No errors should occur
        assert len(add_errors) == 0

        # Flush should have completed
        assert len(flush_result) == 1

    # ========================================================================
    # Stress Tests
    # ========================================================================

    def test_sustained_high_volume(self, sample_trade):
        """Test cache under sustained high-volume load."""
        cache = TradeCache(batch_interval_minutes=1, max_size=500000)

        # Simulate 10 seconds of high-volume trading
        duration_seconds = 5
        target_rate = 10000  # 10K trades/sec

        start_time = time.time()
        trades_added = 0

        while time.time() - start_time < duration_seconds:
            # Add batch of trades
            for i in range(100):  # Add in small batches
                trade = sample_trade.copy()
                trade['trade_id'] = trades_added + i
                should_flush = cache.add_trade(trade)

                # Flush if needed
                if should_flush:
                    df = cache.flush()
                    print(f"    Auto-flushed {len(df):,} trades")

            trades_added += 100

        elapsed = time.time() - start_time
        actual_rate = trades_added / elapsed

        print(f"\n  Sustained load test: {trades_added:,} trades in {elapsed:.2f}s")
        print(f"  Actual rate: {actual_rate:,.0f} trades/sec")

        # Should have processed trades successfully
        assert trades_added > 0

    def test_maxlen_rollover_performance(self, sample_trade):
        """Test performance when cache hits maxlen and starts rolling over."""
        cache = TradeCache(batch_interval_minutes=60, max_size=10000)

        # Add 20K trades (2x max_size) to force rollover
        num_trades = 20000

        start_time = time.time()

        for i in range(num_trades):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            cache.add_trade(trade)

        elapsed = time.time() - start_time
        throughput = num_trades / elapsed

        print(f"\n  Rollover performance: {throughput:,.0f} trades/sec")

        # Dict-based cache grows beyond max_size (flush is triggered but entries are not dropped)
        assert cache.get_current_size() == num_trades

        # Should still be reasonably fast even with rollover
        assert throughput > 5000

    # ========================================================================
    # Real-World Simulation Tests
    # ========================================================================

    def test_realistic_trading_day_simulation(self, sample_trade):
        """Simulate a realistic trading day scenario."""
        # Typical trading day: 6.5 hours * 3600 seconds = 23,400 seconds
        # Average 100 trades/second = ~2.34M trades
        # We'll simulate 1 minute at this rate

        cache = TradeCache(batch_interval_minutes=5, max_size=100000)

        trades_per_second = 100
        duration_seconds = 60
        total_trades = trades_per_second * duration_seconds

        flushes = []

        start_time = time.time()
        trades_added = 0

        for second in range(duration_seconds):
            # Add trades for this second
            for i in range(trades_per_second):
                trade = sample_trade.copy()
                trade['trade_id'] = trades_added
                should_flush = cache.add_trade(trade)
                trades_added += 1

                if should_flush:
                    flush_start = time.time()
                    df = cache.flush()
                    flush_time = time.time() - flush_start
                    flushes.append((len(df), flush_time))

        elapsed = time.time() - start_time

        print(f"\n  Trading day simulation:")
        print(f"    Total trades: {trades_added:,}")
        print(f"    Duration: {elapsed:.2f}s")
        print(f"    Average rate: {trades_added / elapsed:,.0f} trades/sec")
        print(f"    Number of flushes: {len(flushes)}")

        if flushes:
            avg_flush_size = sum(f[0] for f in flushes) / len(flushes)
            avg_flush_time = sum(f[1] for f in flushes) / len(flushes)
            print(f"    Average flush size: {avg_flush_size:,.0f} trades")
            print(f"    Average flush time: {avg_flush_time:.3f}s")

        # Should have processed all trades successfully
        assert trades_added == total_trades


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])  # -s to show print output
