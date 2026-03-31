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
_data_coordinator = None
_stream_task: asyncio.Task | None = None
_archival_task: asyncio.Task | None = None
