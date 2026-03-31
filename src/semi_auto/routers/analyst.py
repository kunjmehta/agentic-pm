"""Analyst router — read-only AnalystDAO endpoints at /v1/analyst/..."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.semi_auto.routers._helpers import _df_to_records
from src.common.utils import get_logger
from src.semi_auto.models.endpoints import (
    AnalystSymbolsResponse,
    EODSummariesResponse,
    LatestEODResponse,
    RecentEODsResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/analyst", tags=["analyst"])


def _dao():
    from src.common.dao.analyst_dao import AnalystDAO
    return AnalystDAO()


@router.get("/symbols", response_model=AnalystSymbolsResponse)
async def get_all_symbols():
    """Return all symbols that have at least one analyst EOD summary.

    Returns:
        Dict with ``symbols`` list and ``count``.
    """
    try:
        dao = _dao()
        symbols = dao.get_all_symbols()
        dao.close()
        return {"symbols": symbols, "count": len(symbols)}
    except Exception as exc:
        logger.warning(f"[analyst/symbols] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/eod", response_model=EODSummariesResponse)
async def get_eod_summaries(
    symbol: str,
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
):
    """Return analyst EOD summaries for a symbol over a date range.

    Returns:
        Dict with ``summaries`` list and ``count``.
    """
    try:
        from datetime import date as _date
        dao = _dao()
        df = dao.get_eod_summaries(symbol.upper(), _date.fromisoformat(start), _date.fromisoformat(end))
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "summaries": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[analyst/{symbol}/eod] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/eod/latest", response_model=LatestEODResponse)
async def get_latest_eod(symbol: str):
    """Return the most recent analyst EOD summary for a symbol.

    Returns:
        Dict with ``symbol`` and ``summary`` (dict or null).
    """
    try:
        dao = _dao()
        summary = dao.get_latest_eod(symbol.upper())
        dao.close()
        return {"symbol": symbol.upper(), "summary": summary}
    except Exception as exc:
        logger.warning(f"[analyst/{symbol}/eod/latest] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/eod/recent", response_model=RecentEODsResponse)
async def get_recent_eods(
    symbol: str,
    count: int = Query(default=5, ge=1, le=100),
):
    """Return the N most recent analyst EOD summaries for a symbol.

    Returns:
        Dict with ``summaries`` list and ``count``.
    """
    try:
        dao = _dao()
        summaries = dao.get_recent_eods(symbol.upper(), count=count)
        dao.close()
        return {"symbol": symbol.upper(), "summaries": summaries, "count": len(summaries)}
    except Exception as exc:
        logger.warning(f"[analyst/{symbol}/eod/recent] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
