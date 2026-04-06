"""Health check router — GET /v1/health, GET /v1/health/detailed.

Endpoints:
    GET /v1/health           - Basic liveness check (graph readiness)
    GET /v1/health/detailed  - Comprehensive health check (graph, registry, all 4 databases)

Database checks:
    - portfolio_db: data/portfolio.duckdb (snapshots, positions, orders)
    - market_data_db: data/market_data.duckdb (bars, trades, watchlist)
    - analysis_db: data/analysis.duckdb (strategy metrics)
    - backtest_db: data/backtest.duckdb (backtest results)
    - checkpoint_db: data/checkpoints.db (graph state persistence)
"""

from datetime import datetime, timezone

from fastapi import APIRouter

import src.server.app_state as _state
from src.common.utils import get_logger
from src.server.models.endpoints import DetailedHealthResponse, HealthResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health():
    """Basic liveness check."""
    return {
        "status": "ok",
        "graph_ready": _state._graph is not None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/detailed", response_model=DetailedHealthResponse)
async def health_detailed():
    """Per-component health check (graph, registry, all databases)."""
    components: dict = {}

    # Graph readiness
    components["graph"] = {"status": "ok" if _state._graph is not None else "not_ready"}

    # Function registry
    try:
        from src.server.registry.functions import AVAILABLE_FUNCTIONS
        components["registry"] = {"status": "ok", "functions": len(AVAILABLE_FUNCTIONS)}
    except Exception as exc:
        components["registry"] = {"status": "error", "error": str(exc)}

    # Portfolio database
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        snap = dao.get_latest_snapshot()
        has_snapshot = snap is not None
        dao.close()
        components["portfolio_db"] = {
            "status": "ok",
            "latest_snapshot": has_snapshot,
            "path": "data/portfolio.duckdb"
        }
    except Exception as exc:
        components["portfolio_db"] = {"status": "error", "error": str(exc)}

    # Market data database
    try:
        from src.common.dao.alpaca_dao import AlpacaDAO
        dao = AlpacaDAO()
        # Check if key tables exist
        has_watchlist = dao.table_exists("watchlist")
        has_bars = dao.table_exists("market_bars")
        has_trades = dao.table_exists("historical_trades")
        dao.close()
        components["market_data_db"] = {
            "status": "ok",
            "tables": {
                "watchlist": has_watchlist,
                "market_bars": has_bars,
                "historical_trades": has_trades
            },
            "path": "data/market_data.duckdb"
        }
    except Exception as exc:
        components["market_data_db"] = {"status": "error", "error": str(exc)}

    # Analysis database
    try:
        from src.common.dao.analytics_dao import AnalyticsDAO
        dao = AnalyticsDAO()
        # Check connection by verifying table exists
        has_metrics = dao.table_exists("strategy_metrics")
        dao.close()
        components["analysis_db"] = {
            "status": "ok",
            "tables": {"strategy_metrics": has_metrics},
            "path": "data/analysis.duckdb"
        }
    except Exception as exc:
        components["analysis_db"] = {"status": "error", "error": str(exc)}

    # Backtest database
    try:
        from src.common.dao.backtest_dao import BacktestDAO
        dao = BacktestDAO()
        # Check if backtest results table exists
        has_results = dao.table_exists("backtest_results")
        dao.close()
        components["backtest_db"] = {
            "status": "ok",
            "tables": {"backtest_results": has_results},
            "path": "data/backtest.duckdb"
        }
    except Exception as exc:
        components["backtest_db"] = {"status": "error", "error": str(exc)}

    # Checkpoint database (SQLite for LangGraph state persistence)
    try:
        import sqlite3
        from pathlib import Path
        checkpoint_path = Path("data/checkpoints.db")
        if checkpoint_path.exists():
            conn = sqlite3.connect(str(checkpoint_path))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            components["checkpoint_db"] = {
                "status": "ok",
                "tables": tables,
                "path": "data/checkpoints.db"
            }
        else:
            components["checkpoint_db"] = {
                "status": "ok",
                "exists": False,
                "path": "data/checkpoints.db",
                "note": "Will be created on first graph invocation"
            }
    except Exception as exc:
        components["checkpoint_db"] = {"status": "error", "error": str(exc)}

    overall = "ok" if all(c.get("status") == "ok" for c in components.values()) else "degraded"
    return {
        "status": overall,
        "components": components,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
