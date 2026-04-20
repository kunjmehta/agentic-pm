"""Dependency-injection container for shared DAO singletons.

Provides a thread-safe ``DAOFactory`` that lazily creates and caches one
instance of each DAO type for the lifetime of the process.  Callers import
``get_dao_factory()`` and call ``factory.get_alpaca_dao()`` rather than
constructing DAOs directly.

Usage::

    from src.common.container import get_dao_factory

    factory = get_dao_factory()
    dao = factory.get_alpaca_dao()
    result = dao.some_query()

FastAPI routers use ``Depends(get_dao_factory)`` and receive the same
singleton without boilerplate DAO construction.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

# Ensure project root is on the path when the module is run directly.
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.dao.alpaca_dao import AlpacaDAO
from src.common.dao.orders_dao import OrdersDAO
from src.common.dao.strategy_dao import StrategyDAO
from src.common.utils import get_logger

logger = get_logger(__name__)


class DAOFactory:
    """Thread-safe lazy singleton factory for all DAO types.

    All ``get_*`` methods return the same cached instance on every call.
    Call ``close_all()`` during application shutdown to release DB connections.
    """

    def __init__(self) -> None:
        """Initialise the factory with empty DAO slots."""
        self._lock: threading.Lock = threading.Lock()
        self._alpaca_dao: Optional[AlpacaDAO] = None
        self._strategy_dao: Optional[StrategyDAO] = None
        self._orders_dao: Optional[OrdersDAO] = None

    def get_alpaca_dao(self) -> AlpacaDAO:
        """Return the shared AlpacaDAO instance, creating it if needed.

        Returns:
            Singleton AlpacaDAO connected to the default DB path.
        """
        if self._alpaca_dao is None:
            with self._lock:
                if self._alpaca_dao is None:
                    logger.debug("[container] Creating AlpacaDAO singleton")
                    self._alpaca_dao = AlpacaDAO()
        return self._alpaca_dao

    def get_strategy_dao(self) -> StrategyDAO:
        """Return the shared StrategyDAO instance, creating it if needed.

        Returns:
            Singleton StrategyDAO connected to the default DB path.
        """
        if self._strategy_dao is None:
            with self._lock:
                if self._strategy_dao is None:
                    logger.debug("[container] Creating StrategyDAO singleton")
                    self._strategy_dao = StrategyDAO()
        return self._strategy_dao

    def get_orders_dao(self) -> OrdersDAO:
        """Return the shared OrdersDAO instance, creating it if needed.

        Returns:
            Singleton OrdersDAO connected to the default DB path.
        """
        if self._orders_dao is None:
            with self._lock:
                if self._orders_dao is None:
                    logger.debug("[container] Creating OrdersDAO singleton")
                    self._orders_dao = OrdersDAO()
        return self._orders_dao

    def close_all(self) -> None:
        """Close all open DAO connections and reset slots to None.

        Should be called once during application shutdown (e.g. FastAPI
        lifespan teardown or ETL process cleanup).
        """
        with self._lock:
            for attr, name in [
                ("_alpaca_dao", "AlpacaDAO"),
                ("_strategy_dao", "StrategyDAO"),
                ("_orders_dao", "OrdersDAO"),
            ]:
                dao = getattr(self, attr)
                if dao is not None:
                    try:
                        dao.close()
                        logger.debug(f"[container] Closed {name}")
                    except Exception as exc:
                        logger.warning(f"[container] Error closing {name}: {exc}")
                    setattr(self, attr, None)


# Module-level singleton — one factory per process.
_factory: DAOFactory = DAOFactory()


def get_dao_factory() -> DAOFactory:
    """Return the process-level DAOFactory singleton.

    Returns:
        Shared DAOFactory instance.
    """
    return _factory


if __name__ == "__main__":
    """Smoke test: verify factory creates singletons and close_all works."""
    print("=" * 60)
    print("src/common/container.py smoke test")
    print("=" * 60)

    factory = get_dao_factory()

    # Verify singleton identity
    dao1 = factory.get_alpaca_dao()
    dao2 = factory.get_alpaca_dao()
    assert dao1 is dao2, "AlpacaDAO must be a singleton"
    print(f"  [OK] AlpacaDAO singleton: {type(dao1).__name__}")

    sdao1 = factory.get_strategy_dao()
    sdao2 = factory.get_strategy_dao()
    assert sdao1 is sdao2, "StrategyDAO must be a singleton"
    print(f"  [OK] StrategyDAO singleton: {type(sdao1).__name__}")

    odao1 = factory.get_orders_dao()
    odao2 = factory.get_orders_dao()
    assert odao1 is odao2, "OrdersDAO must be a singleton"
    print(f"  [OK] OrdersDAO singleton: {type(odao1).__name__}")

    # Verify close_all resets slots
    factory.close_all()
    assert factory._alpaca_dao is None
    assert factory._strategy_dao is None
    assert factory._orders_dao is None
    print("  [OK] close_all() reset all DAO slots")

    # Verify re-creation after close
    dao_new = factory.get_alpaca_dao()
    assert dao_new is not dao1, "Should create fresh instance after close"
    print("  [OK] Fresh AlpacaDAO created after close_all()")
    factory.close_all()

    # Verify get_dao_factory returns the module-level singleton
    f1 = get_dao_factory()
    f2 = get_dao_factory()
    assert f1 is f2
    print("  [OK] get_dao_factory() returns process-level singleton")

    print("\n[ALL OK] src/common/container.py smoke test passed")
    print("=" * 60)
