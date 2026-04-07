"""Backtest router — read-only BacktestDAO endpoints at /v1/backtest/..."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder

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


def _clean_run_data(run: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DuckDB types to JSON-serializable types.

    DuckDB returns Decimal objects for DECIMAL columns which don't serialize to JSON.
    This function explicitly converts all numeric and date fields to proper types.

    Args:
        run: Raw run data dict from DAO.

    Returns:
        Cleaned dict with JSON-serializable types.
    """
    # Convert date fields to ISO strings
    for date_field in ["start_date", "end_date", "created_at", "completed_at"]:
        if run.get(date_field) is not None:
            run[date_field] = str(run[date_field])

    # Convert Decimal/numeric fields to float
    numeric_fields = [
        "initial_capital", "final_capital", "total_return_pct",
        "sharpe_ratio", "max_drawdown_pct", "sortino_ratio",
        "calmar_ratio", "win_rate", "profit_factor",
        "avg_win", "avg_loss", "largest_win", "largest_loss",
        "avg_trade_duration_days"
    ]
    for field in numeric_fields:
        if run.get(field) is not None:
            try:
                # Convert to float and ensure it's a native Python float
                run[field] = float(run[field])
            except (TypeError, ValueError):
                run[field] = None

    # Convert integer fields to int
    for field in ["total_trades", "winning_trades", "losing_trades"]:
        if run.get(field) is not None:
            try:
                run[field] = int(run[field])
            except (TypeError, ValueError):
                run[field] = None

    return run


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
        runs_raw = dao.get_recent_runs(strategy_name=strategy_name, limit=limit)
        dao.close()

        # Clean and convert all runs
        runs = [_clean_run_data(run) for run in runs_raw]

        # Use FastAPI's jsonable_encoder to ensure proper serialization
        return jsonable_encoder({"runs": runs, "count": len(runs)})
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

        if run:
            run = _clean_run_data(run)

        return jsonable_encoder({"run_id": run_id, "run": run})
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

        # Clean trade records (convert dates, ensure numeric types)
        for trade in records:
            for date_field in ["entry_date", "exit_date"]:
                if trade.get(date_field) is not None:
                    trade[date_field] = str(trade[date_field])
            for time_field in ["entry_time", "exit_time"]:
                if trade.get(time_field) is not None:
                    trade[time_field] = str(trade[time_field])
            # Convert numeric fields
            for num_field in ["entry_price", "exit_price", "pnl", "pnl_pct", "fees"]:
                if trade.get(num_field) is not None:
                    trade[num_field] = float(trade[num_field])
            if trade.get("quantity") is not None:
                trade["quantity"] = int(trade["quantity"])

        return jsonable_encoder({"run_id": run_id, "trades": records, "count": len(records)})
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

        # Clean performance records
        for perf in records:
            if perf.get("date") is not None:
                perf["date"] = str(perf["date"])
            for num_field in ["equity", "daily_return", "cumulative_return", "drawdown_pct"]:
                if perf.get(num_field) is not None:
                    perf[num_field] = float(perf[num_field])
            if perf.get("positions") is not None:
                perf["positions"] = int(perf["positions"])

        return jsonable_encoder({"run_id": run_id, "performance": records, "count": len(records)})
    except Exception as exc:
        logger.warning(f"[backtest/runs/{run_id}/performance] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
