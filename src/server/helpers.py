"""FastAPI dependency providers — inject server singletons into route handlers.

Use with FastAPI's ``Depends()`` mechanism for type-safe, testable endpoint
handlers.  All providers also work as plain callables outside of FastAPI
(e.g. in tests or CLI scripts).

Example usage in a router::

    from src.server.helpers import get_graph, get_alpaca_dao
    from fastapi import Depends

    @router.post("/v1/query")
    async def query_endpoint(
        request: QueryRequest,
        graph=Depends(get_graph),
        dao=Depends(get_alpaca_dao),
    ):
        ...
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from typing import Callable, Dict

from fastapi import HTTPException

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.container import DAOFactory, get_dao_factory
from src.common.dao.alpaca_dao import AlpacaDAO
from src.common.dao.orders_dao import OrdersDAO
from src.common.dao.strategy_dao import StrategyDAO
from src.server.state_manager import ApplicationState, get_app_state


# ── Application state ─────────────────────────────────────────────────────────


def get_state() -> ApplicationState:
    """Return the typed application state adapter.

    Returns:
        ApplicationState backed by app_state module globals.
    """
    return get_app_state()


# ── Graph ─────────────────────────────────────────────────────────────────────


def get_graph():
    """Return the compiled LangGraph instance.

    Returns:
        Compiled LangGraph.

    Raises:
        HTTPException: 503 if the graph has not yet been initialised by lifespan.
    """
    state = get_app_state()
    if state.graph is None:
        raise HTTPException(
            status_code=503,
            detail="Agent graph not yet initialized. Retry after server startup completes.",
        )
    return state.graph


# ── Execution bus ─────────────────────────────────────────────────────────────


def get_execution_bus() -> Dict[str, asyncio.Queue]:
    """Return the per-thread execution event queue dict.

    Returns:
        Dict mapping thread_id → asyncio.Queue (owned by execution_bus).
    """
    return get_app_state().execution_queues


# ── Event loop ────────────────────────────────────────────────────────────────


def get_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the server event loop reference for cross-thread publishing.

    Returns:
        The event loop stored at startup, or None if not yet set.
    """
    return get_app_state().event_loop


# ── DAO factory ───────────────────────────────────────────────────────────────


def get_factory() -> DAOFactory:
    """Return the process-level DAOFactory.

    Returns:
        Shared DAOFactory instance.
    """
    return get_dao_factory()


# ── DAO providers (for FastAPI Depends) ───────────────────────────────────────


def get_alpaca_dao() -> AlpacaDAO:
    """Return the shared AlpacaDAO singleton.

    Returns:
        Cached AlpacaDAO instance from the global DAOFactory.
    """
    return get_dao_factory().get_alpaca_dao()


def get_strategy_dao() -> StrategyDAO:
    """Return the shared StrategyDAO singleton.

    Returns:
        Cached StrategyDAO instance from the global DAOFactory.
    """
    return get_dao_factory().get_strategy_dao()


def get_orders_dao() -> OrdersDAO:
    """Return the shared OrdersDAO singleton.

    Returns:
        Cached OrdersDAO instance from the global DAOFactory.
    """
    return get_dao_factory().get_orders_dao()


# ── Function registry ─────────────────────────────────────────────────────────


def get_function_registry() -> Dict[str, Callable]:
    """Return the available registered functions dict.

    This is the single canonical import point for ``AVAILABLE_FUNCTIONS`` so
    routers do not import the global dict directly.

    Returns:
        Dict mapping function name → callable.
    """
    from src.server.registry.functions import AVAILABLE_FUNCTIONS
    return AVAILABLE_FUNCTIONS


# ── Alpaca historical data client ─────────────────────────────────────────────

_alpaca_client_lock = threading.Lock()
_alpaca_client = None


def get_alpaca_client():
    """Return a cached :class:`StockHistoricalDataClient` instance.

    Thread-safe lazy singleton.  Creates the client on first call; reuses it
    for all subsequent calls.

    Returns:
        :class:`alpaca.data.historical.StockHistoricalDataClient` instance.

    Raises:
        HTTPException: 503 if Alpaca credentials are missing.
    """
    global _alpaca_client
    if _alpaca_client is None:
        with _alpaca_client_lock:
            if _alpaca_client is None:
                from alpaca.data.historical import StockHistoricalDataClient
                from src.common.utils import secrets

                api_key = secrets.get("alpaca.api_key")
                secret_key = secrets.get("alpaca.secret_key")
                if not api_key or not secret_key:
                    raise HTTPException(
                        status_code=503,
                        detail="Alpaca API credentials not configured.",
                    )
                _alpaca_client = StockHistoricalDataClient(api_key, secret_key)
    return _alpaca_client
