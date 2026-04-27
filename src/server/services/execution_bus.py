"""Thread-safe pub/sub bus for streaming execution telemetry to SSE endpoints.

Replaces the raw ``app_state._execution_queues`` dict and associated
``app_state._event_loop`` access, giving callers a well-defined interface
and making thread-safety semantics explicit.

Usage::

    # In an async endpoint (creates queue, waits on it):
    from src.server.services.execution_bus import execution_bus
    q = execution_bus.create(thread_id)
    try:
        while True:
            item = await q.get()
            ...
    finally:
        execution_bus.release(thread_id)

    # In a ThreadPoolExecutor worker (publishes events):
    from src.server.services.execution_bus import execution_bus
    execution_bus.publish_threadsafe(thread_id, event, loop)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maximum events buffered per thread before older events are dropped.
# At ~200 bytes per event dict this caps memory at ~200 KB per active thread.
_DEFAULT_MAXSIZE: int = 1_000


class ExecutionBus:
    """Manages per-thread queues for streaming task execution events.

    One :class:`asyncio.Queue` exists per active thread.  Async SSE
    generators consume from the queue; executor thread-pool tasks produce
    to it via :meth:`publish_threadsafe`.

    Queues are bounded (``maxsize=_DEFAULT_MAXSIZE``) to prevent unbounded
    memory growth when a slow or disconnected SSE consumer stops draining.
    Events published to a full queue are dropped with a warning log.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}

    def create(self, thread_id: str, maxsize: int = _DEFAULT_MAXSIZE) -> asyncio.Queue:
        """Create and register a bounded queue for *thread_id*.

        Args:
            thread_id: LangGraph thread identifier.
            maxsize: Maximum number of events buffered before drops occur.
                Defaults to :data:`_DEFAULT_MAXSIZE`.

        Returns:
            New bounded :class:`asyncio.Queue` for this thread.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._queues[thread_id] = q
        return q

    def get_or_create(self, thread_id: str, maxsize: int = _DEFAULT_MAXSIZE) -> asyncio.Queue:
        """Return existing queue for *thread_id*, creating one if absent.

        Args:
            thread_id: LangGraph thread identifier.
            maxsize: Passed to :meth:`create` when a new queue is needed.

        Returns:
            :class:`asyncio.Queue` for this thread.
        """
        if thread_id not in self._queues:
            return self.create(thread_id, maxsize=maxsize)
        return self._queues[thread_id]

    def get(self, thread_id: str) -> asyncio.Queue | None:
        """Return the queue for *thread_id*, or None if not registered.

        Args:
            thread_id: LangGraph thread identifier.

        Returns:
            Queue or None.
        """
        return self._queues.get(thread_id)

    def release(self, thread_id: str) -> None:
        """Remove the queue for *thread_id* after the SSE stream closes.

        Args:
            thread_id: LangGraph thread identifier.
        """
        self._queues.pop(thread_id, None)

    def publish_threadsafe(
        self,
        thread_id: str,
        event: Any,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Post *event* to the queue from a ThreadPoolExecutor worker.

        Uses ``call_soon_threadsafe`` to cross the thread boundary safely.
        If the queue is full the event is silently dropped and a warning is
        logged — the SSE consumer is the bottleneck, not the producer.
        Silently no-ops if there is no registered queue for *thread_id* or
        if the loop is not running.

        Args:
            thread_id: LangGraph thread identifier.
            event: Event dict (or sentinel string) to publish.
            loop: The running event loop (``_state._event_loop``).
        """
        q = self._queues.get(thread_id)
        if q is None or loop is None or not loop.is_running():
            return

        def _safe_put(q: asyncio.Queue = q, event: Any = event) -> None:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    f"[execution_bus] queue full for thread_id={thread_id!r}, "
                    "dropping event — SSE consumer may be too slow or disconnected"
                )

        loop.call_soon_threadsafe(_safe_put)

    def __contains__(self, thread_id: str) -> bool:
        return thread_id in self._queues


# Module-level singleton — initialized once, shared across the process.
execution_bus = ExecutionBus()


if __name__ == "__main__":
    """Smoke test: verify ExecutionBus construction and basic operations."""
    import asyncio as _asyncio

    print("=" * 60)
    print("services/execution_bus.py smoke test")
    print("=" * 60)

    async def _test():
        bus = ExecutionBus()

        # create + get
        q = bus.create("thread-1")
        assert bus.get("thread-1") is q
        print("  [OK]  create / get")

        # Queue is bounded
        assert q.maxsize == _DEFAULT_MAXSIZE
        print(f"  [OK]  queue maxsize={_DEFAULT_MAXSIZE}")

        # get_or_create: existing
        q2 = bus.get_or_create("thread-1")
        assert q2 is q
        print("  [OK]  get_or_create (existing)")

        # get_or_create: new
        q3 = bus.get_or_create("thread-2")
        assert bus.get("thread-2") is q3
        print("  [OK]  get_or_create (new)")

        # __contains__
        assert "thread-1" in bus
        assert "thread-x" not in bus
        print("  [OK]  __contains__")

        # release
        bus.release("thread-1")
        assert bus.get("thread-1") is None
        print("  [OK]  release")

        # QueueFull is handled gracefully — fill beyond maxsize
        tiny_bus = ExecutionBus()
        tq = tiny_bus.create("tiny", maxsize=2)
        tq.put_nowait("a")
        tq.put_nowait("b")
        assert tq.full()
        loop = _asyncio.get_event_loop()
        # publish_threadsafe must not raise even when full
        tiny_bus.publish_threadsafe("tiny", "overflow", loop)
        await _asyncio.sleep(0)  # let call_soon_threadsafe execute
        assert tq.qsize() == 2, "Queue must still hold exactly 2 items (overflow dropped)"
        print("  [OK]  QueueFull handled gracefully — overflow event dropped")

        # Module-level singleton exists
        assert isinstance(execution_bus, ExecutionBus)
        print("  [OK]  module-level execution_bus singleton")

    _asyncio.run(_test())

    print("\n[ALL OK] services/execution_bus.py smoke test passed")
    print("=" * 60)
