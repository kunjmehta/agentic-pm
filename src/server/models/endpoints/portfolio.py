"""Response models for portfolio endpoints."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PortfolioHealthResponse(BaseModel):
    """Response for GET /v1/portfolio/health.

    Attributes:
        status: ``"success"`` or ``"error"``.
        health: Raw dict from ``check_portfolio_health`` registry function.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str
    health: Dict[str, Any]
    timestamp: str


class PortfolioHistoryResponse(BaseModel):
    """Response for GET /v1/portfolio/history.

    Attributes:
        status: Always ``"success"``.
        snapshots: List of portfolio snapshot dicts from the database.
        count: Number of items returned.
        start: Requested start date (may be ``None``).
        end: Requested end date (may be ``None``).
    """

    status: str = "success"
    snapshots: List[Any] = Field(default_factory=list)
    count: int
    start: Optional[str] = None
    end: Optional[str] = None
