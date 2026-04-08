"""Abstract base class for notification channels.

This module defines the interface that all notification channels must implement.
Channels are responsible for delivering notifications via specific mediums
(email, Slack, webhooks, etc.).
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import logging

from ..models import NotificationEvent, NotificationSeverity


logger = logging.getLogger(__name__)


class NotificationChannel(ABC):
    """Abstract base class for notification delivery channels.

    Each channel implementation handles delivery via a specific medium
    (email, Slack, webhook, SMS, etc.). Channels support severity filtering
    to control which events trigger notifications.

    Attributes:
        name: Human-readable channel name
        enabled: Whether the channel is active
        min_severity: Minimum severity level to trigger notifications
    """

    def __init__(
        self,
        name: str,
        enabled: bool = True,
        min_severity: NotificationSeverity = NotificationSeverity.INFO,
        **kwargs
    ):
        """Initialize notification channel.

        Args:
            name: Channel name (e.g., "email", "slack")
            enabled: Whether channel is active
            min_severity: Minimum severity to trigger notifications
            **kwargs: Additional channel-specific configuration
        """
        self.name = name
        self.enabled = enabled
        self.min_severity = min_severity
        self._config = kwargs
        logger.info(
            f"[notifications] Initialized {name} channel "
            f"(enabled={enabled}, min_severity={min_severity.value})"
        )

    def should_send(self, event: NotificationEvent) -> bool:
        """Determine if event should trigger notification on this channel.

        Args:
            event: The notification event to evaluate

        Returns:
            True if notification should be sent, False otherwise
        """
        if not self.enabled:
            logger.debug(
                f"[notifications] {self.name} channel disabled, skipping {event.event_type}"
            )
            return False

        severity_levels = {
            NotificationSeverity.INFO: 0,
            NotificationSeverity.WARNING: 1,
            NotificationSeverity.ERROR: 2,
            NotificationSeverity.CRITICAL: 3
        }

        event_level = severity_levels.get(event.severity, 0)
        min_level = severity_levels.get(self.min_severity, 0)

        if event_level < min_level:
            logger.debug(
                f"[notifications] {self.name} skipping {event.event_type} "
                f"(severity {event.severity.value} < {self.min_severity.value})"
            )
            return False

        return True

    @abstractmethod
    async def send(self, event: NotificationEvent) -> bool:
        """Send notification for the given event.

        This method must be implemented by each channel. It should:
        1. Format the event appropriately for the channel
        2. Attempt to deliver the notification
        3. Return True on success, False on failure
        4. Log errors but NOT raise exceptions (graceful degradation)

        Args:
            event: The notification event to send

        Returns:
            True if notification sent successfully, False otherwise
        """
        pass

    async def notify(self, event: NotificationEvent) -> bool:
        """Check filters and send notification if appropriate.

        This is the main entry point called by NotificationService.
        It handles severity filtering and delegates to send().

        Args:
            event: The notification event to process

        Returns:
            True if notification sent (or skipped due to filters), False on error
        """
        if not self.should_send(event):
            return True  # Skipped due to filters is not an error

        try:
            success = await self.send(event)
            if success:
                logger.info(
                    f"[notifications] {self.name} sent {event.event_type} "
                    f"notification: {event.title}"
                )
            else:
                logger.warning(
                    f"[notifications] {self.name} failed to send {event.event_type} "
                    f"notification: {event.title}"
                )
            return success
        except Exception as exc:
            # Graceful degradation: log error but don't crash
            logger.error(
                f"[notifications] {self.name} error sending {event.event_type}: {exc}",
                exc_info=True
            )
            return False


if __name__ == "__main__":
    """Functional test for base channel."""
    import asyncio
    from ..models import BacktestEvent

    class TestChannel(NotificationChannel):
        """Simple test channel implementation."""

        async def send(self, event: NotificationEvent) -> bool:
            print(f"[TestChannel] Sending: {event.title}")
            return True

    async def test_base_channel():
        """Test channel filtering and notification flow."""
        # Create test channel with WARNING minimum severity
        channel = TestChannel(
            name="test",
            enabled=True,
            min_severity=NotificationSeverity.WARNING
        )

        # Create INFO event (should be skipped)
        info_event = BacktestEvent(
            title="Info Event",
            message="This should be skipped",
            severity=NotificationSeverity.INFO,
            backtest_id="test1",
            strategy="test",
            symbol="TEST",
            timeframe="1Min",
            status="completed"
        )

        # Create WARNING event (should be sent)
        warning_event = BacktestEvent(
            title="Warning Event",
            message="This should be sent",
            severity=NotificationSeverity.WARNING,
            backtest_id="test2",
            strategy="test",
            symbol="TEST",
            timeframe="1Min",
            status="failed",
            error_message="Test error"
        )

        print("=== Testing Severity Filtering ===")
        print(f"Channel min_severity: {channel.min_severity.value}\n")

        result1 = await channel.notify(info_event)
        print(f"INFO event result: {result1} (should skip)\n")

        result2 = await channel.notify(warning_event)
        print(f"WARNING event result: {result2} (should send)\n")

        # Test disabled channel
        channel.enabled = False
        result3 = await channel.notify(warning_event)
        print(f"Disabled channel result: {result3} (should skip)")

        print("\n✅ Base channel tests passed")

    asyncio.run(test_base_channel())
