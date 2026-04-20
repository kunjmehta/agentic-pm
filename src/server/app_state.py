"""Shared mutable server state — API process only.

Single source of truth for all module-level globals that need to be mutated at
startup (by :mod:`src.server.lifespan`) and read at request time (by routers).
Keeping this in its own module avoids circular imports: the lifespan writes
here; routers import this module and read from it by attribute access so that
``patch("src.server.app_state._graph", ...)`` affects all readers.

ETL streaming, archival, and autonomous signal processing globals have been
removed — those concerns now live in their own process entry points under
``src/processes/``.
"""

import asyncio
from pathlib import Path

# ── File-system ────────────────────────────────────────────────────────────────

CONVERSATIONS_DIR = Path("data/conversations")

# ── Runtime state (mutated by lifespan, read-only for routers) ────────────────

_graph = None
_checkpointer = None     # AsyncSqliteSaver instance
_checkpointer_cm = None  # context manager handle for cleanup

# ── Live execution telemetry ───────────────────────────────────────────────────

# Thread-safe pub/sub bus for per-thread execution event queues.
# Use execution_bus.create/release/publish_threadsafe instead of accessing queues directly.
from src.server.services.execution_bus import execution_bus  # noqa: E402

# Reference to the running event loop — stored at startup so executor_node
# (which runs in a ThreadPoolExecutor) can safely call call_soon_threadsafe.
_event_loop: asyncio.AbstractEventLoop | None = None
