"""Fundamentals router — read-only AlphaVantageDAO endpoints at /v1/fundamentals/..."""

from datetime import date as _date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from src.common.dao.alpha_vantage_dao import AlphaVantageDAO
from src.common.utils import get_logger
from src.server.models.endpoints import (
    BalanceSheetResponse,
    CashFlowResponse,
    CompanyOverviewResponse,
    DividendsResponse,
    EarningsResponse,
    FundamentalsListResponse,
    IncomeStatementResponse,
)
from src.server.routers._helpers import _df_to_records, dao_context, handle_http_errors, run_in_thread

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/fundamentals", tags=["fundamentals"])


@router.get("", response_model=FundamentalsListResponse)
@handle_http_errors
async def get_all_fundamentals() -> Dict[str, Any]:
    """Return latest fundamentals for all symbols in the DB.

    Returns:
        Dict with ``fundamentals`` list and ``count``.
    """
    def _fetch():
        with dao_context(AlphaVantageDAO) as dao:
            return dao.get_all_fundamentals()

    records = _df_to_records(await run_in_thread(_fetch))
    return {"fundamentals": records, "count": len(records)}


@router.get("/{symbol}", response_model=CompanyOverviewResponse)
@handle_http_errors
async def get_company_overview(symbol: str) -> Dict[str, Any]:
    """Return the company overview for a single symbol.

    Returns:
        Dict with ``symbol`` and ``overview`` (dict or null).
    """
    def _fetch():
        with dao_context(AlphaVantageDAO) as dao:
            return dao.get_company_overview(symbol.upper())

    overview = await run_in_thread(_fetch)
    return {"symbol": symbol.upper(), "overview": overview}


@router.get("/{symbol}/dividends", response_model=DividendsResponse)
@handle_http_errors
async def get_dividends(
    symbol: str,
    start: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    limit: int = Query(default=20, ge=1, le=500),
) -> Dict[str, Any]:
    """Return dividend history for a symbol.

    Returns:
        Dict with ``dividends`` list and ``count``.
    """
    start_date = _date.fromisoformat(start) if start else None
    end_date = _date.fromisoformat(end) if end else None

    def _fetch():
        with dao_context(AlphaVantageDAO) as dao:
            return dao.get_dividends(symbol.upper(), start_date=start_date, end_date=end_date, limit=limit)

    records = _df_to_records(await run_in_thread(_fetch))
    return {"symbol": symbol.upper(), "dividends": records, "count": len(records)}


@router.get("/{symbol}/earnings", response_model=EarningsResponse)
@handle_http_errors
async def get_earnings(
    symbol: str,
    quarterly: bool = Query(default=True),
    limit: int = Query(default=4, ge=1, le=40),
) -> Dict[str, Any]:
    """Return earnings history for a symbol.

    Returns:
        Dict with ``earnings`` list and ``count``.
    """
    def _fetch():
        with dao_context(AlphaVantageDAO) as dao:
            return dao.get_earnings(symbol.upper(), quarterly=quarterly, limit=limit)

    records = _df_to_records(await run_in_thread(_fetch))
    return {"symbol": symbol.upper(), "quarterly": quarterly, "earnings": records, "count": len(records)}


@router.get("/{symbol}/income", response_model=IncomeStatementResponse)
@handle_http_errors
async def get_income_statement(
    symbol: str,
    quarterly: bool = Query(default=False),
    limit: int = Query(default=4, ge=1, le=40),
) -> Dict[str, Any]:
    """Return income statement history for a symbol.

    Returns:
        Dict with ``income_statements`` list and ``count``.
    """
    def _fetch():
        with dao_context(AlphaVantageDAO) as dao:
            return dao.get_income_statement(symbol.upper(), quarterly=quarterly, limit=limit)

    records = _df_to_records(await run_in_thread(_fetch))
    return {"symbol": symbol.upper(), "income_statements": records, "count": len(records)}


@router.get("/{symbol}/balance-sheet", response_model=BalanceSheetResponse)
@handle_http_errors
async def get_balance_sheet(
    symbol: str,
    quarterly: bool = Query(default=False),
    limit: int = Query(default=4, ge=1, le=40),
) -> Dict[str, Any]:
    """Return balance sheet history for a symbol.

    Returns:
        Dict with ``balance_sheets`` list and ``count``.
    """
    def _fetch():
        with dao_context(AlphaVantageDAO) as dao:
            return dao.get_balance_sheet(symbol.upper(), quarterly=quarterly, limit=limit)

    records = _df_to_records(await run_in_thread(_fetch))
    return {"symbol": symbol.upper(), "balance_sheets": records, "count": len(records)}


@router.get("/{symbol}/cash-flow", response_model=CashFlowResponse)
@handle_http_errors
async def get_cash_flow(
    symbol: str,
    quarterly: bool = Query(default=False),
    limit: int = Query(default=4, ge=1, le=40),
) -> Dict[str, Any]:
    """Return cash flow history for a symbol.

    Returns:
        Dict with ``cash_flows`` list and ``count``.
    """
    def _fetch():
        with dao_context(AlphaVantageDAO) as dao:
            return dao.get_cash_flow(symbol.upper(), quarterly=quarterly, limit=limit)

    records = _df_to_records(await run_in_thread(_fetch))
    return {"symbol": symbol.upper(), "cash_flows": records, "count": len(records)}
