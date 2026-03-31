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
