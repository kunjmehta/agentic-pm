"""In-memory cache for live trade data with time-based and size-based batching.

This module provides a thread-safe cache that accumulates live trades from WebSocket
streams and flushes them to the database in batches, reducing write frequency and
improving performance.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List, Optional, Tuple
import pandas as pd
from src.common.utils import config, get_logger


# Initialize logger
logger = get_logger(__name__)


class TradeCache:
    """In-memory cache for live trades with time-based and size-based batching.

    This cache accumulates trade data in memory and flushes to the database based on:
    - Time threshold: Flush every N minutes (configurable)
    - Size threshold: Flush when cache reaches 90% capacity

    Supports trade corrections and cancellations as per Alpaca real-time data spec:
    https://docs.alpaca.markets/docs/real-time-stock-pricing-data#trade-corrections
    https://docs.alpaca.markets/docs/real-time-stock-pricing-data#trade-cancelserrors

    Thread-safe implementation using threading.Lock for concurrent access.

    Attributes:
        _cache: Dict storing trades keyed by (symbol, trade_id) for update/delete support
        _lock: Thread lock for synchronization
        _batch_interval: Timedelta for flush interval
        _last_flush: Timestamp of last flush operation
        _max_size: Maximum cache size before forced flush
        _correction_count: Counter for trade corrections
        _cancellation_count: Counter for trade cancellations
    """

    def __init__(
        self,
        batch_interval_minutes: int = 5,
        max_size: int = 100000,
        max_memory_mb: int = 500
    ):
        """Initialize TradeCache.

        Args:
            batch_interval_minutes: Minutes between automatic flushes (default: 5)
            max_size: Maximum trades before forced flush (default: 100,000)
            max_memory_mb: Maximum memory usage in MB before forced flush (default: 500)
        """
        # Changed from deque to dict for O(1) lookup/update/delete
        self._cache: Dict[Tuple[str, int], Dict] = {}
        self._lock = Lock()
        self._batch_interval = timedelta(minutes=batch_interval_minutes)
        self._last_flush = datetime.now()
        self._max_size = max_size
        self._max_memory_bytes = max_memory_mb * 1024 * 1024
        self._correction_count = 0
        self._cancellation_count = 0

        logger.info(
            f"TradeCache initialized: batch_interval={batch_interval_minutes}min, "
            f"max_size={max_size:,}, max_memory={max_memory_mb}MB, supports corrections/cancellations"
        )

    def add_trade(self, trade_data: Dict) -> bool:
        """Add trade to cache.

        Args:
            trade_data: Dictionary with trade data (symbol, timestamp, price, size, trade_id, etc.)

        Returns:
            True if flush is needed, False otherwise

        Thread-safe: Uses lock for concurrent access
        """
        with self._lock:
            # Use (symbol, trade_id) as key for O(1) lookups
            symbol = trade_data.get('symbol')
            trade_id = trade_data.get('trade_id')

            if not symbol or trade_id is None:
                logger.warning(f"Trade missing symbol or trade_id, skipping: {trade_data}")
                return False

            key = (symbol, trade_id)
            self._cache[key] = trade_data

            # Check memory usage first (higher priority than other triggers)
            current_memory = self._estimate_memory_usage()
            if current_memory > self._max_memory_bytes:
                logger.warning(
                    f"Cache memory exceeded {self._max_memory_bytes / 1024 / 1024:.0f}MB "
                    f"(current: {current_memory / 1024 / 1024:.1f}MB), forcing flush"
                )
                return True

            should_flush = self._should_flush()

            if should_flush:
                logger.debug(
                    f"Flush triggered: size={len(self._cache):,}, "
                    f"time_since_last={datetime.now() - self._last_flush}"
                )

            return should_flush

    def update_trade(self, correction_data: Dict) -> bool:
        """Update an existing trade with corrected data.

        Handles Alpaca trade corrections:
        https://docs.alpaca.markets/docs/real-time-stock-pricing-data#trade-corrections

        Args:
            correction_data: Dictionary with corrected trade data (must include symbol, trade_id)

        Returns:
            True if trade was found and updated, False otherwise

        Thread-safe: Uses lock for concurrent access
        """
        with self._lock:
            symbol = correction_data.get('symbol')
            trade_id = correction_data.get('trade_id')

            if not symbol or trade_id is None:
                logger.warning(f"Correction missing symbol or trade_id: {correction_data}")
                return False

            key = (symbol, trade_id)

            if key in self._cache:
                # Update existing trade with corrected values
                old_trade = self._cache[key].copy()
                self._cache[key].update(correction_data)
                self._correction_count += 1

                logger.debug(
                    f"Trade corrected: {symbol} trade_id={trade_id} "
                    f"(price: {old_trade.get('price')} -> {correction_data.get('price', old_trade.get('price'))})"
                )
                return True
            else:
                logger.warning(
                    f"Trade correction received but original trade not in cache: "
                    f"{symbol} trade_id={trade_id}"
                )
                return False

    def cancel_trade(self, symbol: str, trade_id: int) -> bool:
        """Remove a trade from cache (cancellation or error).

        Handles Alpaca trade cancellations/errors:
        https://docs.alpaca.markets/docs/real-time-stock-pricing-data#trade-cancelserrors

        Args:
            symbol: Stock symbol
            trade_id: Trade ID to cancel

        Returns:
            True if trade was found and removed, False otherwise

        Thread-safe: Uses lock for concurrent access
        """
        with self._lock:
            key = (symbol, trade_id)

            if key in self._cache:
                removed_trade = self._cache.pop(key)
                self._cancellation_count += 1

                logger.debug(
                    f"Trade cancelled: {symbol} trade_id={trade_id} "
                    f"(price: ${removed_trade.get('price')}, size: {removed_trade.get('size')})"
                )
                return True
            else:
                logger.warning(
                    f"Trade cancellation received but trade not in cache: "
                    f"{symbol} trade_id={trade_id}"
                )
                return False

    def _estimate_memory_usage(self) -> int:
        """Estimate cache memory usage in bytes.

        Uses rough estimate: each trade dict ~200 bytes
        (symbol, timestamp, trade_id, price, size, exchange, conditions, etc.)

        Returns:
            Estimated memory usage in bytes

        Note: Assumes caller holds lock
        """
        # Rough estimate: each trade ~200 bytes
        return len(self._cache) * 200

    def _should_flush(self) -> bool:
        """Check if cache should be flushed.

        Returns:
            True if time or size threshold exceeded

        Note: Assumes caller holds lock
        """
        # Time-based trigger
        time_elapsed = datetime.now() - self._last_flush
        time_based = time_elapsed >= self._batch_interval

        # Size-based trigger (90% capacity)
        size_threshold = int(self._max_size * 0.9)
        size_based = len(self._cache) >= size_threshold

        return time_based or size_based

    def flush(self) -> pd.DataFrame:
        """Extract all trades from cache and return as DataFrame.

        Clears the cache and resets the last_flush timestamp.
        Note: Corrections and cancellations have already been applied in-place.

        Returns:
            DataFrame with all cached trades (with corrections applied, cancellations removed),
            empty DataFrame if cache is empty

        Thread-safe: Uses lock for concurrent access
        """
        with self._lock:
            if not self._cache:
                logger.debug("Flush called but cache is empty")
                return pd.DataFrame()

            # Extract all trades from dict values
            trades_list = list(self._cache.values())
            cache_size = len(trades_list)
            corrections = self._correction_count
            cancellations = self._cancellation_count

            # Clear cache and reset counters
            self._cache.clear()
            self._last_flush = datetime.now()
            self._correction_count = 0
            self._cancellation_count = 0

            logger.info(
                f"Flushed {cache_size:,} trades from cache "
                f"({corrections} corrections, {cancellations} cancellations applied)"
            )

            # Convert to DataFrame
            try:
                df = pd.DataFrame(trades_list)
                return df
            except Exception as e:
                logger.error(f"Error converting cache to DataFrame: {e}")
                return pd.DataFrame()

    def get_current_size(self) -> int:
        """Get current number of trades in cache.

        Returns:
            Number of trades currently cached

        Thread-safe: Uses lock for concurrent access
        """
        with self._lock:
            return len(self._cache)

    def get_stats(self) -> Dict:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats: size, capacity, time_since_flush, corrections, etc.

        Thread-safe: Uses lock for concurrent access
        """
        with self._lock:
            time_since_flush = datetime.now() - self._last_flush

            return {
                'current_size': len(self._cache),
                'max_size': self._max_size,
                'utilization_pct': (len(self._cache) / self._max_size) * 100 if self._max_size > 0 else 0,
                'time_since_flush_seconds': time_since_flush.total_seconds(),
                'batch_interval_seconds': self._batch_interval.total_seconds(),
                'last_flush': self._last_flush.isoformat(),
                'corrections_pending': self._correction_count,
                'cancellations_pending': self._cancellation_count
            }

    def force_flush(self) -> pd.DataFrame:
        """Force an immediate flush regardless of thresholds.

        Returns:
            DataFrame with all cached trades

        Thread-safe: Uses lock for concurrent access
        """
        logger.info("Force flush requested")
        return self.flush()


# Module-level singleton instance
_cache_instance: Optional[TradeCache] = None
_instance_lock = Lock()


def get_cache() -> TradeCache:
    """Get or create singleton TradeCache instance.

    Reads configuration from config file:
    - cache.batch_interval_minutes (default: 5)
    - cache.max_size (default: 100000)
    - cache.max_memory_mb (default: 500)

    Returns:
        TradeCache singleton instance

    Thread-safe: Uses lock for singleton creation
    """
    global _cache_instance

    if _cache_instance is None:
        with _instance_lock:
            # Double-check locking pattern
            if _cache_instance is None:
                batch_interval = config.get("cache.batch_interval_minutes", default=5)
                max_size = config.get("cache.max_size", default=100000)
                max_memory_mb = config.get("cache.max_memory_mb", default=500)

                _cache_instance = TradeCache(
                    batch_interval_minutes=batch_interval,
                    max_size=max_size,
                    max_memory_mb=max_memory_mb
                )

    return _cache_instance


def reset_cache() -> None:
    """Reset the singleton cache instance.

    Useful for testing or forcing cache recreation with new config.

    Thread-safe: Uses lock for instance reset
    """
    global _cache_instance

    with _instance_lock:
        if _cache_instance is not None:
            logger.info("Resetting cache instance")
            _cache_instance = None


if __name__ == "__main__":
    """Test TradeCache functionality."""
    import time

    print("=" * 60)
    print("Testing TradeCache")
    print("=" * 60)

    # Test 1: Basic operations
    print("\n1. Testing basic add/flush operations...")
    cache = TradeCache(batch_interval_minutes=1, max_size=1000)

    for i in range(100):
        trade = {
            'symbol': 'TEST',
            'timestamp': datetime.now(),
            'trade_id': i,
            'price': 150.0 + i * 0.01,
            'size': 100,
            'exchange': 'Q'
        }
        cache.add_trade(trade)

    print(f"   Added 100 trades")
    print(f"   Cache size: {cache.get_current_size()}")

    # Test 2: Flush
    print("\n2. Testing flush...")
    df = cache.flush()
    print(f"   Flushed {len(df)} trades")
    print(f"   Cache size after flush: {cache.get_current_size()}")

    # Test 3: Singleton
    print("\n3. Testing singleton pattern...")
    instance1 = get_cache()
    instance2 = get_cache()
    print(f"   Same instance: {instance1 is instance2}")

    print("\n" + "=" * 60)
    print("TradeCache Tests Complete")
    print("=" * 60)
