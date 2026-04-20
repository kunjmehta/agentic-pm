"""Response models for analyst endpoints (AnalystDAO)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AnalystSymbolsResponse(BaseModel):
    """Response for GET /v1/analyst/symbols.

    Attributes:
        symbols: List of tickers with analyst data.
        count: Number of symbols.
    """

    symbols: List[str]
    count: int


class EODSummariesResponse(BaseModel):
    """Response for GET /v1/analyst/{symbol}/eod (date range).

    Attributes:
        symbol: Upper-cased ticker.
        summaries: Analyst EOD summary rows.
        count: Number of rows.
    """

    symbol: str
    summaries: List[Any] = Field(default_factory=list)
    count: int


class LatestEODResponse(BaseModel):
    """Response for GET /v1/analyst/{symbol}/eod/latest.

    Attributes:
        symbol: Upper-cased ticker.
        summary: Most recent EOD summary dict, or ``None`` if no data.
    """

    symbol: str
    summary: Optional[Dict[str, Any]] = None


class RecentEODsResponse(BaseModel):
    """Response for GET /v1/analyst/{symbol}/eod/recent.

    Attributes:
        symbol: Upper-cased ticker.
        summaries: Up to ``count`` most recent EOD summary dicts.
        count: Actual number returned.
    """

    symbol: str
    summaries: List[Any] = Field(default_factory=list)
    count: int
