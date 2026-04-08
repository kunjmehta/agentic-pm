"""Unit tests for notification system.

Tests notification models, channels, and service with mock integrations.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.server.services.notifications.models import (
    NotificationEvent,
    BacktestEvent,
    OrderEvent,
    AgentErrorEvent,
    PortfolioEvent,
    NotificationSeverity
)
from src.server.services.notifications.channels.base import NotificationChannel
from src.server.services.notifications.channels.email_channel import EmailChannel
from src.server.services.notifications.channels.slack_channel import SlackChannel
from src.server.services.notifications.channels.webhook_channel import WebhookChannel
from src.server.services.notifications.notification_service import NotificationService
from src.server.services.notifications.helpers import (
    notify_backtest_completed,
    notify_backtest_failed,
    notify_order_filled,
    notify_order_rejected,
    notify_agent_error
)


# ── Test Models ────────────────────────────────────────────────────────────────────


def test_backtest_event_creation():
    """Test BacktestEvent model creation and serialization."""
    event = BacktestEvent(
        title="Test Backtest",
        message="Test message",
        severity=NotificationSeverity.INFO,
        backtest_id="bt_123",
        strategy="mean_reversion",
        symbol="AAPL",
        timeframe="1Min",
        status="completed",
        sharpe_ratio=1.85,
        total_return=12.5,
        max_drawdown=-3.2
    )

    assert event.event_type == "backtest"
    assert event.backtest_id == "bt_123"
    assert event.strategy == "mean_reversion"
    assert event.sharpe_ratio == 1.85

    # Test serialization
    data = event.model_dump()
    assert data["event_type"] == "backtest"
    assert data["severity"] == "INFO"


def test_order_event_creation():
    """Test OrderEvent model creation."""
    event = OrderEvent(
        title="Order Filled",
        message="Order executed",
        severity=NotificationSeverity.INFO,
        order_id="ord_123",
        symbol="TSLA",
        side="buy",
        qty=100,
        order_type="market",
        status="filled",
        filled_qty=100,
        avg_fill_price=150.25
    )

    assert event.event_type == "order"
    assert event.order_id == "ord_123"
    assert event.side == "buy"
    assert event.filled_qty == 100


def test_agent_error_event_creation():
    """Test AgentErrorEvent model creation."""
    event = AgentErrorEvent(
        title="Agent Error",
        message="Error occurred",
        severity=NotificationSeverity.ERROR,
        agent_name="quant_analyst",
        thread_id="thread_123",
        error_type="ValueError",
        error_traceback="Traceback...",
        recoverable=True
    )

    assert event.event_type == "agent_error"
    assert event.agent_name == "quant_analyst"
    assert event.recoverable is True


def test_portfolio_event_creation():
    """Test PortfolioEvent model creation."""
    event = PortfolioEvent(
        title="Portfolio Alert",
        message="Drawdown threshold exceeded",
        severity=NotificationSeverity.WARNING,
        portfolio_value=95000.0,
        cash_balance=45000.0,
        positions_count=3,
        daily_pnl=-2500.0,
        daily_pnl_pct=-2.56,
        change_reason="drawdown_threshold"
    )

    assert event.event_type == "portfolio"
    assert event.portfolio_value == 95000.0
    assert event.positions_count == 3


# ── Test Channels ──────────────────────────────────────────────────────────────────


class MockChannel(NotificationChannel):
    """Mock channel for testing base functionality."""

    def __init__(self, **kwargs):
        super().__init__(name="mock", **kwargs)
        self.sent_events = []

    async def send(self, event: NotificationEvent) -> bool:
        self.sent_events.append(event)
        return True


@pytest.mark.asyncio
async def test_channel_severity_filtering():
    """Test channel severity filtering logic."""
    # Create channel with WARNING minimum severity
    channel = MockChannel(
        enabled=True,
        min_severity=NotificationSeverity.WARNING
    )

    # Create INFO event (should be skipped)
    info_event = BacktestEvent(
        title="Info Event",
        message="Test",
        severity=NotificationSeverity.INFO,
        backtest_id="test",
        strategy="test",
        symbol="TEST",
        timeframe="1Min",
        status="completed"
    )

    # Create WARNING event (should be sent)
    warning_event = BacktestEvent(
        title="Warning Event",
        message="Test",
        severity=NotificationSeverity.WARNING,
        backtest_id="test",
        strategy="test",
        symbol="TEST",
        timeframe="1Min",
        status="failed",
        error_message="Test error"
    )

    # Test filtering
    await channel.notify(info_event)
    assert len(channel.sent_events) == 0  # Skipped due to severity

    await channel.notify(warning_event)
    assert len(channel.sent_events) == 1  # Sent


@pytest.mark.asyncio
async def test_channel_disabled():
    """Test disabled channel behavior."""
    channel = MockChannel(enabled=False)

    event = BacktestEvent(
        title="Test",
        message="Test",
        severity=NotificationSeverity.ERROR,
        backtest_id="test",
        strategy="test",
        symbol="TEST",
        timeframe="1Min",
        status="completed"
    )

    result = await channel.notify(event)
    assert result is True  # Returns true but doesn't send
    assert len(channel.sent_events) == 0


@pytest.mark.asyncio
async def test_email_channel_html_formatting():
    """Test email channel HTML formatting."""
    channel = EmailChannel(
        enabled=False,  # Disabled to avoid actual sending
        from_email="test@example.com",
        to_emails=["recipient@example.com"]
    )

    event = BacktestEvent(
        title="Test Backtest",
        message="Test message",
        severity=NotificationSeverity.INFO,
        backtest_id="bt_123",
        strategy="mean_reversion",
        symbol="AAPL",
        timeframe="1Min",
        status="completed",
        sharpe_ratio=1.85,
        total_return=12.5,
        max_drawdown=-3.2
    )

    html = channel._format_backtest_email(event)
    assert "Test Backtest" in html
    assert "AAPL" in html
    assert "1.85" in html  # Sharpe ratio
    assert "12.5" in html  # Return


@pytest.mark.asyncio
async def test_slack_channel_message_formatting():
    """Test Slack channel message formatting."""
    channel = SlackChannel(
        enabled=False  # Disabled to avoid actual sending
    )

    event = BacktestEvent(
        title="Test Backtest",
        message="Test message",
        severity=NotificationSeverity.INFO,
        backtest_id="bt_123",
        strategy="mean_reversion",
        symbol="AAPL",
        timeframe="1Min",
        status="completed",
        sharpe_ratio=1.85,
        total_return=12.5,
        max_drawdown=-3.2
    )

    payload = channel._format_backtest_message(event)
    assert "text" in payload
    assert "attachments" in payload
    assert len(payload["attachments"]) > 0
    assert payload["attachments"][0]["color"] == "good"  # INFO = green


@pytest.mark.asyncio
async def test_webhook_channel_payload_formatting():
    """Test webhook channel payload formatting."""
    channel = WebhookChannel(
        enabled=False  # Disabled to avoid actual sending
    )

    event = OrderEvent(
        title="Order Filled",
        message="Order executed",
        severity=NotificationSeverity.INFO,
        order_id="ord_123",
        symbol="TSLA",
        side="buy",
        qty=100,
        order_type="market",
        status="filled",
        filled_qty=100,
        avg_fill_price=150.25
    )

    payload = channel._format_payload(event)
    assert payload["event_type"] == "order"
    assert payload["order_id"] == "ord_123"
    assert "_webhook_metadata" in payload
    assert payload["_webhook_metadata"]["severity"] == "INFO"


# ── Test Service ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notification_service_initialization():
    """Test NotificationService initialization from config."""
    config = {
        "enabled": True,
        "email": {
            "enabled": True,  # Enable for testing
            "min_severity": "WARNING",
            "api_key": "test_key",  # Provide dummy key
            "from_email": "test@example.com",
            "to_emails": ["recipient@example.com"]
        },
        "slack": {
            "enabled": True,  # Enable for testing
            "webhook_url": "https://hooks.slack.com/test",  # Provide dummy URL
            "min_severity": "ERROR"
        }
    }

    # Reset singleton
    NotificationService.reset_instance()

    service = await NotificationService.get_instance(config)
    assert service.enabled is True
    assert len(service.channels) == 2  # Email + Slack
    # Channels should be disabled due to invalid credentials, but still instantiated
    assert service.channels[0].name == "email"
    assert service.channels[1].name == "slack"


@pytest.mark.asyncio
async def test_notification_service_dispatch():
    """Test multi-channel notification dispatch."""
    # Reset singleton
    NotificationService.reset_instance()

    # Create service with mock channels
    service = NotificationService()
    service.enabled = True
    service.channels = [
        MockChannel(enabled=True, min_severity=NotificationSeverity.INFO),
        MockChannel(enabled=True, min_severity=NotificationSeverity.WARNING)
    ]

    # Create INFO event
    event = BacktestEvent(
        title="Test",
        message="Test",
        severity=NotificationSeverity.INFO,
        backtest_id="test",
        strategy="test",
        symbol="TEST",
        timeframe="1Min",
        status="completed"
    )

    # Dispatch
    result = await service.notify(event)
    assert result is True

    # First channel should receive (INFO >= INFO)
    assert len(service.channels[0].sent_events) == 1

    # Second channel should skip (INFO < WARNING)
    assert len(service.channels[1].sent_events) == 0


@pytest.mark.asyncio
async def test_notification_service_disabled():
    """Test service behavior when disabled."""
    # Reset singleton
    NotificationService.reset_instance()

    service = NotificationService()
    service.enabled = False
    service.channels = [MockChannel(enabled=True)]

    event = BacktestEvent(
        title="Test",
        message="Test",
        severity=NotificationSeverity.ERROR,
        backtest_id="test",
        strategy="test",
        symbol="TEST",
        timeframe="1Min",
        status="failed"
    )

    result = await service.notify(event)
    assert result is True  # Returns true but doesn't send
    assert len(service.channels[0].sent_events) == 0


# ── Test Helpers ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_helper_notify_backtest_completed():
    """Test backtest completion helper function."""
    # Reset singleton and create mock service
    NotificationService.reset_instance()
    service = NotificationService()
    service.enabled = True
    mock_channel = MockChannel(enabled=True)
    service.channels = [mock_channel]

    # Manually set singleton instance for testing
    NotificationService._instance = service

    # Call helper
    result = await notify_backtest_completed(
        backtest_id="bt_123",
        strategy="mean_reversion",
        symbol="AAPL",
        timeframe="1Min",
        sharpe_ratio=1.85,
        total_return=12.5,
        max_drawdown=-3.2
    )

    assert result is True
    assert len(mock_channel.sent_events) == 1
    event = mock_channel.sent_events[0]
    assert isinstance(event, BacktestEvent)
    assert event.backtest_id == "bt_123"
    assert event.status == "completed"


@pytest.mark.asyncio
async def test_helper_notify_order_filled():
    """Test order fill helper function."""
    # Reset singleton and create mock service
    NotificationService.reset_instance()
    service = NotificationService()
    service.enabled = True
    mock_channel = MockChannel(enabled=True)
    service.channels = [mock_channel]
    NotificationService._instance = service

    # Call helper
    result = await notify_order_filled(
        order_id="ord_123",
        symbol="TSLA",
        side="buy",
        qty=100,
        filled_qty=100,
        avg_fill_price=250.50
    )

    assert result is True
    assert len(mock_channel.sent_events) == 1
    event = mock_channel.sent_events[0]
    assert isinstance(event, OrderEvent)
    assert event.order_id == "ord_123"
    assert event.status == "filled"


@pytest.mark.asyncio
async def test_helper_notify_agent_error():
    """Test agent error helper function."""
    # Reset singleton and create mock service
    NotificationService.reset_instance()
    service = NotificationService()
    service.enabled = True
    mock_channel = MockChannel(enabled=True)
    service.channels = [mock_channel]
    NotificationService._instance = service

    # Create test exception
    try:
        raise ValueError("Test error")
    except Exception as exc:
        result = await notify_agent_error(
            agent_name="quant_analyst",
            thread_id="thread_123",
            error=exc,
            node_name="test_node",
            recoverable=True
        )

    assert result is True
    assert len(mock_channel.sent_events) == 1
    event = mock_channel.sent_events[0]
    assert isinstance(event, AgentErrorEvent)
    assert event.agent_name == "quant_analyst"
    assert event.error_type == "ValueError"
    assert "Test error" in event.error_traceback


if __name__ == "__main__":
    """Run tests with pytest."""
    pytest.main([__file__, "-v"])
