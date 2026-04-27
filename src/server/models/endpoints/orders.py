"""Response models for order execution endpoints."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class OrderResponse(BaseModel):
    """Response for a single order submission.

    Attributes:
        status: "success" | "error".
        order: Order details dict from Alpaca (id, symbol, qty, side, type, etc.).
        error: Error message on failure.
        timestamp: ISO-8601 response timestamp.
    """

    model_config = ConfigDict(extra="allow")

    status: str
    order: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ScalePositionResponse(BaseModel):
    """Response for POST /v1/orders/scale.

    Attributes:
        status: "success" | "error".
        action: "buy" | "sell" | "hold" | "close".
        symbol: Stock ticker.
        current_qty: Shares held before scale.
        target_qty: Desired shares after scale.
        delta_qty: Shares to trade (signed).
        current_pct: Current allocation fraction.
        target_pct: Requested target fraction.
        order: Order details (None when action is "hold").
        error: Error message on failure.
        timestamp: ISO-8601.
    """

    model_config = ConfigDict(extra="allow")

    status: str
    action: Optional[str] = None
    symbol: Optional[str] = None
    current_qty: Optional[int] = None
    target_qty: Optional[int] = None
    delta_qty: Optional[int] = None
    current_pct: Optional[float] = None
    target_pct: Optional[float] = None
    order: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class StrategySignalExecutionResponse(BaseModel):
    """Response for POST /v1/orders/signal.

    Attributes:
        status: "success" | "error".
        action: "buy" | "sell" | "hold".
        symbol: Stock ticker.
        signal: Original signal value.
        confidence: Conviction used.
        target_pct: Allocation target applied.
        order: Order placed (None for hold).
        error: Error message on failure.
        timestamp: ISO-8601.
    """

    model_config = ConfigDict(extra="allow")

    status: str
    action: Optional[str] = None
    symbol: Optional[str] = None
    signal: Optional[str] = None
    confidence: Optional[float] = None
    target_pct: Optional[float] = None
    order: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class OrderCancelResponse(BaseModel):
    """Response for DELETE /v1/orders/{order_id}.

    Attributes:
        status: "success" | "error".
        order_id: Cancelled order UUID.
        message: Human-readable confirmation.
        error: Error message on failure.
        timestamp: ISO-8601.
    """

    status: str
    order_id: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class OpenOrdersResponse(BaseModel):
    """Response for GET /v1/orders.

    Attributes:
        status: "success" | "error".
        orders: List of open-order dicts.
        count: Total orders returned.
        timestamp: ISO-8601.
    """

    status: str
    orders: List[Dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
