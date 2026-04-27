"""Typed interface for server-wide application runtime state.

:mod:`src.server.app_state` holds the concrete module-level variables that
lifespan mutates.  This module wraps that concrete state behind a typed
:class:`ApplicationState` protocol so that routers and services can receive it
via FastAPI ``Depends(get_app_state)`` without directly importing a global
module.

Usage (in a router)::

    from fastapi import Depends
    from src.server.state_manager import ApplicationState, get_app_state

    @router.get("/health")
    async def health(state: ApplicationState = Depends(get_app_state)):
        return {"graph_ready": state.graph is not None}

Testing::

    from src.server.state_manager import ApplicationState
    # patch app_state attributes as before — the protocol is transparent.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, runtime_checkable

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.server.services.execution_bus import execution_bus as _execution_bus


@runtime_checkable
class ApplicationState(Protocol):
    """Read-only typed view of the server runtime state.

    All attributes are set by :func:`src.server.lifespan.lifespan` at startup
    and should be treated as read-only by routers.
    """

    @property
    def graph(self) -> Any:
        """Compiled LangGraph instance (``None`` until startup completes)."""
        ...

    @property
    def checkpointer(self) -> Any:
        """AsyncSqliteSaver — LangGraph checkpoint persistence."""
        ...

    @property
    def event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Running event loop reference for cross-thread callbacks."""
        ...

    @property
    def execution_queues(self) -> Dict[str, asyncio.Queue]:
        """Per-thread execution event queues (owned by execution_bus)."""
        ...

class _AppStateAdapter:
    """Adapts :mod:`src.server.app_state` globals to the :class:`ApplicationState` protocol.

    This thin wrapper avoids leaking ``app_state``'s raw module attributes while
    keeping the implementation in one place.  The adapter reads from the module
    dynamically so any mutation by lifespan is immediately visible.
    """

    @property
    def graph(self) -> Any:
        """Return the compiled LangGraph from app_state."""
        import src.server.app_state as _state
        return _state._graph

    @property
    def checkpointer(self) -> Any:
        """Return the AsyncSqliteSaver from app_state."""
        import src.server.app_state as _state
        return _state._checkpointer

    @property
    def event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Return the stored event loop reference from app_state."""
        import src.server.app_state as _state
        return _state._event_loop

    @property
    def execution_queues(self) -> Dict[str, asyncio.Queue]:
        """Return per-thread execution queues from the execution_bus."""
        return _execution_bus._queues  # type: ignore[attr-defined]

# Single process-level adapter instance.
_adapter = _AppStateAdapter()


def get_app_state() -> ApplicationState:
    """Return the typed application state adapter.

    This is the canonical FastAPI dependency for accessing server state.
    It reads live from :mod:`src.server.app_state` on every attribute access,
    so lifespan mutations are always visible.

    Returns:
        ApplicationState adapter backed by app_state module globals.
    """
    return _adapter  # type: ignore[return-value]


if __name__ == "__main__":
    """Smoke test: verify protocol compliance and attribute access."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    print("=" * 60)
    print("src/server/state_manager.py smoke test")
    print("=" * 60)

    state = get_app_state()

    # Verify protocol compliance
    assert isinstance(state, ApplicationState), "adapter must satisfy ApplicationState protocol"
    print("  [OK] get_app_state() returns ApplicationState-compliant object")

    # Verify all properties are accessible (values will be None before lifespan)
    _ = state.graph
    print(f"  [OK] state.graph = {state.graph!r}")
    _ = state.checkpointer
    print(f"  [OK] state.checkpointer = {state.checkpointer!r}")
    _ = state.event_loop
    print(f"  [OK] state.event_loop = {state.event_loop!r}")
    _ = state.execution_queues
    print(f"  [OK] state.execution_queues = {type(state.execution_queues).__name__}")
    _ = state.signal_aggregator
    print(f"  [OK] state.signal_aggregator = {state.signal_aggregator!r}")

    # Verify same instance on repeated calls
    s1 = get_app_state()
    s2 = get_app_state()
    assert s1 is s2
    print("  [OK] get_app_state() is idempotent (same adapter)")

    print("\n[ALL OK] src/server/state_manager.py smoke test passed")
    print("=" * 60)
