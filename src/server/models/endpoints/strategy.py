"""Response models for strategy and signal review endpoints (StrategyDAO)."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ActionableSignalsResponse(BaseModel):
    """Response for GET /v1/strategy/actionable.

    Attributes:
        signals: Signals meeting the confidence threshold.
        count: Number of signals.
    """

    signals: List[Any] = Field(default_factory=list)
    count: int


class StrategyPerformanceResponse(BaseModel):
    """Response for GET /v1/strategy/{strategy_name}/performance.

    Attributes:
        strategy_name: Name of the strategy.
        days: Look-back window in days.
        performance: Performance stats dict, or ``None`` if no data.
    """

    strategy_name: str
    days: int
    performance: Optional[Dict[str, Any]] = None


class LatestSignalResponse(BaseModel):
    """Response for GET /v1/strategy/{symbol}/{strategy_name}/latest.

    Attributes:
        symbol: Upper-cased ticker.
        strategy_name: Strategy name.
        signal: Most recent signal dict, or ``None``.
    """

    symbol: str
    strategy_name: str
    signal: Optional[Dict[str, Any]] = None


class RecentSignalsResponse(BaseModel):
    """Response for GET /v1/strategy/{symbol}/{strategy_name}/signals.

    Attributes:
        symbol: Upper-cased ticker.
        strategy_name: Strategy name.
        signals: Recent signal rows.
        count: Number of rows.
    """

    symbol: str
    strategy_name: str
    signals: List[Any] = Field(default_factory=list)
    count: int


class PendingSignalsResponse(BaseModel):
    """Response for GET /v1/strategy/signals/pending.

    Attributes:
        signals: Rows with ``status='pending_review'``.
        count: Number of rows.
    """

    signals: List[Any] = Field(default_factory=list)
    count: int


class SignalReviewResponse(BaseModel):
    """Response for POST /v1/strategy/signals/{id}/approve|reject.

    Attributes:
        signal_id: Primary key that was reviewed.
        status: New status applied — ``'approved'`` | ``'rejected'``.
        ok: Whether the update succeeded.
        message: Human-readable confirmation.
        timestamp: ISO-8601 review timestamp.
    """

    signal_id: int
    status: str
    ok: bool
    message: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class SignalRejectRequest(BaseModel):
    """Request body for POST /v1/strategy/signals/{id}/reject.

    Attributes:
        reviewer_note: Optional human-readable reason for rejection.
    """

    reviewer_note: Optional[str] = Field(None, description="Optional rejection reason")


class SignalModifyRequest(BaseModel):
    """Request body for PATCH /v1/strategy/signals/{id}/modify.

    Attributes:
        qty_override: Replacement quantity to pass to the order layer.
        reviewer_note: Optional human note.
    """

    qty_override: int = Field(..., ge=1, description="Replacement share quantity (≥ 1)")
    reviewer_note: Optional[str] = Field(None, description="Optional reviewer comment")


class SignalModifyResponse(BaseModel):
    """Response for PATCH /v1/strategy/signals/{id}/modify.

    Attributes:
        signal_id: Primary key that was modified.
        new_qty: The qty_override that was stored.
        ok: Whether the update succeeded.
        message: Human-readable confirmation.
        timestamp: ISO-8601 review timestamp.
    """

    signal_id: int
    new_qty: int
    ok: bool
    message: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
