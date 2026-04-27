"""Redis Stream publisher for market data ingestion.

This module provides methods to publish trade and bar data to Redis Streams
with msgpack serialization and automatic retention management.

Usage:
    from src.common.cache.redis_stream_publisher import RedisStreamPublisher

    # Create publisher
    publisher = RedisStreamPublisher()

    # Publish trade
    publisher.publish_trade(
        symbol="AAPL",
        trade_data={
            "price": 150.25,
            "size": 100,
            "timestamp": "2024-03-20T10:30:00Z",
            "conditions": ["@", "F"]
        }
    )

    # Publish bar
    publisher.publish_bar(
        symbol="AAPL",
        bar_data={
            "timestamp": "2024-03-20T10:30:00Z",
            "open": 150.00,
            "high": 150.50,
            "low": 149.75,
            "close": 150.25,
            "volume": 1000000,
            "vwap": 150.15
        }
    )
"""

import time
from typing import Any, Dict, Optional

import msgpack
import redis

from src.common.cache.redis_manager import RedisManager
from src.common.utils.config_loader import config
from src.common.utils.logger import get_logger

logger = get_logger(__name__)


class RedisStreamPublisher:
    """Publisher for Redis Streams with msgpack serialization.

    Publishes trade and bar data to per-ticker streams with automatic
    time-based retention (MINID) to prevent unbounded growth.
    """

    def __init__(self):
        """Initialize Redis Stream publisher.

        Raises:
            ValueError: If Redis configuration is missing
        """
        # Get Redis client from manager
        self.redis_mgr = RedisManager()
        self.client = self.redis_mgr.get_client()

        # Load stream configuration
        stream_config = config.get("redis.streams", default={})
        if not stream_config:
            raise ValueError("redis.streams configuration missing in config.json")

        self.trades_prefix = stream_config.get("trades_prefix", "stream:trades:")
        self.bars_prefix = stream_config.get("bars_prefix", "stream:bars:")
        self.retention_minutes = stream_config.get("retention_minutes", 5)

        logger.info(
            f"RedisStreamPublisher initialized "
            f"(retention: {self.retention_minutes} min)"
        )

    def _get_retention_timestamp(self) -> int:
        """Calculate minimum retention timestamp in milliseconds.

        Returns:
            int: Unix timestamp in milliseconds for MINID trimming
        """
        retention_seconds = self.retention_minutes * 60
        min_timestamp_seconds = time.time() - retention_seconds
        return int(min_timestamp_seconds * 1000)

    def publish_trade(
        self,
        symbol: str,
        trade_data: Dict[str, Any],
        maxlen: Optional[int] = None
    ) -> Optional[str]:
        """Publish trade data to Redis Stream.

        Args:
            symbol: Stock ticker symbol (e.g., "AAPL")
            trade_data: Trade dictionary with fields:
                - price: float
                - size: int
                - timestamp: str (ISO format)
                - conditions: list[str] (optional)
                - exchange: str (optional)
            maxlen: Optional max stream length (uses time-based by default)

        Returns:
            str: Stream entry ID if successful, None otherwise

        Example:
            >>> publisher.publish_trade(
            ...     symbol="AAPL",
            ...     trade_data={
            ...         "price": 150.25,
            ...         "size": 100,
            ...         "timestamp": "2024-03-20T10:30:00Z",
            ...         "conditions": ["@"],
            ...         "exchange": "Q"
            ...     }
            ... )
            '1710932400000-0'
        """
        stream_key = f"{self.trades_prefix}{symbol.upper()}"

        try:
            # Serialize with msgpack
            serialized = msgpack.packb(trade_data, use_bin_type=True)

            # Add to stream with time-based retention
            min_id = self._get_retention_timestamp()

            entry_id = self.client.xadd(
                name=stream_key,
                fields={"data": serialized},
                maxlen=maxlen,
                approximate=True,
                minid=min_id
            )

            logger.debug(
                f"Published trade to {stream_key}: "
                f"{trade_data.get('price')} @ {trade_data.get('size')} "
                f"(entry_id: {entry_id.decode() if isinstance(entry_id, bytes) else entry_id})"
            )

            return entry_id.decode() if isinstance(entry_id, bytes) else entry_id

        except redis.RedisError as e:
            logger.error(f"Failed to publish trade to {stream_key}: {e}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error publishing trade to {stream_key}: {e}")
            return None

    def publish_bar(
        self,
        symbol: str,
        bar_data: Dict[str, Any],
        maxlen: Optional[int] = None
    ) -> Optional[str]:
        """Publish bar/candle data to Redis Stream.

        Args:
            symbol: Stock ticker symbol (e.g., "AAPL")
            bar_data: Bar dictionary with fields:
                - timestamp: str (ISO format)
                - open: float
                - high: float
                - low: float
                - close: float
                - volume: int
                - vwap: float (optional)
                - trade_count: int (optional)
            maxlen: Optional max stream length (uses time-based by default)

        Returns:
            str: Stream entry ID if successful, None otherwise

        Example:
            >>> publisher.publish_bar(
            ...     symbol="AAPL",
            ...     bar_data={
            ...         "timestamp": "2024-03-20T10:30:00Z",
            ...         "open": 150.00,
            ...         "high": 150.50,
            ...         "low": 149.75,
            ...         "close": 150.25,
            ...         "volume": 1000000,
            ...         "vwap": 150.15
            ...     }
            ... )
            '1710932400000-0'
        """
        stream_key = f"{self.bars_prefix}{symbol.upper()}"

        try:
            # Serialize with msgpack
            serialized = msgpack.packb(bar_data, use_bin_type=True)

            # Add to stream with time-based retention
            min_id = self._get_retention_timestamp()

            entry_id = self.client.xadd(
                name=stream_key,
                fields={"data": serialized},
                maxlen=maxlen,
                approximate=True,
                minid=min_id
            )

            logger.debug(
                f"Published bar to {stream_key}: "
                f"O:{bar_data.get('open')} H:{bar_data.get('high')} "
                f"L:{bar_data.get('low')} C:{bar_data.get('close')} "
                f"V:{bar_data.get('volume')} "
                f"(entry_id: {entry_id.decode() if isinstance(entry_id, bytes) else entry_id})"
            )

            return entry_id.decode() if isinstance(entry_id, bytes) else entry_id

        except redis.RedisError as e:
            logger.error(f"Failed to publish bar to {stream_key}: {e}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error publishing bar to {stream_key}: {e}")
            return None

    def get_stream_info(self, symbol: str, stream_type: str = "trades") -> Dict[str, Any]:
        """Get information about a stream.

        Args:
            symbol: Stock ticker symbol
            stream_type: "trades" or "bars"

        Returns:
            dict: Stream information (length, first_entry, last_entry, etc.)
        """
        prefix = self.trades_prefix if stream_type == "trades" else self.bars_prefix
        stream_key = f"{prefix}{symbol.upper()}"

        try:
            info = self.client.xinfo_stream(stream_key)
            return {
                "length": info.get(b"length", 0),
                "first_entry": info.get(b"first-entry", None),
                "last_entry": info.get(b"last-entry", None),
                "groups": info.get(b"groups", 0),
            }
        except redis.RedisError as e:
            logger.warning(f"Failed to get stream info for {stream_key}: {e}")
            return {}

    def trim_stream(
        self,
        symbol: str,
        stream_type: str = "trades",
        maxlen: Optional[int] = None
    ) -> int:
        """Manually trim a stream.

        Args:
            symbol: Stock ticker symbol
            stream_type: "trades" or "bars"
            maxlen: Max length to trim to (uses time-based if None)

        Returns:
            int: Number of entries removed
        """
        prefix = self.trades_prefix if stream_type == "trades" else self.bars_prefix
        stream_key = f"{prefix}{symbol.upper()}"

        try:
            if maxlen:
                # Length-based trim
                trimmed = self.client.xtrim(stream_key, maxlen=maxlen, approximate=True)
            else:
                # Time-based trim
                min_id = self._get_retention_timestamp()
                trimmed = self.client.xtrim(stream_key, minid=min_id, approximate=True)

            logger.info(f"Trimmed {trimmed} entries from {stream_key}")
            return trimmed

        except redis.RedisError as e:
            logger.error(f"Failed to trim stream {stream_key}: {e}")
            return 0

    def delete_stream(self, symbol: str, stream_type: str = "trades") -> bool:
        """Delete a stream.

        Args:
            symbol: Stock ticker symbol
            stream_type: "trades" or "bars"

        Returns:
            bool: True if deleted, False otherwise
        """
        prefix = self.trades_prefix if stream_type == "trades" else self.bars_prefix
        stream_key = f"{prefix}{symbol.upper()}"

        try:
            deleted = self.client.delete(stream_key)
            logger.info(f"Deleted stream {stream_key}: {bool(deleted)}")
            return bool(deleted)
        except redis.RedisError as e:
            logger.error(f"Failed to delete stream {stream_key}: {e}")
            return False

    def __repr__(self) -> str:
        """String representation of publisher."""
        return (
            f"RedisStreamPublisher("
            f"trades_prefix='{self.trades_prefix}', "
            f"bars_prefix='{self.bars_prefix}', "
            f"retention={self.retention_minutes}min)"
        )


if __name__ == "__main__":
    """Test Redis Stream publisher."""
    import sys
    from datetime import datetime
    from pathlib import Path

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(project_root))

    print("=" * 60)
    print("RedisStreamPublisher Tests")
    print("=" * 60)

    try:
        # Test 1: Initialize publisher
        print("\n[Test 1] Initialize publisher:")
        publisher = RedisStreamPublisher()
        print(f"  Publisher: {publisher}")
        print("  [OK] Publisher initialized")

        # Test 2: Publish trade data
        print("\n[Test 2] Publish trade data:")
        test_symbol = "AAPL"
        trade_data = {
            "price": 150.25,
            "size": 100,
            "timestamp": datetime.now().isoformat(),
            "conditions": ["@", "F"],
            "exchange": "Q"
        }

        entry_id = publisher.publish_trade(test_symbol, trade_data)
        assert entry_id is not None, "Trade publish should succeed"
        print(f"  Published trade: entry_id={entry_id}")
        print(f"  Data: {trade_data}")
        print("  [OK] Trade published successfully")

        # Test 3: Publish bar data
        print("\n[Test 3] Publish bar data:")
        bar_data = {
            "timestamp": datetime.now().isoformat(),
            "open": 150.00,
            "high": 150.50,
            "low": 149.75,
            "close": 150.25,
            "volume": 1000000,
            "vwap": 150.15,
            "trade_count": 1523
        }

        entry_id = publisher.publish_bar(test_symbol, bar_data)
        assert entry_id is not None, "Bar publish should succeed"
        print(f"  Published bar: entry_id={entry_id}")
        print(f"  Data: OHLCV={bar_data['open']}/{bar_data['high']}/"
              f"{bar_data['low']}/{bar_data['close']}/{bar_data['volume']}")
        print("  [OK] Bar published successfully")

        # Test 4: Get stream info
        print("\n[Test 4] Get stream info:")
        trades_info = publisher.get_stream_info(test_symbol, "trades")
        bars_info = publisher.get_stream_info(test_symbol, "bars")

        print(f"  Trades stream length: {trades_info.get('length', 0)}")
        print(f"  Bars stream length: {bars_info.get('length', 0)}")
        print("  [OK] Stream info retrieved")

        # Test 5: Publish multiple entries
        print("\n[Test 5] Publish batch of trades:")
        for i in range(5):
            trade = {
                "price": 150.00 + i * 0.10,
                "size": 100 * (i + 1),
                "timestamp": datetime.now().isoformat(),
                "conditions": ["@"],
                "exchange": "Q"
            }
            publisher.publish_trade(test_symbol, trade)

        final_info = publisher.get_stream_info(test_symbol, "trades")
        print(f"  Final trades stream length: {final_info.get('length', 0)}")
        assert final_info.get('length', 0) >= 6, "Should have at least 6 trades"
        print("  [OK] Batch publish successful")

        # Test 6: Stream trimming
        print("\n[Test 6] Test stream trimming:")
        trimmed = publisher.trim_stream(test_symbol, "trades", maxlen=3)
        print(f"  Trimmed {trimmed} entries")

        trimmed_info = publisher.get_stream_info(test_symbol, "trades")
        print(f"  Stream length after trim: {trimmed_info.get('length', 0)}")
        print("  [OK] Stream trimming working")

        # Cleanup: Delete test streams
        print("\n[Cleanup] Deleting test streams:")
        publisher.delete_stream(test_symbol, "trades")
        publisher.delete_stream(test_symbol, "bars")
        print("  [OK] Test streams deleted")

        print("\n" + "=" * 60)
        print("✓ All RedisStreamPublisher tests passed")
        print("=" * 60)

    except ValueError as e:
        print(f"\n✗ Configuration error: {e}")
        print("\nMake sure config.json has redis.streams section:")
        print("""
{
  "redis": {
    "enabled": true,
    "streams": {
      "trades_prefix": "stream:trades:",
      "bars_prefix": "stream:bars:",
      "retention_minutes": 5
    }
  }
}
        """)
        sys.exit(1)

    except redis.RedisError as e:
        print(f"\n✗ Redis error: {e}")
        print("\nCheck Redis connection and configuration")
        sys.exit(1)

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
