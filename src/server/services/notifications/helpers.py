"""Helper functions for sending notifications.

This module provides convenience functions for common notification scenarios,
making it easy to integrate notifications throughout the codebase without
dealing with event models directly.
"""

import logging
from typing import Optional, Dict, Any
import traceback

from .notification_service import get_notification_service
from .models import (
    BacktestEvent,
    OrderEvent,
    AgentErrorEvent,
    PortfolioEvent,
    NotificationSeverity
)


logger = logging.getLogger(__name__)


async def notify_backtest_completed(
    backtest_id: str,
    strategy: str,
    symbol: str,
    timeframe: str,
    sharpe_ratio: Optional[float] = None,
    total_return: Optional[float] = None,
    max_drawdown: Optional[float] = None,
    severity: NotificationSeverity = NotificationSeverity.INFO
) -> bool:
    """Send notification for successful backtest completion.

    Args:
        backtest_id: Unique backtest identifier
        strategy: Strategy name
        symbol: Trading symbol
        timeframe: Bar timeframe
        sharpe_ratio: Sharpe ratio result
        total_return: Total return percentage
        max_drawdown: Maximum drawdown percentage
        severity: Notification severity level

    Returns:
        True if notification sent successfully
    """
    try:
        event = BacktestEvent(
            title=f"Backtest Completed: {symbol} {strategy}",
            message=(
                f"Successfully completed backtest for {symbol} using {strategy} strategy. "
                f"Sharpe: {sharpe_ratio:.2f}, Return: {total_return:.2f}%, "
                f"Max DD: {max_drawdown:.2f}%"
            ) if sharpe_ratio is not None else f"Backtest completed for {symbol} using {strategy}",
            severity=severity,
            backtest_id=backtest_id,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            status="completed",
            sharpe_ratio=sharpe_ratio,
            total_return=total_return,
            max_drawdown=max_drawdown
        )

        service = await get_notification_service()
        return await service.notify(event)
    except Exception as exc:
        logger.error(f"Error sending backtest completion notification: {exc}")
        return False


async def notify_backtest_failed(
    backtest_id: str,
    strategy: str,
    symbol: str,
    timeframe: str,
    error_message: str,
    severity: NotificationSeverity = NotificationSeverity.ERROR
) -> bool:
    """Send notification for backtest failure.

    Args:
        backtest_id: Unique backtest identifier
        strategy: Strategy name
        symbol: Trading symbol
        timeframe: Bar timeframe
        error_message: Error description
        severity: Notification severity level

    Returns:
        True if notification sent successfully
    """
    try:
        event = BacktestEvent(
            title=f"Backtest Failed: {symbol} {strategy}",
            message=f"Backtest failed for {symbol} using {strategy}: {error_message}",
            severity=severity,
            backtest_id=backtest_id,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            status="failed",
            error_message=error_message
        )

        service = await get_notification_service()
        return await service.notify(event)
    except Exception as exc:
        logger.error(f"Error sending backtest failure notification: {exc}")
        return False


async def notify_order_filled(
    order_id: str,
    symbol: str,
    side: str,
    qty: float,
    filled_qty: float,
    avg_fill_price: float,
    order_type: str = "market",
    severity: NotificationSeverity = NotificationSeverity.INFO
) -> bool:
    """Send notification for order fill.

    Args:
        order_id: Unique order identifier
        symbol: Trading symbol
        side: Order side (buy/sell)
        qty: Order quantity
        filled_qty: Filled quantity
        avg_fill_price: Average fill price
        order_type: Order type
        severity: Notification severity level

    Returns:
        True if notification sent successfully
    """
    try:
        event = OrderEvent(
            title=f"Order Filled: {symbol} {side.upper()}",
            message=(
                f"Successfully filled {filled_qty}/{qty} shares of {symbol} "
                f"at ${avg_fill_price:.2f}"
            ),
            severity=severity,
            order_id=order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            order_type=order_type,
            status="filled",
            filled_qty=filled_qty,
            avg_fill_price=avg_fill_price
        )

        service = await get_notification_service()
        return await service.notify(event)
    except Exception as exc:
        logger.error(f"Error sending order fill notification: {exc}")
        return False


async def notify_order_rejected(
    order_id: str,
    symbol: str,
    side: str,
    qty: float,
    rejection_reason: str,
    order_type: str = "market",
    severity: NotificationSeverity = NotificationSeverity.WARNING
) -> bool:
    """Send notification for order rejection.

    Args:
        order_id: Unique order identifier
        symbol: Trading symbol
        side: Order side (buy/sell)
        qty: Order quantity
        rejection_reason: Reason for rejection
        order_type: Order type
        severity: Notification severity level

    Returns:
        True if notification sent successfully
    """
    try:
        event = OrderEvent(
            title=f"Order Rejected: {symbol} {side.upper()}",
            message=f"Order to {side} {qty} shares of {symbol} was rejected: {rejection_reason}",
            severity=severity,
            order_id=order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            order_type=order_type,
            status="rejected",
            rejection_reason=rejection_reason
        )

        service = await get_notification_service()
        return await service.notify(event)
    except Exception as exc:
        logger.error(f"Error sending order rejection notification: {exc}")
        return False


async def notify_agent_error(
    agent_name: str,
    thread_id: str,
    error: Exception,
    node_name: Optional[str] = None,
    recoverable: bool = False,
    severity: NotificationSeverity = NotificationSeverity.ERROR
) -> bool:
    """Send notification for agent execution error.

    Args:
        agent_name: Name of the agent
        thread_id: LangGraph thread ID
        error: The exception that occurred
        node_name: Graph node where error occurred
        recoverable: Whether the error is recoverable
        severity: Notification severity level

    Returns:
        True if notification sent successfully
    """
    try:
        error_traceback = "".join(traceback.format_exception(
            type(error), error, error.__traceback__
        ))

        event = AgentErrorEvent(
            title=f"Agent Error: {agent_name}",
            message=f"Error in {agent_name} agent: {str(error)}",
            severity=severity,
            agent_name=agent_name,
            thread_id=thread_id,
            node_name=node_name,
            error_type=type(error).__name__,
            error_traceback=error_traceback,
            recoverable=recoverable
        )

        service = await get_notification_service()
        return await service.notify(event)
    except Exception as exc:
        logger.error(f"Error sending agent error notification: {exc}")
        return False


async def notify_portfolio_event(
    portfolio_value: float,
    cash_balance: float,
    positions_count: int,
    change_reason: str,
    daily_pnl: Optional[float] = None,
    daily_pnl_pct: Optional[float] = None,
    severity: NotificationSeverity = NotificationSeverity.WARNING
) -> bool:
    """Send notification for significant portfolio changes.

    Args:
        portfolio_value: Current total portfolio value
        cash_balance: Available cash
        positions_count: Number of open positions
        change_reason: Reason for notification
        daily_pnl: Daily profit/loss
        daily_pnl_pct: Daily P&L percentage
        severity: Notification severity level

    Returns:
        True if notification sent successfully
    """
    try:
        event = PortfolioEvent(
            title=f"Portfolio Alert: {change_reason.replace('_', ' ').title()}",
            message=(
                f"Portfolio event triggered: {change_reason}. "
                f"Value: ${portfolio_value:,.2f}, Cash: ${cash_balance:,.2f}, "
                f"Positions: {positions_count}"
            ),
            severity=severity,
            portfolio_value=portfolio_value,
            cash_balance=cash_balance,
            positions_count=positions_count,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            change_reason=change_reason
        )

        service = await get_notification_service()
        return await service.notify(event)
    except Exception as exc:
        logger.error(f"Error sending portfolio event notification: {exc}")
        return False


if __name__ == "__main__":
    """Functional test for notification helpers."""
    import asyncio

    async def test_helpers():
        """Test helper functions."""
        print("=== Testing Notification Helpers ===\n")

        # Test backtest completion
        print("1. Testing backtest completion notification...")
        await notify_backtest_completed(
            backtest_id="bt_test_123",
            strategy="mean_reversion",
            symbol="AAPL",
            timeframe="1Min",
            sharpe_ratio=1.85,
            total_return=12.5,
            max_drawdown=-3.2
        )

        # Test backtest failure
        print("2. Testing backtest failure notification...")
        await notify_backtest_failed(
            backtest_id="bt_test_456",
            strategy="vwap_reversion",
            symbol="TSLA",
            timeframe="1Min",
            error_message="Insufficient data for backtest period"
        )

        # Test order filled
        print("3. Testing order fill notification...")
        await notify_order_filled(
            order_id="ord_test_789",
            symbol="GOOGL",
            side="buy",
            qty=50,
            filled_qty=50,
            avg_fill_price=2845.75
        )

        # Test order rejection
        print("4. Testing order rejection notification...")
        await notify_order_rejected(
            order_id="ord_test_101",
            symbol="MSFT",
            side="sell",
            qty=100,
            rejection_reason="Insufficient shares to sell"
        )

        # Test agent error
        print("5. Testing agent error notification...")
        try:
            raise ValueError("Test error for notification")
        except Exception as e:
            await notify_agent_error(
                agent_name="quant_analyst",
                thread_id="thread_test_202",
                error=e,
                node_name="analysis_node",
                recoverable=True
            )

        # Test portfolio event
        print("6. Testing portfolio event notification...")
        await notify_portfolio_event(
            portfolio_value=98500.0,
            cash_balance=42000.0,
            positions_count=5,
            change_reason="drawdown_threshold",
            daily_pnl=-1500.0,
            daily_pnl_pct=-1.5
        )

        print("\n[OK] All helper functions tested successfully")

    asyncio.run(test_helpers())
