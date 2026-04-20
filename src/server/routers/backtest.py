"""Backtest router — read-only BacktestDAO endpoints at /v1/backtest/..."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder

from src.common.dao.backtest_dao import BacktestDAO
from src.common.utils import get_logger
from src.server.models.endpoints import (
    BacktestPerformanceResponse,
    BacktestRunResponse,
    BacktestRunsResponse,
    BacktestTradesResponse,
)
from src.server.routers._helpers import _df_to_records, dao_context, handle_http_errors, run_in_thread

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/backtest", tags=["backtest"])


def _clean_run_data(run: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DuckDB types to JSON-serializable types.

    DuckDB returns Decimal objects for DECIMAL columns which don't serialize to
    JSON.  All numeric and date fields are coerced to standard Python types.

    Args:
        run: Raw run data dict from DAO.

    Returns:
        Cleaned dict with JSON-serializable types.
    """
    for field in ("start_date", "end_date", "created_at", "completed_at"):
        if run.get(field) is not None:
            run[field] = str(run[field])

    for field in (
        "initial_capital", "final_capital", "total_return_pct",
        "sharpe_ratio", "max_drawdown_pct", "sortino_ratio",
        "calmar_ratio", "win_rate", "profit_factor",
        "avg_win", "avg_loss", "largest_win", "largest_loss",
        "avg_trade_duration_days",
    ):
        if run.get(field) is not None:
            try:
                run[field] = float(run[field])
            except (TypeError, ValueError):
                run[field] = None

    for field in ("total_trades", "winning_trades", "losing_trades"):
        if run.get(field) is not None:
            try:
                run[field] = int(run[field])
            except (TypeError, ValueError):
                run[field] = None

    if run.get("win_rate") is not None:
        run["win_rate"] = run["win_rate"] * 100.0

    initial = run.get("initial_capital")
    ret_pct = run.get("total_return_pct")
    dd_pct = run.get("max_drawdown_pct")
    run["total_return_dollars"] = (ret_pct / 100.0) * initial if (ret_pct is not None and initial) else None
    run["max_drawdown_dollars"] = (dd_pct / 100.0) * initial if (dd_pct is not None and initial) else None

    return run


@router.get("/runs", response_model=BacktestRunsResponse)
@handle_http_errors
async def get_recent_runs(
    strategy_name: Optional[str] = Query(None, description="Filter by strategy name"),
    limit: int = Query(default=10, ge=1, le=200),
) -> Any:
    """Return the most recent backtest runs.

    Args:
        strategy_name: Optional strategy name filter.
        limit: Maximum number of runs to return (default 10).

    Returns:
        Dict with ``runs`` list and ``count``.
    """
    def _fetch() -> List[Dict[str, Any]]:
        with dao_context(BacktestDAO) as dao:
            return dao.get_recent_runs(strategy_name=strategy_name, limit=limit)

    runs_raw = await run_in_thread(_fetch)
    runs = [_clean_run_data(r) for r in runs_raw]
    return jsonable_encoder({"runs": runs, "count": len(runs)})


@router.get("/runs/{run_id}", response_model=BacktestRunResponse)
@handle_http_errors
async def get_run(run_id: str) -> Any:
    """Return details for a single backtest run.

    Returns:
        Dict with ``run_id`` and ``run`` (dict or null).
    """
    def _fetch():
        with dao_context(BacktestDAO) as dao:
            return dao.get_run(run_id)

    run = await run_in_thread(_fetch)
    if run:
        run = _clean_run_data(run)
    return jsonable_encoder({"run_id": run_id, "run": run})


@router.get("/runs/{run_id}/trades", response_model=BacktestTradesResponse)
@handle_http_errors
async def get_trades_for_run(run_id: str) -> Any:
    """Return all trades executed in a backtest run.

    Returns:
        Dict with ``run_id``, ``trades`` list, and ``count``.
    """
    def _fetch():
        with dao_context(BacktestDAO) as dao:
            return dao.get_trades_for_run(run_id)

    records = _df_to_records(await run_in_thread(_fetch))
    for trade in records:
        for field in ("entry_date", "exit_date", "entry_time", "exit_time"):
            if trade.get(field) is not None:
                trade[field] = str(trade[field])
        for field in ("entry_price", "exit_price", "pnl", "pnl_pct", "fees"):
            if trade.get(field) is not None:
                trade[field] = float(trade[field])
        if trade.get("quantity") is not None:
            trade["quantity"] = int(trade["quantity"])
    return jsonable_encoder({"run_id": run_id, "trades": records, "count": len(records)})


@router.get("/runs/{run_id}/performance", response_model=BacktestPerformanceResponse)
@handle_http_errors
async def get_performance_history(run_id: str) -> Any:
    """Return daily performance history for a backtest run.

    Returns:
        Dict with ``run_id``, ``performance`` list, and ``count``.
    """
    def _fetch():
        with dao_context(BacktestDAO) as dao:
            return dao.get_performance_history(run_id)

    records = _df_to_records(await run_in_thread(_fetch))
    for perf in records:
        if perf.get("date") is not None:
            perf["date"] = str(perf["date"])
        for field in ("equity", "daily_return", "cumulative_return", "drawdown_pct"):
            if perf.get(field) is not None:
                perf[field] = float(perf[field])
        if perf.get("positions") is not None:
            perf["positions"] = int(perf["positions"])
    return jsonable_encoder({"run_id": run_id, "performance": records, "count": len(records)})
