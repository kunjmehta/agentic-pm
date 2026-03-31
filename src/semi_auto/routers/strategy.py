"""Strategy router — read-only StrategyDAO endpoints at /v1/strategy/..."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.semi_auto.routers._helpers import _df_to_records
from src.common.utils import get_logger
from src.semi_auto.models.endpoints import (
    ActionableSignalsResponse,
    LatestSignalResponse,
    RecentSignalsResponse,
    StrategyPerformanceResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/strategy", tags=["strategy"])


def _dao():
    from src.common.dao.strategy_dao import StrategyDAO
    return StrategyDAO()


@router.get("/actionable", response_model=ActionableSignalsResponse)
async def get_actionable_signals(
    min_confidence: float = Query(default=0.7, ge=0.0, le=1.0),
    action: Optional[str] = Query(None, description="Filter by action e.g. 'buy' | 'sell'"),
):
    """Return all strategy signals that meet the confidence threshold.

    Args:
        min_confidence: Minimum confidence score (0–1, default 0.7).
        action: Optional action filter (buy / sell / hold).

    Returns:
        Dict with ``signals`` list and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_actionable_signals(min_confidence=min_confidence, action_filter=action)
        dao.close()
        records = _df_to_records(df)
        return {"signals": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[strategy/actionable] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{strategy_name}/performance", response_model=StrategyPerformanceResponse)
async def get_strategy_performance(
    strategy_name: str,
    days: int = Query(default=30, ge=1, le=365),
):
    """Return performance statistics for a strategy over the last N days.

    Returns:
        Dict with ``strategy_name``, ``days``, and ``performance``.
    """
    try:
        dao = _dao()
        perf = dao.get_strategy_performance(strategy_name, days=days)
        dao.close()
        return {"strategy_name": strategy_name, "days": days, "performance": perf}
    except Exception as exc:
        logger.warning(f"[strategy/{strategy_name}/performance] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/{strategy_name}/latest", response_model=LatestSignalResponse)
async def get_latest_signal(symbol: str, strategy_name: str):
    """Return the most recent signal for a symbol + strategy combination.

    Returns:
        Dict with ``symbol``, ``strategy_name``, and ``signal`` (dict or null).
    """
    try:
        dao = _dao()
        signal = dao.get_latest_signal(symbol.upper(), strategy_name)
        dao.close()
        return {"symbol": symbol.upper(), "strategy_name": strategy_name, "signal": signal}
    except Exception as exc:
        logger.warning(f"[strategy/{symbol}/{strategy_name}/latest] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/{strategy_name}/signals", response_model=RecentSignalsResponse)
async def get_recent_signals(
    symbol: str,
    strategy_name: str,
    limit: int = Query(default=10, ge=1, le=200),
):
    """Return recent signals for a symbol + strategy combination.

    Returns:
        Dict with ``signals`` list and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_recent_signals(symbol.upper(), strategy_name, limit=limit)
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "strategy_name": strategy_name, "signals": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[strategy/{symbol}/{strategy_name}/signals] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
