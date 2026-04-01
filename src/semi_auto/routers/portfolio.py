"""Portfolio router — GET /v1/portfolio/status|health|history."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.common.utils import get_logger
from src.semi_auto.models.endpoints import PortfolioHealthResponse, PortfolioHistoryResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/portfolio", tags=["portfolio"])


@router.get("/status")
async def portfolio_status():
    """Direct portfolio status without agent reasoning.

    Returns:
        Portfolio status dict from Alpaca.
    """
    try:
        from src.agentic.agents.portfolio.skills.portfoliostatus.status import get_portfolio_status_core
        return get_portfolio_status_core()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health", response_model=PortfolioHealthResponse)
async def portfolio_health():
    """Risk compliance check against portfolio risk parameters.

    Calls ``check_portfolio_health`` via the FUNCTION_REGISTRY wrapper which
    auto-injects portfolio_status and positions_data.

    Returns:
        Health status with violations, warnings, and checks performed.
    """
    try:
        from src.semi_auto.registry.functions import AVAILABLE_FUNCTIONS
        health_fn = AVAILABLE_FUNCTIONS.get("check_portfolio_health")
        if health_fn is None:
            raise HTTPException(status_code=503, detail="check_portfolio_health not available")
        result = health_fn()
        return {
            "status": "success",
            "health": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[portfolio/health] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history", response_model=PortfolioHistoryResponse)
async def portfolio_history(
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
):
    """Historical portfolio snapshots.

    Args:
        start: Optional start date filter (YYYY-MM-DD).
        end: Optional end date filter (YYYY-MM-DD).

    Returns:
        List of portfolio snapshots with count.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        history = dao.get_snapshot_history(start_date=start, end_date=end)
        dao.close()
        return {
            "status": "success",
            "snapshots": history,
            "count": len(history),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[portfolio/history] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# Valid timeframe options per period to avoid Alpaca 422 errors.
_PERIOD_TIMEFRAME_MAP: dict = {
    "1D": {"1Min", "5Min", "15Min", "1H"},
    "1W": {"1Min", "5Min", "15Min", "1H", "1D"},
    "1M": {"1H", "1D"},
    "3M": {"1D"},
    "1A": {"1D"},
    "all": {"1D"},
}


@router.get("/history/alpaca")
async def portfolio_history_alpaca(
    period: str = Query(default="1M", description="Time period: 1D, 1W, 1M, 3M, 1A, all"),
    timeframe: str = Query(default="1D", description="Bar resolution: 1Min, 5Min, 15Min, 1H, 1D"),
    extended_hours: bool = Query(default=False, description="Include pre/post market data"),
):
    """Live portfolio performance history directly from Alpaca.

    Returns equity curve and P&L series from Alpaca's portfolio history API,
    as opposed to ``/history`` which returns locally-stored snapshots.

    Args:
        period: Lookback window. One of ``1D``, ``1W``, ``1M``, ``3M``,
            ``1A``, ``all``. Default ``1M``.
        timeframe: Bar aggregation. Allowed values depend on ``period``
            (e.g. ``1D`` period only supports intraday resolutions).
            Default ``1D``.
        extended_hours: Include extended-hours data. Default False.

    Returns:
        Dict with timestamp list, equity list, profit_loss list,
        profit_loss_pct list, base_value, and timeframe.

    Raises:
        400: If the period+timeframe combination is invalid.
        500: If the Alpaca API request fails.
    """
    valid_timeframes = _PERIOD_TIMEFRAME_MAP.get(period.upper())
    if valid_timeframes is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {', '.join(_PERIOD_TIMEFRAME_MAP)}",
        )
    if timeframe not in valid_timeframes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Timeframe '{timeframe}' is not valid for period '{period}'. "
                f"Allowed: {', '.join(sorted(valid_timeframes))}"
            ),
        )
    try:
        from src.common.external.alpaca_portfolio import fetch_portfolio_history
        data = fetch_portfolio_history(
            period=period.upper(),
            timeframe=timeframe,
            extended_hours=extended_hours,
        )
        return {
            "status": "success",
            "period": period,
            **data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[portfolio/history/alpaca] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
