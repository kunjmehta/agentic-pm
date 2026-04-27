"""Generic webhook notification channel.

This module implements generic HTTP POST notifications to custom webhooks.
It sends JSON payloads containing the full event data, making it suitable
for integration with custom systems, logging platforms, or monitoring tools.
"""

import logging
from typing import Optional, Dict, Any
import aiohttp
import os

from .base import NotificationChannel
from ..models import NotificationEvent, NotificationSeverity


logger = logging.getLogger(__name__)


class WebhookChannel(NotificationChannel):
    """Generic webhook notification channel.

    Sends JSON payloads via HTTP POST to a configurable webhook URL.
    Useful for integrating with custom systems, monitoring platforms,
    or aggregating notifications in a central service.

    Attributes:
        webhook_url: Target webhook URL
        headers: Optional HTTP headers to include in requests
        timeout: Request timeout in seconds
    """

    def __init__(
        self,
        enabled: bool = True,
        min_severity: NotificationSeverity = NotificationSeverity.INFO,
        webhook_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 10,
        **kwargs
    ):
        """Initialize webhook channel.

        Args:
            enabled: Whether channel is active
            min_severity: Minimum severity to send webhooks
            webhook_url: Target webhook URL
            headers: Optional HTTP headers (e.g., authentication)
            timeout: Request timeout in seconds
            **kwargs: Additional configuration
        """
        super().__init__(
            name="webhook",
            enabled=enabled,
            min_severity=min_severity,
            **kwargs
        )

        self.webhook_url = webhook_url or os.getenv("WEBHOOK_URL")
        self.headers = headers or {}
        self.timeout = timeout

        # Add Content-Type header
        if "Content-Type" not in self.headers:
            self.headers["Content-Type"] = "application/json"

        # Validate configuration
        if enabled and not self.webhook_url:
            logger.warning(
                "[notifications] Webhook channel enabled but no URL provided. "
                "Set WEBHOOK_URL in configuration or environment."
            )
            self.enabled = False

    def _format_payload(self, event: NotificationEvent) -> Dict[str, Any]:
        """Format webhook payload from event.

        Args:
            event: Notification event

        Returns:
            JSON-serializable payload
        """
        # Convert event to dict and add metadata
        payload = event.model_dump()

        # Add webhook-specific metadata
        payload["_webhook_metadata"] = {
            "channel": self.name,
            "severity": event.severity.value,
            "event_type": event.event_type
        }

        return payload

    async def send(self, event: NotificationEvent) -> bool:
        """Send webhook notification via HTTP POST.

        Args:
            event: The notification event to send

        Returns:
            True if webhook request successful, False otherwise
        """
        try:
            # Format payload
            payload = self._format_payload(event)

            # Send HTTP POST request
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    # Accept 2xx status codes as success
                    if 200 <= response.status < 300:
                        logger.info(
                            f"[notifications] Webhook sent successfully "
                            f"(status={response.status})"
                        )
                        return True
                    else:
                        error_text = await response.text()
                        logger.warning(
                            f"[notifications] Webhook returned status {response.status}: "
                            f"{error_text}"
                        )
                        return False

        except aiohttp.ClientError as exc:
            logger.error(
                f"[notifications] Webhook request failed: {exc}",
                exc_info=True
            )
            return False
        except Exception as exc:
            logger.error(
                f"[notifications] Webhook send error: {exc}",
                exc_info=True
            )
            return False


if __name__ == "__main__":
    """Functional test for webhook channel."""
    import asyncio
    from ..models import BacktestEvent, OrderEvent

    async def test_webhook_channel():
        """Test webhook formatting and configuration."""
        # Create channel (will be disabled without URL)
        channel = WebhookChannel(
            enabled=True,
            min_severity=NotificationSeverity.INFO,
            headers={"Authorization": "Bearer test_token"}
        )

        # Create test events
        backtest_event = BacktestEvent(
            title="Test Backtest",
            message="Test message",
            severity=NotificationSeverity.INFO,
            backtest_id="test_123",
            strategy="mean_reversion",
            symbol="AAPL",
            timeframe="1Min",
            status="completed",
            sharpe_ratio=1.85,
            total_return=12.5,
            max_drawdown=-3.2
        )

        order_event = OrderEvent(
            title="Test Order",
            message="Test order execution",
            severity=NotificationSeverity.INFO,
            order_id="ord_123",
            symbol="AAPL",
            side="buy",
            qty=100,
            order_type="market",
            status="filled",
            filled_qty=100,
            avg_fill_price=150.25
        )

        # Test payload formatting
        print("=== Backtest Event Webhook Payload ===")
        import json
        payload1 = channel._format_payload(backtest_event)
        print(json.dumps(payload1, indent=2, default=str))

        print("\n=== Order Event Webhook Payload ===")
        payload2 = channel._format_payload(order_event)
        print(json.dumps(payload2, indent=2, default=str))

        # Verify webhook metadata
        assert "_webhook_metadata" in payload1
        assert payload1["_webhook_metadata"]["event_type"] == "backtest"
        assert payload1["_webhook_metadata"]["severity"] == "INFO"

        print("\n✅ Webhook channel structure validated")

    asyncio.run(test_webhook_channel())
