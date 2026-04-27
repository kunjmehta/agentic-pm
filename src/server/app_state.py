"""Shared mutable server state.

Single source of truth for all module-level globals that need to be mutated at
startup (by :mod:`src.semi_auto.lifespan`) and read at request time (by
routers).  Keeping this in its own module avoids circular imports: the lifespan
writes here; routers import this module and read from it by attribute access so
that ``patch("src.semi_auto.app_state._graph", ...)`` affects all readers.
"""

import asyncio
from pathlib import Path

# ── File-system ────────────────────────────────────────────────────────────────

CONVERSATIONS_DIR = Path("data/conversations")

# ── Archival constants ─────────────────────────────────────────────────────────

_ARCHIVAL_INTERVAL_MINUTES: int = 15
_ARCHIVAL_CUTOFF_MINUTES: int = 120  # archive rows older than 2 hours

# ── Runtime state (mutated by lifespan, read-only for routers) ────────────────

_graph = None
_checkpointer = None       # AsyncSqliteSaver instance
_checkpointer_cm = None    # context manager handle for cleanup
_data_coordinator = None
_stream_task: asyncio.Task | None = None
_archival_task: asyncio.Task | None = None
_autonomous_task: asyncio.Task | None = None
_signal_aggregator = None

# ── Live execution telemetry ───────────────────────────────────────────────────

# Per-thread asyncio queues for streaming execution progress events.
# Keys: thread_id → asyncio.Queue[dict | str]
# Values are SSE event dicts; sentinel "__done__" signals end of stream.
_execution_queues: dict[str, asyncio.Queue] = {}

# Reference to the running event loop — stored at startup so executor_node
# (which runs in a ThreadPoolExecutor) can safely call call_soon_threadsafe.
_event_loop: asyncio.AbstractEventLoop | None = None
