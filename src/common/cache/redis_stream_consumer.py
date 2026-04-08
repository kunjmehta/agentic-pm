"""Redis Stream consumer for backend market data consumption.

This module provides a consumer for Redis Streams with:
- Consumer groups for reliable delivery
- Batched polling to reduce overhead
- Pending message recovery on startup
- Multi-stream support for parallel consumption
- Acknowledgment after successful processing

Usage:
    from src.common.cache.redis_stream_consumer import RedisStreamConsumer

    # Create consumer
    consumer = RedisStreamConsumer()

    # Subscribe to trade streams
    async def handle_trade(trade_data: dict):
        print(f"Trade: {trade_data['symbol']} @ {trade_data['price']}")

    consumer.subscribe_trades(symbols=["AAPL", "MSFT"], handler=handle_trade)

    # Run consumer loop
    await consumer.run()
"""

import asyncio
import os
import socket
import time
from typing import Callable, Dict, List, Optional

import msgpack
import redis

from src.common.cache.redis_manager import RedisManager
from src.common.utils.config_loader import config
from src.common.utils.logger import get_logger

logger = get_logger(__name__)


class RedisStreamConsumer:
    """Consumer for Redis Streams with consumer groups and batched polling.

    Consumes trade and bar data from Redis Streams with reliable delivery
    using consumer groups. Supports batch processing and pending message
    recovery for fault tolerance.
    """

    def __init__(self):
        """Initialize Redis Stream consumer.

        Raises:
            ValueError: If Redis or streams configuration is missing
        """
        # Get Redis client
        self.redis_mgr = RedisManager()
        self.client = self.redis_mgr.get_client()

        # Load stream configuration
        stream_config = config.get("redis.streams", default={})
        if not stream_config:
            raise ValueError("redis.streams configuration missing in config.json")

        self.trades_prefix = stream_config.get("trades_prefix", "stream:trades:")
        self.bars_prefix = stream_config.get("bars_prefix", "stream:bars:")
        self.consumer_group = stream_config.get("consumer_group_backend", "backend-consumers")
        self.batch_size = stream_config.get("batch_size", 100)
        self.poll_interval = stream_config.get("batch_poll_interval_seconds", 10)

        # Generate unique consumer name: hostname-pid
        self.consumer_name = f"{socket.gethostname()}-{os.getpid()}"

        # Handlers and streams
        self._trade_handler: Optional[Callable] = None
        self._bar_handler: Optional[Callable] = None
        self._trade_streams: List[str] = []
        self._bar_streams: List[str] = []

        # Control flags
        self._running = False

        logger.info(
            f"RedisStreamConsumer initialized: group={self.consumer_group}, "
            f"consumer={self.consumer_name}, batch_size={self.batch_size}, "
            f"poll_interval={self.poll_interval}s"
        )

    def _ensure_consumer_group(self, streams: List[str]) -> None:
        """Create consumer group for streams if not exists.

        Args:
            streams: List of stream keys to create groups for
        """
        for stream in streams:
            try:
                self.client.xgroup_create(
                    name=stream,
                    groupname=self.consumer_group,
                    id='0',  # Start from beginning
                    mkstream=True  # Create stream if not exists
                )
                logger.info(f"Created consumer group '{self.consumer_group}' for {stream}")

            except redis.exceptions.ResponseError as e:
                if 'BUSYGROUP' in str(e):
                    # Group already exists
                    logger.debug(f"Consumer group '{self.consumer_group}' already exists for {stream}")
                else:
                    raise

    def subscribe_trades(
        self,
        symbols: List[str],
        handler: Callable
    ) -> None:
        """Subscribe to trade streams for symbols.

        Args:
            symbols: List of stock ticker symbols
            handler: Async callback function: async def handler(trade_data: dict)

        Example:
            >>> async def on_trade(trade_data: dict):
            ...     print(f"Trade: {trade_data['symbol']} @ {trade_data['price']}")
            >>>
            >>> consumer.subscribe_trades(["AAPL", "MSFT"], on_trade)
        """
        self._trade_handler = handler
        self._trade_streams = [f"{self.trades_prefix}{s.upper()}" for s in symbols]

        # Ensure consumer groups exist
        self._ensure_consumer_group(self._trade_streams)

        logger.info(f"Subscribed to {len(symbols)} trade streams: {symbols}")

    def subscribe_bars(
        self,
        symbols: List[str],
        handler: Callable
    ) -> None:
        """Subscribe to bar streams for symbols.

        Args:
            symbols: List of stock ticker symbols
            handler: Async callback function: async def handler(bar_data: dict)

        Example:
            >>> async def on_bar(bar_data: dict):
            ...     print(f"Bar: {bar_data['symbol']} OHLC={bar_data['close']}")
            >>>
            >>> consumer.subscribe_bars(["AAPL", "MSFT"], on_bar)
        """
        self._bar_handler = handler
        self._bar_streams = [f"{self.bars_prefix}{s.upper()}" for s in symbols]

        # Ensure consumer groups exist
        self._ensure_consumer_group(self._bar_streams)

        logger.info(f"Subscribed to {len(symbols)} bar streams: {symbols}")

    async def _recover_pending_messages(self) -> None:
        """Recover pending messages on startup.

        Reclaims messages that were delivered but not acknowledged before
        a previous crash or shutdown.
        """
        all_streams = self._trade_streams + self._bar_streams

        for stream in all_streams:
            try:
                # Get pending messages for this consumer
                pending = self.client.xpending_range(
                    name=stream,
                    groupname=self.consumer_group,
                    min='-',
                    max='+',
                    count=100,
                    consumername=self.consumer_name
                )

                if not pending:
                    continue

                logger.warning(f"Recovering {len(pending)} pending messages from {stream}")

                # Claim idle messages (1 minute idle threshold)
                message_ids = [p['message_id'] for p in pending]
                claimed = self.client.xclaim(
                    name=stream,
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    min_idle_time=60000,  # 1 minute
                    message_ids=message_ids
                )

                # Process claimed messages
                handler = self._trade_handler if 'trades' in stream else self._bar_handler
                for message_id, fields in claimed:
                    try:
                        payload = msgpack.unpackb(fields[b'data'], raw=False)
                        if handler:
                            await handler(payload)
                        self.client.xack(stream, self.consumer_group, message_id)

                    except Exception as e:
                        logger.error(f"Failed to recover message {message_id}: {e}", exc_info=True)
                        # Ack anyway to avoid reprocessing
                        self.client.xack(stream, self.consumer_group, message_id)

            except redis.RedisError as e:
                logger.error(f"Pending recovery error for {stream}: {e}", exc_info=True)

            except Exception as e:
                logger.error(f"Unexpected error during pending recovery for {stream}: {e}", exc_info=True)

    async def _poll_streams(
        self,
        streams: List[str],
        handler: Callable
    ) -> None:
        """Poll multiple streams and process messages.

        Args:
            streams: List of stream keys to poll
            handler: Async callback function for message processing
        """
        if not streams or not handler:
            return

        # Build streams dict: {stream_key: '>'}
        # '>' means only new messages not yet delivered to this consumer
        stream_keys = {stream: '>' for stream in streams}

        try:
            # XREADGROUP with batching
            results = self.client.xreadgroup(
                groupname=self.consumer_group,
                consumername=self.consumer_name,
                streams=stream_keys,
                count=self.batch_size,
                block=None  # Non-blocking (we poll on interval)
            )

            if not results:
                return

            # Process messages: results = [(stream_name, [(msg_id, {fields}), ...])]
            total_processed = 0
            for stream_name, messages in results:
                for message_id, fields in messages:
                    try:
                        # Deserialize msgpack payload
                        payload = msgpack.unpackb(fields[b'data'], raw=False)

                        # Call handler
                        await handler(payload)

                        # Acknowledge message
                        self.client.xack(stream_name, self.consumer_group, message_id)
                        total_processed += 1

                    except Exception as e:
                        logger.error(
                            f"Failed to process message {message_id} from {stream_name}: {e}",
                            exc_info=True
                        )
                        # Do NOT ack - will be recovered later

            if total_processed > 0:
                logger.debug(f"Processed {total_processed} messages")

        except redis.RedisError as e:
            logger.error(f"Poll error: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Unexpected poll error: {e}", exc_info=True)

    async def run(self) -> None:
        """Start consumer loop (runs as background task).

        Polls trade and bar streams on configured interval, processes messages,
        and acknowledges successful processing.

        Example:
            >>> consumer = RedisStreamConsumer()
            >>> consumer.subscribe_trades(["AAPL"], handle_trade)
            >>> await consumer.run()  # Blocks until stopped
        """
        self._running = True
        logger.info(f"Starting Redis Stream consumer: {self.consumer_name}")

        # Recover pending messages on startup
        await self._recover_pending_messages()

        while self._running:
            try:
                # Poll trade streams
                if self._trade_handler and self._trade_streams:
                    await self._poll_streams(self._trade_streams, self._trade_handler)

                # Poll bar streams
                if self._bar_handler and self._bar_streams:
                    await self._poll_streams(self._bar_streams, self._bar_handler)

                # Wait before next poll
                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                logger.info("Consumer loop cancelled")
                break

            except Exception as e:
                logger.error(f"Consumer error: {e}", exc_info=True)
                await asyncio.sleep(1)  # Brief pause before retry

        logger.info("Redis Stream consumer stopped")

    def stop(self) -> None:
        """Stop consumer loop."""
        self._running = False
        logger.info("Stopping Redis Stream consumer")

    def get_consumer_info(self) -> Dict:
        """Get consumer statistics.

        Returns:
            dict: Consumer info including pending count, lag, etc.
        """
        info = {
            'consumer_name': self.consumer_name,
            'consumer_group': self.consumer_group,
            'trade_streams': len(self._trade_streams),
            'bar_streams': len(self._bar_streams),
            'running': self._running,
        }

        # Get pending counts per stream
        pending_counts = {}
        all_streams = self._trade_streams + self._bar_streams

        for stream in all_streams:
            try:
                pending_info = self.client.xpending(stream, self.consumer_group)
                if pending_info:
                    stream_name = stream.split(':')[-1]  # Extract symbol
                    pending_counts[stream_name] = pending_info.get('pending', 0)
            except redis.RedisError:
                pass

        info['pending_by_stream'] = pending_counts

        return info

    def __repr__(self) -> str:
        """String representation of consumer."""
        return (
            f"RedisStreamConsumer("
            f"group='{self.consumer_group}', "
            f"consumer='{self.consumer_name}', "
            f"trade_streams={len(self._trade_streams)}, "
            f"bar_streams={len(self._bar_streams)})"
        )


if __name__ == "__main__":
    """Test Redis Stream consumer."""
    import sys
    from pathlib import Path

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(project_root))

    print("=" * 60)
    print("RedisStreamConsumer Tests")
    print("=" * 60)

    try:
        # Test 1: Initialize consumer
        print("\n[Test 1] Initialize consumer:")
        consumer = RedisStreamConsumer()
        print(f"  Consumer: {consumer}")
        print("  [OK] Consumer initialized")

        # Test 2: Subscribe to streams
        print("\n[Test 2] Subscribe to streams:")
        test_symbols = ["AAPL", "MSFT"]

        async def mock_trade_handler(trade_data: dict):
            print(f"    Trade: {trade_data.get('symbol')} @ {trade_data.get('price', 0)}")

        async def mock_bar_handler(bar_data: dict):
            print(f"    Bar: {bar_data.get('symbol')} close={bar_data.get('close', 0)}")

        consumer.subscribe_trades(test_symbols, mock_trade_handler)
        consumer.subscribe_bars(test_symbols, mock_bar_handler)
        print("  [OK] Subscribed to streams")

        # Test 3: Publish test data (using publisher)
        print("\n[Test 3] Publish test data:")
        from src.common.cache.redis_stream_publisher import RedisStreamPublisher
        from datetime import datetime

        publisher = RedisStreamPublisher()

        # Publish test trades
        for symbol in test_symbols:
            trade_data = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'trade_id': f'{symbol}-test-1',
                'price': 150.25,
                'size': 100,
                'exchange': 'Q',
                'conditions': ['@'],
                'tape': 'A'
            }
            publisher.publish_trade(symbol, trade_data)

        # Publish test bars
        for symbol in test_symbols:
            bar_data = {
                'symbol': symbol,
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
            publisher.publish_bar(symbol, bar_data)

        print(f"  Published test data for {len(test_symbols)} symbols")
        print("  [OK] Test data published")

        # Test 4: Poll once (non-blocking test)
        print("\n[Test 4] Poll streams once:")

        async def poll_once():
            # Poll trades
            await consumer._poll_streams(consumer._trade_streams, mock_trade_handler)
            # Poll bars
            await consumer._poll_streams(consumer._bar_streams, mock_bar_handler)

        asyncio.run(poll_once())
        print("  [OK] Polling complete")

        # Test 5: Get consumer info
        print("\n[Test 5] Get consumer info:")
        info = consumer.get_consumer_info()
        print(f"  Consumer name: {info['consumer_name']}")
        print(f"  Trade streams: {info['trade_streams']}")
        print(f"  Bar streams: {info['bar_streams']}")
        print(f"  Running: {info['running']}")
        if info['pending_by_stream']:
            print(f"  Pending by stream: {info['pending_by_stream']}")
        print("  [OK] Consumer info retrieved")

        # Cleanup: Delete test streams
        print("\n[Cleanup] Deleting test streams:")
        for symbol in test_symbols:
            publisher.delete_stream(symbol, "trades")
            publisher.delete_stream(symbol, "bars")
        print("  [OK] Test streams deleted")

        print("\n" + "=" * 60)
        print("✓ All RedisStreamConsumer tests passed")
        print("=" * 60)

        print("\nNote: Full consumer loop test skipped (would block indefinitely)")
        print("To test the full consumer loop:")
        print("  1. Run the ingestion script to publish real data")
        print("  2. Run this consumer with await consumer.run()")
        print("  3. Observe messages being processed")

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
      "consumer_group_backend": "backend-consumers",
      "batch_poll_interval_seconds": 10,
      "batch_size": 100
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
