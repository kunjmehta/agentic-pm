"""Dependency-injection container for shared DAO singletons.

Provides a thread-safe ``DAOFactory`` that lazily creates and caches one
instance of each DAO type for the lifetime of the process.  Callers import
the module-level shortcut functions (e.g. ``get_alpaca_dao()``) rather than
constructing DAOs directly.

Usage::

    from src.common.utils.container import get_alpaca_dao, get_analysis_dao

    result = get_alpaca_dao().get_bars(symbol, start, end, timeframe)

FastAPI routers use ``Depends(get_dao_factory)`` and receive the same
singleton without boilerplate DAO construction.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

# Ensure project root is on the path when the module is run directly.
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.dao.alpaca_dao import AlpacaDAO
from src.common.dao.alpha_vantage_dao import AlphaVantageDAO
from src.common.dao.analysis_dao import AnalysisDAO
from src.common.dao.backtest_dao import BacktestDAO
from src.common.dao.orders_dao import OrdersDAO
from src.common.dao.portfolio_dao import PortfolioDAO
from src.common.utils.logger import get_logger

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
        self._alpha_vantage_dao: Optional[AlphaVantageDAO] = None
        self._analysis_dao: Optional[AnalysisDAO] = None
        self._backtest_dao: Optional[BacktestDAO] = None
        self._orders_dao: Optional[OrdersDAO] = None
        self._portfolio_dao: Optional[PortfolioDAO] = None

    # ------------------------------------------------------------------
    # DAO accessors — double-checked locking for thread-safe lazy init
    # ------------------------------------------------------------------

    def get_alpaca_dao(self) -> AlpacaDAO:
        """Return the shared AlpacaDAO instance, creating it if needed."""
        if self._alpaca_dao is None:
            with self._lock:
                if self._alpaca_dao is None:
                    logger.debug("[container] Creating AlpacaDAO singleton")
                    self._alpaca_dao = AlpacaDAO()
        return self._alpaca_dao

    def get_alpha_vantage_dao(self) -> AlphaVantageDAO:
        """Return the shared AlphaVantageDAO instance, creating it if needed."""
        if self._alpha_vantage_dao is None:
            with self._lock:
                if self._alpha_vantage_dao is None:
                    logger.debug("[container] Creating AlphaVantageDAO singleton")
                    self._alpha_vantage_dao = AlphaVantageDAO()
        return self._alpha_vantage_dao

    def get_analysis_dao(self) -> AnalysisDAO:
        """Return the shared AnalysisDAO instance, creating it if needed."""
        if self._analysis_dao is None:
            with self._lock:
                if self._analysis_dao is None:
                    logger.debug("[container] Creating AnalysisDAO singleton")
                    self._analysis_dao = AnalysisDAO()
        return self._analysis_dao

    def get_backtest_dao(self) -> BacktestDAO:
        """Return the shared BacktestDAO instance, creating it if needed."""
        if self._backtest_dao is None:
            with self._lock:
                if self._backtest_dao is None:
                    logger.debug("[container] Creating BacktestDAO singleton")
                    self._backtest_dao = BacktestDAO()
        return self._backtest_dao

    def get_orders_dao(self) -> OrdersDAO:
        """Return the shared OrdersDAO instance, creating it if needed."""
        if self._orders_dao is None:
            with self._lock:
                if self._orders_dao is None:
                    logger.debug("[container] Creating OrdersDAO singleton")
                    self._orders_dao = OrdersDAO()
        return self._orders_dao

    def get_portfolio_dao(self) -> PortfolioDAO:
        """Return the shared PortfolioDAO instance, creating it if needed."""
        if self._portfolio_dao is None:
            with self._lock:
                if self._portfolio_dao is None:
                    logger.debug("[container] Creating PortfolioDAO singleton")
                    self._portfolio_dao = PortfolioDAO()
        return self._portfolio_dao


    def close_all(self) -> None:
        """Close all open DAO connections and reset slots to None.

        Should be called once during application shutdown (e.g. FastAPI
        lifespan teardown or ETL process cleanup).
        """
        _dao_slots = [
            ("_alpaca_dao",        "AlpacaDAO"),
            ("_alpha_vantage_dao", "AlphaVantageDAO"),
            ("_analysis_dao",      "AnalysisDAO"),
            ("_backtest_dao",      "BacktestDAO"),
            ("_orders_dao",        "OrdersDAO"),
            ("_portfolio_dao",     "PortfolioDAO"),
        ]
        with self._lock:
            for attr, name in _dao_slots:
                dao = getattr(self, attr)
                if dao is not None:
                    try:
                        dao.close()
                        logger.debug(f"[container] Closed {name}")
                    except Exception as exc:
                        logger.warning(f"[container] Error closing {name}: {exc}")
                    setattr(self, attr, None)


# ---------------------------------------------------------------------------
# Module-level singleton — one factory per process.
# ---------------------------------------------------------------------------

_factory: DAOFactory = DAOFactory()


def get_dao_factory() -> DAOFactory:
    """Return the process-level DAOFactory singleton.

    Returns:
        Shared DAOFactory instance.
    """
    return _factory


# ---------------------------------------------------------------------------
# Module-level convenience accessors — preferred over factory.get_*() calls
# in non-DI contexts (registry functions, services, ETL).
# ---------------------------------------------------------------------------

def get_alpaca_dao() -> AlpacaDAO:
    """Return the shared AlpacaDAO singleton."""
    return _factory.get_alpaca_dao()


def get_alpha_vantage_dao() -> AlphaVantageDAO:
    """Return the shared AlphaVantageDAO singleton."""
    return _factory.get_alpha_vantage_dao()


def get_analysis_dao() -> AnalysisDAO:
    """Return the shared AnalysisDAO singleton."""
    return _factory.get_analysis_dao()


def get_backtest_dao() -> BacktestDAO:
    """Return the shared BacktestDAO singleton."""
    return _factory.get_backtest_dao()


def get_orders_dao() -> OrdersDAO:
    """Return the shared OrdersDAO singleton."""
    return _factory.get_orders_dao()


def get_portfolio_dao() -> PortfolioDAO:
    """Return the shared PortfolioDAO singleton."""
    return _factory.get_portfolio_dao()


if __name__ == "__main__":
    print("DAOFactory smoke test")
    factory = get_dao_factory()
    dao = factory.get_alpaca_dao()
    print(f"AlpacaDAO: {type(dao).__name__} OK")
    factory.close_all()
    print("close_all OK")
