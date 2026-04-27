"""Unit tests for TradeCache.

Tests cache flush logic, thread safety, and time-based/size-based triggers.
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


class TestTradeCache:
    """Test suite for TradeCache functionality."""

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
            'trade_id': 123456,
            'price': 150.50,
            'size': 100,
            'exchange': 'Q'
        }

    # ========================================================================
    # Basic Functionality Tests
    # ========================================================================

    def test_cache_initialization(self):
        """Test cache initialization with default parameters."""
        cache = TradeCache()

        assert cache.get_current_size() == 0
        assert cache._max_size == 100000
        assert cache._batch_interval.total_seconds() == 5 * 60  # 5 minutes

    def test_cache_initialization_custom_params(self):
        """Test cache initialization with custom parameters."""
        cache = TradeCache(batch_interval_minutes=10, max_size=50000)

        assert cache._max_size == 50000
        assert cache._batch_interval.total_seconds() == 10 * 60

    def test_add_trade(self, sample_trade):
        """Test adding a trade to cache."""
        cache = TradeCache()

        should_flush = cache.add_trade(sample_trade)

        assert cache.get_current_size() == 1
        assert should_flush is False  # Should not trigger flush for 1 trade

    def test_add_multiple_trades(self, sample_trade):
        """Test adding multiple trades."""
        cache = TradeCache()

        for i in range(10):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            cache.add_trade(trade)

        assert cache.get_current_size() == 10

    def test_flush_returns_dataframe(self, sample_trade):
        """Test that flush returns a DataFrame."""
        cache = TradeCache()

        # Add trades
        for i in range(5):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            cache.add_trade(trade)

        # Flush
        df = cache.flush()

        assert df is not None
        assert len(df) == 5
        assert 'symbol' in df.columns
        assert 'trade_id' in df.columns

    def test_flush_clears_cache(self, sample_trade):
        """Test that flush clears the cache."""
        cache = TradeCache()

        cache.add_trade(sample_trade)
        assert cache.get_current_size() == 1

        cache.flush()
        assert cache.get_current_size() == 0

    def test_flush_empty_cache(self):
        """Test flushing an empty cache."""
        cache = TradeCache()

        df = cache.flush()

        assert df.empty
        assert cache.get_current_size() == 0

    # ========================================================================
    # Size-Based Flush Trigger Tests
    # ========================================================================

    def test_size_based_flush_trigger(self, sample_trade):
        """Test that cache triggers flush at 90% capacity."""
        cache = TradeCache(batch_interval_minutes=60, max_size=100)

        # Add 89 unique trades (89% of 100)
        for i in range(89):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            cache.add_trade(trade)

        # 90th unique trade should trigger flush
        last_trade = sample_trade.copy()
        last_trade['trade_id'] = 89
        should_flush = cache.add_trade(last_trade)

        assert should_flush is True
        assert cache.get_current_size() == 90

    def test_size_not_triggering_below_threshold(self, sample_trade):
        """Test that cache doesn't trigger flush below 90% threshold."""
        cache = TradeCache(batch_interval_minutes=60, max_size=100)

        # Add 80 trades (80% of 100)
        for i in range(80):
            should_flush = cache.add_trade(sample_trade.copy())

        assert should_flush is False

    def test_max_size_enforcement(self, sample_trade):
        """Test that cache triggers flush signal when max_size is exceeded."""
        cache = TradeCache(batch_interval_minutes=60, max_size=10)

        # Add 15 unique trades (exceeds max_size of 10)
        flush_triggered = False
        for i in range(15):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            if cache.add_trade(trade):
                flush_triggered = True

        # Cache should have triggered flush at 90% (9 trades of max_size=10)
        assert flush_triggered is True

    # ========================================================================
    # Time-Based Flush Trigger Tests
    # ========================================================================

    def test_time_based_flush_trigger(self, sample_trade):
        """Test that cache triggers flush after time interval."""
        # Set very short interval for testing (0.01 min = 0.6 seconds)
        cache = TradeCache(batch_interval_minutes=0.01, max_size=10000)

        cache.add_trade(sample_trade)
        assert cache.get_current_size() == 1

        # Wait for interval to pass
        time.sleep(1)

        # Next add should trigger flush
        should_flush = cache.add_trade(sample_trade)

        assert should_flush is True

    def test_time_not_triggering_before_interval(self, sample_trade):
        """Test that cache doesn't trigger flush before time interval."""
        cache = TradeCache(batch_interval_minutes=10, max_size=10000)

        cache.add_trade(sample_trade)

        # Immediately add another - should not trigger flush
        should_flush = cache.add_trade(sample_trade)

        assert should_flush is False

    # ========================================================================
    # Thread Safety Tests
    # ========================================================================

    def test_concurrent_adds(self, sample_trade):
        """Test that concurrent adds are thread-safe."""
        cache = TradeCache(batch_interval_minutes=60, max_size=100000)
        errors = []

        def add_trades(start_id, count):
            try:
                for i in range(count):
                    trade = sample_trade.copy()
                    trade['trade_id'] = start_id + i
                    cache.add_trade(trade)
            except Exception as e:
                errors.append(str(e))

        # Create 10 threads, each adding 100 trades
        threads = []
        for t in range(10):
            thread = threading.Thread(target=add_trades, args=(t * 100, 100))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Should have 1000 total trades with no errors
        assert cache.get_current_size() == 1000
        assert len(errors) == 0

    def test_concurrent_flush(self, sample_trade):
        """Test that concurrent flushes are thread-safe."""
        cache = TradeCache(batch_interval_minutes=60, max_size=100000)
        results = []

        # Add 100 unique trades
        for i in range(100):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            cache.add_trade(trade)

        def flush_cache():
            df = cache.flush()
            results.append(len(df))

        # Create multiple threads that flush simultaneously
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=flush_cache)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Only one thread should get the data, others should get empty
        assert sum(results) == 100  # Total rows flushed
        assert cache.get_current_size() == 0

    # ========================================================================
    # Stats and Monitoring Tests
    # ========================================================================

    def test_get_stats(self, sample_trade):
        """Test getting cache statistics."""
        cache = TradeCache(batch_interval_minutes=5, max_size=1000)

        cache.add_trade(sample_trade)

        stats = cache.get_stats()

        assert 'current_size' in stats
        assert 'max_size' in stats
        assert 'utilization_pct' in stats
        assert 'time_since_flush_seconds' in stats
        assert 'batch_interval_seconds' in stats
        assert 'last_flush' in stats

        assert stats['current_size'] == 1
        assert stats['max_size'] == 1000
        assert 0 <= stats['utilization_pct'] <= 100

    def test_utilization_percentage(self, sample_trade):
        """Test utilization percentage calculation."""
        cache = TradeCache(batch_interval_minutes=5, max_size=100)

        # Add 50 unique trades
        for i in range(50):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            cache.add_trade(trade)

        stats = cache.get_stats()

        assert stats['utilization_pct'] == 50.0

    # ========================================================================
    # Force Flush Tests
    # ========================================================================

    def test_force_flush(self, sample_trade):
        """Test force flush functionality."""
        cache = TradeCache(batch_interval_minutes=60, max_size=10000)

        # Add 10 unique trades
        for i in range(10):
            trade = sample_trade.copy()
            trade['trade_id'] = i
            cache.add_trade(trade)

        # Force flush
        df = cache.force_flush()

        assert len(df) == 10
        assert cache.get_current_size() == 0

    # ========================================================================
    # Singleton Pattern Tests
    # ========================================================================

    def test_singleton_pattern(self):
        """Test that get_cache() returns the same instance."""
        from src.common.data_gatherer.trade_cache import get_cache

        cache1 = get_cache()
        cache2 = get_cache()

        assert cache1 is cache2

    def test_singleton_reset(self):
        """Test that reset_cache() creates new instance."""
        from src.common.data_gatherer.trade_cache import get_cache

        cache1 = get_cache()
        reset_cache()
        cache2 = get_cache()

        assert cache1 is not cache2

    # ========================================================================
    # Edge Cases
    # ========================================================================

    def test_add_trade_with_missing_fields(self):
        """Test that trade missing required trade_id is skipped."""
        cache = TradeCache()

        # Trade missing trade_id — should be skipped
        trade = {
            'symbol': 'AAPL',
            'timestamp': datetime.now()
        }

        cache.add_trade(trade)

        assert cache.get_current_size() == 0

    def test_multiple_flushes(self, sample_trade):
        """Test multiple consecutive flushes."""
        cache = TradeCache()

        # First flush - with data
        cache.add_trade(sample_trade)
        df1 = cache.flush()
        assert len(df1) == 1

        # Second flush - empty
        df2 = cache.flush()
        assert df2.empty

        # Add more and flush again
        cache.add_trade(sample_trade)
        df3 = cache.flush()
        assert len(df3) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
