"""Analyst router — read-only AnalysisDAO endpoints at /v1/analyst/..."""

from datetime import date as _date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from src.common.dao.analysis_dao import AnalysisDAO
from src.common.utils import get_logger
from src.server.models.endpoints import (
    AnalystSymbolsResponse,
    EODSummariesResponse,
    LatestEODResponse,
    RecentEODsResponse,
)
from src.server.routers._helpers import _df_to_records, dao_context, handle_http_errors, run_in_thread

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/analyst", tags=["analyst"])


@router.get("/symbols", response_model=AnalystSymbolsResponse)
@handle_http_errors
async def get_all_symbols() -> Dict[str, Any]:
    """Return all symbols that have at least one analyst EOD summary.

    Returns:
        Dict with ``symbols`` list and ``count``.
    """
    def _fetch() -> list:
        with dao_context(AnalysisDAO) as dao:
            return dao.get_all_symbols()

    symbols = await run_in_thread(_fetch)
    return {"symbols": symbols, "count": len(symbols)}


@router.get("/{symbol}/eod", response_model=EODSummariesResponse)
@handle_http_errors
async def get_eod_summaries(
    symbol: str,
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> Dict[str, Any]:
    """Return analyst EOD summaries for a symbol over a date range.

    Returns:
        Dict with ``summaries`` list and ``count``.
    """
    start_date = _date.fromisoformat(start)
    end_date = _date.fromisoformat(end)

    def _fetch():
        with dao_context(AnalysisDAO) as dao:
            return dao.get_eod_summaries(symbol.upper(), start_date, end_date)

    df = await run_in_thread(_fetch)
    records = _df_to_records(df)
    return {"symbol": symbol.upper(), "summaries": records, "count": len(records)}


@router.get("/{symbol}/eod/latest", response_model=LatestEODResponse)
@handle_http_errors
async def get_latest_eod(symbol: str) -> Dict[str, Any]:
    """Return the most recent analyst EOD summary for a symbol.

    Returns:
        Dict with ``symbol`` and ``summary`` (dict or null).
    """
    def _fetch():
        with dao_context(AnalysisDAO) as dao:
            return dao.get_latest_eod(symbol.upper())

    summary = await run_in_thread(_fetch)
    return {"symbol": symbol.upper(), "summary": summary}


@router.get("/{symbol}/eod/recent", response_model=RecentEODsResponse)
@handle_http_errors
async def get_recent_eods(
    symbol: str,
    count: int = Query(default=5, ge=1, le=100),
) -> Dict[str, Any]:
    """Return the N most recent analyst EOD summaries for a symbol.

    Returns:
        Dict with ``summaries`` list and ``count``.
    """
    def _fetch():
        with dao_context(AnalysisDAO) as dao:
            return dao.get_recent_eods(symbol.upper(), count=count)

    summaries = await run_in_thread(_fetch)
    return {"symbol": symbol.upper(), "summaries": summaries, "count": len(summaries)}
