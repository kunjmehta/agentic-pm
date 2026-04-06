"""Fundamentals router — read-only AlphaVantageDAO endpoints at /v1/fundamentals/..."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.server.routers._helpers import _df_to_records
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

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/fundamentals", tags=["fundamentals"])


def _dao():
    from src.common.dao.alpha_vantage_dao import AlphaVantageDAO
    return AlphaVantageDAO()


@router.get("", response_model=FundamentalsListResponse)
async def get_all_fundamentals():
    """Return latest fundamentals for all symbols in the DB.

    Returns:
        Dict with ``fundamentals`` list and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_all_fundamentals()
        dao.close()
        records = _df_to_records(df)
        return {"fundamentals": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[fundamentals/all] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}", response_model=CompanyOverviewResponse)
async def get_company_overview(symbol: str):
    """Return the company overview for a single symbol.

    Returns:
        Dict with ``symbol`` and ``overview`` (dict or null).
    """
    try:
        dao = _dao()
        overview = dao.get_company_overview(symbol.upper())
        dao.close()
        return {"symbol": symbol.upper(), "overview": overview}
    except Exception as exc:
        logger.warning(f"[fundamentals/{symbol}] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/dividends", response_model=DividendsResponse)
async def get_dividends(
    symbol: str,
    start: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    limit: int = Query(default=20, ge=1, le=500),
):
    """Return dividend history for a symbol.

    Returns:
        Dict with ``dividends`` list and ``count``.
    """
    try:
        from datetime import date as _date
        dao = _dao()
        df = dao.get_dividends(
            symbol.upper(),
            start_date=_date.fromisoformat(start) if start else None,
            end_date=_date.fromisoformat(end) if end else None,
            limit=limit,
        )
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "dividends": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[fundamentals/{symbol}/dividends] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/earnings", response_model=EarningsResponse)
async def get_earnings(
    symbol: str,
    quarterly: bool = Query(default=True),
    limit: int = Query(default=4, ge=1, le=40),
):
    """Return earnings history for a symbol.

    Returns:
        Dict with ``earnings`` list and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_earnings(symbol.upper(), quarterly=quarterly, limit=limit)
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "quarterly": quarterly, "earnings": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[fundamentals/{symbol}/earnings] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/income", response_model=IncomeStatementResponse)
async def get_income_statement(
    symbol: str,
    quarterly: bool = Query(default=False),
    limit: int = Query(default=4, ge=1, le=40),
):
    """Return income statement history for a symbol.

    Returns:
        Dict with ``income_statements`` list and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_income_statement(symbol.upper(), quarterly=quarterly, limit=limit)
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "income_statements": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[fundamentals/{symbol}/income] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/balance-sheet", response_model=BalanceSheetResponse)
async def get_balance_sheet(
    symbol: str,
    quarterly: bool = Query(default=False),
    limit: int = Query(default=4, ge=1, le=40),
):
    """Return balance sheet history for a symbol.

    Returns:
        Dict with ``balance_sheets`` list and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_balance_sheet(symbol.upper(), quarterly=quarterly, limit=limit)
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "balance_sheets": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[fundamentals/{symbol}/balance-sheet] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/cash-flow", response_model=CashFlowResponse)
async def get_cash_flow(
    symbol: str,
    quarterly: bool = Query(default=False),
    limit: int = Query(default=4, ge=1, le=40),
):
    """Return cash flow history for a symbol.

    Returns:
        Dict with ``cash_flows`` list and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_cash_flow(symbol.upper(), quarterly=quarterly, limit=limit)
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "cash_flows": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[fundamentals/{symbol}/cash-flow] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
