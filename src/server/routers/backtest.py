"""Backtest router — read-only BacktestDAO endpoints at /v1/backtest/..."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.server.routers._helpers import _df_to_records
from src.common.utils import get_logger
from src.server.models.endpoints import (
    BacktestPerformanceResponse,
    BacktestRunResponse,
    BacktestRunsResponse,
    BacktestTradesResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/backtest", tags=["backtest"])


def _dao():
    from src.common.dao.backtest_dao import BacktestDAO
    return BacktestDAO()


@router.get("/runs", response_model=BacktestRunsResponse)
async def get_recent_runs(
    strategy_name: Optional[str] = Query(None, description="Filter by strategy name"),
    limit: int = Query(default=10, ge=1, le=200),
):
    """Return the most recent backtest runs.

    Args:
        strategy_name: Optional strategy name filter.
        limit: Maximum number of runs to return (default 10).

    Returns:
        Dict with ``runs`` list and ``count``.
    """
    try:
        dao = _dao()
        runs = dao.get_recent_runs(strategy_name=strategy_name, limit=limit)
        dao.close()
        return {"runs": runs, "count": len(runs)}
    except Exception as exc:
        logger.warning(f"[backtest/runs] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/runs/{run_id}", response_model=BacktestRunResponse)
async def get_run(run_id: str):
    """Return details for a single backtest run.

    Returns:
        Dict with ``run_id`` and ``run`` (dict or null).
    """
    try:
        dao = _dao()
        run = dao.get_run(run_id)
        dao.close()
        return {"run_id": run_id, "run": run}
    except Exception as exc:
        logger.warning(f"[backtest/runs/{run_id}] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/runs/{run_id}/trades", response_model=BacktestTradesResponse)
async def get_trades_for_run(run_id: str):
    """Return all trades executed in a backtest run.

    Returns:
        Dict with ``run_id``, ``trades`` list, and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_trades_for_run(run_id)
        dao.close()
        records = _df_to_records(df)
        return {"run_id": run_id, "trades": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[backtest/runs/{run_id}/trades] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/runs/{run_id}/performance", response_model=BacktestPerformanceResponse)
async def get_performance_history(run_id: str):
    """Return daily performance history for a backtest run.

    Returns:
        Dict with ``run_id``, ``performance`` list, and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_performance_history(run_id)
        dao.close()
        records = _df_to_records(df)
        return {"run_id": run_id, "performance": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[backtest/runs/{run_id}/performance] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
