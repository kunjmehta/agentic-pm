"""Indicator computation queue using Redis Streams.

This module provides a queue for indicator computation jobs using Redis Streams
with consumer groups for reliable delivery and parallel worker processing.

Usage:
    from src.common.cache.indicator_queue import IndicatorQueue

    # Enqueue indicator computation job
    queue = IndicatorQueue()
    queue.enqueue(symbol="AAPL", timeframe="1Min", timestamp="2024-03-20T10:30:00Z")

    # Worker: dequeue and process jobs
    jobs = queue.dequeue_batch(count=10, block_ms=5000)
    for job in jobs:
        compute_indicators(job['symbol'], job['timeframe'])
        queue.ack(job['message_id'])
"""

import asyncio
import os
import socket
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import msgpack
import redis

from src.common.cache.redis_manager import RedisManager
from src.common.utils.config_loader import config
from src.common.utils.logger import get_logger

logger = get_logger(__name__)


class IndicatorQueue:
    """Queue for indicator computation jobs using Redis Streams.

    Uses consumer groups for reliable delivery and supports multiple
    parallel workers for horizontal scaling.
    """

    def __init__(self):
        """Initialize indicator queue.

        Raises:
            ValueError: If Redis or queue configuration is missing
        """
        # Get Redis client
        self.redis_mgr = RedisManager()
        self.client = self.redis_mgr.get_client()

        # Load queue configuration
        queue_config = config.get("redis.indicator_jobs", default={})
        if not queue_config:
            raise ValueError("redis.indicator_jobs configuration missing in config.json")

        self.stream_key = queue_config.get("stream_key", "stream:indicator_jobs")
        self.consumer_group = queue_config.get("consumer_group", "indicator-workers")

        # Generate unique consumer name: hostname-pid
        self.consumer_name = f"{socket.gethostname()}-{os.getpid()}"

        # Ensure consumer group exists
        self._ensure_consumer_group()

        logger.info(
            f"IndicatorQueue initialized: stream={self.stream_key}, "
            f"group={self.consumer_group}, consumer={self.consumer_name}"
        )

    def _ensure_consumer_group(self) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            self.client.xgroup_create(
                name=self.stream_key,
                groupname=self.consumer_group,
                id='0',  # Start from beginning
                mkstream=True  # Create stream if not exists
            )
            logger.info(f"Created consumer group '{self.consumer_group}' for {self.stream_key}")

        except redis.exceptions.ResponseError as e:
            if 'BUSYGROUP' in str(e):
                # Group already exists
                logger.debug(f"Consumer group '{self.consumer_group}' already exists")
            else:
                raise

    def enqueue(
        self,
        symbol: str,
        timeframe: str,
        timestamp: Optional[str] = None
    ) -> Optional[str]:
        """Enqueue indicator computation job.

        Args:
            symbol: Stock ticker symbol (e.g., "AAPL")
            timeframe: Bar timeframe (e.g., "1Min", "1Hour", "1Day")
            timestamp: Optional ISO timestamp of the bar that triggered computation

        Returns:
            str: Stream entry ID if successful, None otherwise

        Example:
            >>> queue = IndicatorQueue()
            >>> queue.enqueue("AAPL", "1Min", "2024-03-20T10:30:00Z")
            '1710932400000-0'
        """
        # Build job data
        job_data = {
            'symbol': symbol.upper(),
            'timeframe': timeframe,
            'timestamp': timestamp or datetime.now(timezone.utc).isoformat(),
            'queued_at': datetime.now(timezone.utc).isoformat()
        }

        try:
            # Serialize with msgpack
            serialized = msgpack.packb(job_data, use_bin_type=True)

            # Add to stream
            entry_id = self.client.xadd(
                name=self.stream_key,
                fields={'data': serialized},
                id='*'  # Auto-generate ID
            )

            logger.debug(
                f"Enqueued indicator job: {symbol} {timeframe} "
                f"(entry_id: {entry_id.decode() if isinstance(entry_id, bytes) else entry_id})"
            )

            return entry_id.decode() if isinstance(entry_id, bytes) else entry_id

        except redis.RedisError as e:
            logger.error(f"Failed to enqueue indicator job: {e}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error enqueuing indicator job: {e}")
            return None

    def dequeue_batch(
        self,
        count: int = 10,
        block_ms: int = 5000
    ) -> List[Dict]:
        """Dequeue batch of indicator jobs (blocking).

        Args:
            count: Maximum number of jobs to dequeue
            block_ms: Block timeout in milliseconds (0 for non-blocking)

        Returns:
            List of job dictionaries with 'message_id' field for acknowledgment

        Example:
            >>> queue = IndicatorQueue()
            >>> jobs = queue.dequeue_batch(count=10, block_ms=5000)
            >>> for job in jobs:
            ...     compute_indicators(job['symbol'], job['timeframe'])
            ...     queue.ack(job['message_id'])
        """
        try:
            # XREADGROUP to fetch new messages
            results = self.client.xreadgroup(
                groupname=self.consumer_group,
                consumername=self.consumer_name,
                streams={self.stream_key: '>'},  # '>' = only new messages
                count=count,
                block=block_ms if block_ms > 0 else None
            )

            if not results:
                return []

            # Parse results
            jobs = []
            for stream_name, messages in results:
                for message_id, fields in messages:
                    try:
                        # Deserialize msgpack payload
                        payload = msgpack.unpackb(fields[b'data'], raw=False)
                        payload['message_id'] = message_id.decode() if isinstance(message_id, bytes) else message_id
                        jobs.append(payload)

                    except Exception as e:
                        logger.error(f"Failed to deserialize job {message_id}: {e}")
                        # Still ack to avoid reprocessing
                        self.ack(message_id)

            if jobs:
                logger.debug(f"Dequeued {len(jobs)} indicator jobs")

            return jobs

        except redis.RedisError as e:
            logger.error(f"Failed to dequeue indicator jobs: {e}")
            return []

        except Exception as e:
            logger.error(f"Unexpected error dequeuing indicator jobs: {e}")
            return []

    def ack(self, message_id: str) -> bool:
        """Acknowledge processed job.

        Args:
            message_id: Stream entry ID from job dict

        Returns:
            bool: True if acknowledged successfully

        Example:
            >>> queue.ack('1710932400000-0')
            True
        """
        try:
            self.client.xack(self.stream_key, self.consumer_group, message_id)
            logger.debug(f"Acknowledged job: {message_id}")
            return True

        except redis.RedisError as e:
            logger.error(f"Failed to acknowledge job {message_id}: {e}")
            return False

    def recover_pending(self, idle_time_ms: int = 60000) -> List[Dict]:
        """Recover pending messages that failed or were abandoned.

        Reclaims messages that have been idle for longer than idle_time_ms.
        Useful for startup recovery after crashes.

        Args:
            idle_time_ms: Minimum idle time in milliseconds before reclaiming

        Returns:
            List of recovered job dictionaries

        Example:
            >>> queue = IndicatorQueue()
            >>> recovered_jobs = queue.recover_pending(idle_time_ms=60000)
            >>> for job in recovered_jobs:
            ...     compute_indicators(job['symbol'], job['timeframe'])
            ...     queue.ack(job['message_id'])
        """
        try:
            # Get pending messages for this consumer
            pending = self.client.xpending_range(
                name=self.stream_key,
                groupname=self.consumer_group,
                min='-',
                max='+',
                count=100,
                consumername=self.consumer_name
            )

            if not pending:
                logger.debug("No pending messages to recover")
                return []

            # Claim idle messages
            message_ids = [p['message_id'] for p in pending]
            claimed = self.client.xclaim(
                name=self.stream_key,
                groupname=self.consumer_group,
                consumername=self.consumer_name,
                min_idle_time=idle_time_ms,
                message_ids=message_ids
            )

            # Parse claimed messages
            jobs = []
            for message_id, fields in claimed:
                try:
                    payload = msgpack.unpackb(fields[b'data'], raw=False)
                    payload['message_id'] = message_id.decode() if isinstance(message_id, bytes) else message_id
                    jobs.append(payload)

                except Exception as e:
                    logger.error(f"Failed to deserialize recovered job {message_id}: {e}")
                    self.ack(message_id)

            if jobs:
                logger.warning(f"Recovered {len(jobs)} pending indicator jobs")

            return jobs

        except redis.RedisError as e:
            logger.error(f"Failed to recover pending jobs: {e}")
            return []

        except Exception as e:
            logger.error(f"Unexpected error recovering pending jobs: {e}")
            return []

    def get_queue_info(self) -> Dict:
        """Get queue statistics.

        Returns:
            dict: Queue info including length, groups, pending count

        Example:
            >>> queue = IndicatorQueue()
            >>> info = queue.get_queue_info()
            >>> print(f"Pending jobs: {info['length']}")
        """
        try:
            stream_info = self.client.xinfo_stream(self.stream_key)
            pending_info = self.client.xpending(self.stream_key, self.consumer_group)

            return {
                'stream_length': stream_info.get(b'length', 0),
                'first_entry_id': stream_info.get(b'first-entry'),
                'last_entry_id': stream_info.get(b'last-entry'),
                'groups': stream_info.get(b'groups', 0),
                'pending_count': pending_info.get('pending', 0) if pending_info else 0,
            }

        except redis.RedisError as e:
            logger.error(f"Failed to get queue info: {e}")
            return {}

    def purge_queue(self) -> bool:
        """Delete all jobs from queue (destructive operation).

        Returns:
            bool: True if purged successfully

        Warning:
            This deletes the entire stream including all pending jobs!
        """
        try:
            deleted = self.client.delete(self.stream_key)
            logger.warning(f"Purged indicator queue: {bool(deleted)}")

            # Recreate consumer group
            self._ensure_consumer_group()

            return bool(deleted)

        except redis.RedisError as e:
            logger.error(f"Failed to purge queue: {e}")
            return False

    def __repr__(self) -> str:
        """String representation of queue."""
        return (
            f"IndicatorQueue("
            f"stream='{self.stream_key}', "
            f"group='{self.consumer_group}', "
            f"consumer='{self.consumer_name}')"
        )


if __name__ == "__main__":
    """Test indicator queue."""
    import sys
    from pathlib import Path

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(project_root))

    print("=" * 60)
    print("IndicatorQueue Tests")
    print("=" * 60)

    try:
        # Test 1: Initialize queue
        print("\n[Test 1] Initialize queue:")
        queue = IndicatorQueue()
        print(f"  Queue: {queue}")
        print("  [OK] Queue initialized")

        # Test 2: Enqueue jobs
        print("\n[Test 2] Enqueue indicator jobs:")
        symbols = ["AAPL", "MSFT", "GOOGL"]
        timeframes = ["1Min", "1Hour", "1Day"]

        enqueued_ids = []
        for symbol in symbols:
            for timeframe in timeframes:
                entry_id = queue.enqueue(symbol, timeframe)
                assert entry_id is not None, f"Failed to enqueue {symbol} {timeframe}"
                enqueued_ids.append(entry_id)

        print(f"  Enqueued {len(enqueued_ids)} jobs")
        print("  [OK] Jobs enqueued successfully")

        # Test 3: Get queue info
        print("\n[Test 3] Get queue info:")
        info = queue.get_queue_info()
        print(f"  Stream length: {info.get('stream_length', 0)}")
        print(f"  Pending count: {info.get('pending_count', 0)}")
        assert info.get('stream_length', 0) >= len(enqueued_ids), "Queue should have jobs"
        print("  [OK] Queue info retrieved")

        # Test 4: Dequeue jobs
        print("\n[Test 4] Dequeue jobs:")
        jobs = queue.dequeue_batch(count=5, block_ms=1000)
        assert len(jobs) > 0, "Should dequeue jobs"
        print(f"  Dequeued {len(jobs)} jobs")
        for job in jobs[:3]:
            print(f"    - {job['symbol']} {job['timeframe']}")
        print("  [OK] Jobs dequeued successfully")

        # Test 5: Acknowledge jobs
        print("\n[Test 5] Acknowledge jobs:")
        for job in jobs:
            ack_success = queue.ack(job['message_id'])
            assert ack_success, f"Failed to ack {job['message_id']}"
        print(f"  Acknowledged {len(jobs)} jobs")
        print("  [OK] Jobs acknowledged")

        # Test 6: Dequeue remaining
        print("\n[Test 6] Dequeue remaining jobs:")
        remaining_jobs = queue.dequeue_batch(count=10, block_ms=1000)
        print(f"  Dequeued {len(remaining_jobs)} remaining jobs")
        for job in remaining_jobs:
            queue.ack(job['message_id'])
        print("  [OK] All jobs processed")

        # Test 7: Pending recovery
        print("\n[Test 7] Test pending recovery:")
        # Enqueue a job and don't ack it
        test_id = queue.enqueue("TEST", "1Min")
        unacked_jobs = queue.dequeue_batch(count=1, block_ms=100)
        # Don't ack, so it remains pending

        # Try to recover (won't find it yet due to idle time)
        recovered = queue.recover_pending(idle_time_ms=60000)
        print(f"  Recovered {len(recovered)} pending jobs (should be 0 - not idle long enough)")

        # Ack the test job to clean up
        if unacked_jobs:
            queue.ack(unacked_jobs[0]['message_id'])
        print("  [OK] Pending recovery tested")

        # Test 8: Queue info after processing
        print("\n[Test 8] Final queue info:")
        final_info = queue.get_queue_info()
        print(f"  Stream length: {final_info.get('stream_length', 0)}")
        print(f"  Pending count: {final_info.get('pending_count', 0)}")
        print("  [OK] Queue info retrieved")

        # Cleanup
        print("\n[Cleanup] Purging queue:")
        queue.purge_queue()
        print("  [OK] Queue purged")

        print("\n" + "=" * 60)
        print("✓ All IndicatorQueue tests passed")
        print("=" * 60)

    except ValueError as e:
        print(f"\n✗ Configuration error: {e}")
        print("\nMake sure config.json has redis.indicator_jobs section:")
        print("""
{
  "redis": {
    "enabled": true,
    "indicator_jobs": {
      "stream_key": "stream:indicator_jobs",
      "consumer_group": "indicator-workers",
      "worker_count": 2
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
