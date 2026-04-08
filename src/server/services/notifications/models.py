"""Data models for notification events.

This module defines the event types that can trigger notifications across
the trading system. Each event type includes metadata specific to its domain
(backtesting, order execution, agent errors, portfolio updates).
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict


class NotificationSeverity(str, Enum):
    """Severity levels for notifications (aligned with logging levels)."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class NotificationEvent(BaseModel):
    """Base model for all notification events.

    Attributes:
        event_type: Type of event (e.g., "backtest", "order", "agent_error")
        severity: Severity level for filtering notifications
        title: Short summary of the event
        message: Detailed description
        timestamp: When the event occurred (UTC)
        metadata: Additional event-specific data
    """
    event_type: str = Field(..., description="Type of event")
    severity: NotificationSeverity = Field(
        default=NotificationSeverity.INFO,
        description="Severity level for filtering"
    )
    title: str = Field(..., description="Short summary of the event")
    message: str = Field(..., description="Detailed description")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the event occurred (UTC)"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional event-specific data"
    )

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )


class BacktestEvent(NotificationEvent):
    """Event triggered by backtest completion or failure.

    Attributes:
        backtest_id: Unique identifier for the backtest run
        strategy: Strategy name (e.g., "mean_reversion", "vwap_reversion")
        symbol: Trading symbol
        timeframe: Bar timeframe (e.g., "1Min", "1Day")
        status: Completion status ("completed", "failed", "cancelled")
        sharpe_ratio: Sharpe ratio (if completed successfully)
        total_return: Total return percentage (if completed)
        max_drawdown: Maximum drawdown percentage (if completed)
        error_message: Error details (if failed)
    """
    event_type: Literal["backtest"] = "backtest"
    backtest_id: str = Field(..., description="Unique backtest identifier")
    strategy: str = Field(..., description="Strategy name")
    symbol: str = Field(..., description="Trading symbol")
    timeframe: str = Field(..., description="Bar timeframe")
    status: str = Field(..., description="Completion status")
    sharpe_ratio: Optional[float] = Field(None, description="Sharpe ratio")
    total_return: Optional[float] = Field(None, description="Total return %")
    max_drawdown: Optional[float] = Field(None, description="Max drawdown %")
    error_message: Optional[str] = Field(None, description="Error details")


class OrderEvent(NotificationEvent):
    """Event triggered by order execution, fill, or rejection.

    Attributes:
        order_id: Unique order identifier
        symbol: Trading symbol
        side: Order side ("buy" or "sell")
        qty: Order quantity
        order_type: Order type (e.g., "market", "limit")
        status: Order status (e.g., "filled", "partially_filled", "rejected")
        filled_qty: Quantity filled
        avg_fill_price: Average fill price
        rejection_reason: Reason for rejection (if applicable)
    """
    event_type: Literal["order"] = "order"
    order_id: str = Field(..., description="Unique order identifier")
    symbol: str = Field(..., description="Trading symbol")
    side: str = Field(..., description="Order side (buy/sell)")
    qty: float = Field(..., description="Order quantity")
    order_type: str = Field(..., description="Order type")
    status: str = Field(..., description="Order status")
    filled_qty: Optional[float] = Field(None, description="Quantity filled")
    avg_fill_price: Optional[float] = Field(None, description="Average fill price")
    rejection_reason: Optional[str] = Field(None, description="Rejection reason")


class AgentErrorEvent(NotificationEvent):
    """Event triggered by agent/graph execution errors.

    Attributes:
        agent_name: Name of the agent (e.g., "quant_analyst", "portfolio_manager")
        thread_id: LangGraph thread ID
        node_name: Graph node where error occurred
        error_type: Exception type
        error_traceback: Full traceback
        recoverable: Whether the error is recoverable
    """
    event_type: Literal["agent_error"] = "agent_error"
    agent_name: str = Field(..., description="Agent name")
    thread_id: str = Field(..., description="LangGraph thread ID")
    node_name: Optional[str] = Field(None, description="Graph node name")
    error_type: str = Field(..., description="Exception type")
    error_traceback: str = Field(..., description="Full traceback")
    recoverable: bool = Field(
        default=False,
        description="Whether the error is recoverable"
    )


class PortfolioEvent(NotificationEvent):
    """Event triggered by significant portfolio changes.

    Attributes:
        portfolio_value: Current total portfolio value
        cash_balance: Available cash
        positions_count: Number of open positions
        daily_pnl: Profit/loss for the day
        daily_pnl_pct: Daily P&L as percentage
        change_reason: Reason for notification (e.g., "margin_call", "target_reached")
    """
    event_type: Literal["portfolio"] = "portfolio"
    portfolio_value: float = Field(..., description="Total portfolio value")
    cash_balance: float = Field(..., description="Available cash")
    positions_count: int = Field(..., description="Number of open positions")
    daily_pnl: Optional[float] = Field(None, description="Daily P&L")
    daily_pnl_pct: Optional[float] = Field(None, description="Daily P&L %")
    change_reason: str = Field(..., description="Reason for notification")


if __name__ == "__main__":
    """Functional test for notification models."""
    import json

    # Test BacktestEvent
    backtest_event = BacktestEvent(
        title="Backtest Completed: AAPL Mean Reversion",
        message="Successfully completed backtest for AAPL using mean_reversion strategy",
        severity=NotificationSeverity.INFO,
        backtest_id="bt_12345",
        strategy="mean_reversion",
        symbol="AAPL",
        timeframe="1Min",
        status="completed",
        sharpe_ratio=1.85,
        total_return=12.5,
        max_drawdown=-3.2
    )

    print("=== BacktestEvent ===")
    print(json.dumps(backtest_event.model_dump(), indent=2, default=str))

    # Test OrderEvent
    order_event = OrderEvent(
        title="Order Filled: AAPL Buy",
        message="Market order to buy 100 shares of AAPL filled at $150.25",
        severity=NotificationSeverity.INFO,
        order_id="ord_67890",
        symbol="AAPL",
        side="buy",
        qty=100,
        order_type="market",
        status="filled",
        filled_qty=100,
        avg_fill_price=150.25
    )

    print("\n=== OrderEvent ===")
    print(json.dumps(order_event.model_dump(), indent=2, default=str))

    # Test AgentErrorEvent
    agent_error_event = AgentErrorEvent(
        title="Agent Error: Quant Analyst",
        message="Error in quant_analyst during signal generation",
        severity=NotificationSeverity.ERROR,
        agent_name="quant_analyst",
        thread_id="thread_abc123",
        node_name="quant_analysis_node",
        error_type="ValueError",
        error_traceback="Traceback (most recent call last):\n  ...",
        recoverable=True
    )

    print("\n=== AgentErrorEvent ===")
    print(json.dumps(agent_error_event.model_dump(), indent=2, default=str))

    # Test PortfolioEvent
    portfolio_event = PortfolioEvent(
        title="Portfolio Alert: Drawdown Threshold",
        message="Portfolio drawdown exceeded 5% threshold",
        severity=NotificationSeverity.WARNING,
        portfolio_value=95000.0,
        cash_balance=45000.0,
        positions_count=3,
        daily_pnl=-2500.0,
        daily_pnl_pct=-2.56,
        change_reason="drawdown_threshold"
    )

    print("\n=== PortfolioEvent ===")
    print(json.dumps(portfolio_event.model_dump(), indent=2, default=str))

    print("\n[OK] All notification models validated successfully")
