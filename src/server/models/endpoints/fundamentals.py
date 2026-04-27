"""Response models for fundamentals endpoints (AlphaVantageDAO)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FundamentalsListResponse(BaseModel):
    """Response for GET /v1/fundamentals.

    Attributes:
        fundamentals: List of fundamental dicts (one per symbol).
        count: Number of symbols.
    """

    fundamentals: List[Any] = Field(default_factory=list)
    count: int


class CompanyOverviewResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}.

    Attributes:
        symbol: Upper-cased ticker.
        overview: Company overview dict, or ``None`` if not in DB.
    """

    symbol: str
    overview: Optional[Dict[str, Any]] = None


class DividendsResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}/dividends.

    Attributes:
        symbol: Upper-cased ticker.
        dividends: Dividend history rows.
        count: Number of rows.
    """

    symbol: str
    dividends: List[Any] = Field(default_factory=list)
    count: int


class EarningsResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}/earnings.

    Attributes:
        symbol: Upper-cased ticker.
        quarterly: True = quarterly data, False = annual.
        earnings: Earnings rows.
        count: Number of rows.
    """

    symbol: str
    quarterly: bool
    earnings: List[Any] = Field(default_factory=list)
    count: int


class IncomeStatementResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}/income.

    Attributes:
        symbol: Upper-cased ticker.
        income_statements: Income statement rows.
        count: Number of rows.
    """

    symbol: str
    income_statements: List[Any] = Field(default_factory=list)
    count: int


class BalanceSheetResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}/balance-sheet.

    Attributes:
        symbol: Upper-cased ticker.
        balance_sheets: Balance sheet rows.
        count: Number of rows.
    """

    symbol: str
    balance_sheets: List[Any] = Field(default_factory=list)
    count: int


class CashFlowResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}/cash-flow.

    Attributes:
        symbol: Upper-cased ticker.
        cash_flows: Cash flow rows.
        count: Number of rows.
    """

    symbol: str
    cash_flows: List[Any] = Field(default_factory=list)
    count: int
