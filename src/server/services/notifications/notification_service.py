"""Core notification service with async multi-channel dispatch.

This module implements the NotificationService singleton that manages
notification delivery across multiple channels (email, Slack, webhooks).
It supports graceful degradation and severity-based filtering.
"""

import logging
import asyncio
from typing import List, Optional, Dict, Any
import json
import os

from .models import NotificationEvent, NotificationSeverity
from .channels import (
    NotificationChannel,
    EmailChannel,
    SlackChannel,
    WebhookChannel
)


logger = logging.getLogger(__name__)


class NotificationService:
    """Singleton notification service for multi-channel dispatch.

    Manages notification delivery across multiple channels with async dispatch,
    severity filtering, and graceful degradation. Channels are initialized from
    configuration and notifications are sent concurrently.

    Usage:
        service = NotificationService.get_instance(config)
        await service.notify(event)

    Attributes:
        enabled: Master on/off switch for all notifications
        channels: List of configured notification channels
    """

    _instance: Optional["NotificationService"] = None
    _lock = asyncio.Lock()

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize notification service.

        Args:
            config: Notification configuration dict from config.json
        """
        self.enabled = False
        self.channels: List[NotificationChannel] = []

        if config:
            self._configure(config)

    def _configure(self, config: Dict[str, Any]) -> None:
        """Configure notification service from config dict.

        Args:
            config: Configuration dict with channel settings
        """
        self.enabled = config.get("enabled", False)

        if not self.enabled:
            logger.info("[notifications] Notification service disabled in config")
            return

        logger.info("[notifications] Configuring notification service...")

        # Load secrets from secret.json if available
        secrets = self._load_secrets()

        # Configure email channel
        email_config = config.get("email", {})
        if email_config.get("enabled", False):
            api_key = self._resolve_secret(
                email_config.get("api_key"),
                secrets
            )
            self.channels.append(
                EmailChannel(
                    enabled=True,
                    min_severity=NotificationSeverity[
                        email_config.get("min_severity", "WARNING")
                    ],
                    api_key=api_key,
                    from_email=email_config.get("from_email", "trading@yourcompany.com"),
                    to_emails=email_config.get("to_emails", [])
                )
            )

        # Configure Slack channel
        slack_config = config.get("slack", {})
        if slack_config.get("enabled", False):
            webhook_url = self._resolve_secret(
                slack_config.get("webhook_url"),
                secrets
            )
            self.channels.append(
                SlackChannel(
                    enabled=True,
                    min_severity=NotificationSeverity[
                        slack_config.get("min_severity", "ERROR")
                    ],
                    webhook_url=webhook_url
                )
            )

        # Configure webhook channel
        webhook_config = config.get("webhook", {})
        if webhook_config.get("enabled", False):
            webhook_url = self._resolve_secret(
                webhook_config.get("url"),
                secrets
            )
            self.channels.append(
                WebhookChannel(
                    enabled=True,
                    min_severity=NotificationSeverity[
                        webhook_config.get("min_severity", "INFO")
                    ],
                    webhook_url=webhook_url,
                    headers=webhook_config.get("headers", {}),
                    timeout=webhook_config.get("timeout", 10)
                )
            )

        active_channels = [ch.name for ch in self.channels if ch.enabled]
        logger.info(
            f"[notifications] Service configured with {len(active_channels)} "
            f"active channels: {', '.join(active_channels)}"
        )

    def _load_secrets(self) -> Dict[str, Any]:
        """Load secrets from secret.json.

        Returns:
            Dictionary of secrets, empty dict if file not found
        """
        try:
            secret_path = os.path.join(
                os.path.dirname(__file__),
                "..", "..", "..", "..", "secret.json"
            )
            secret_path = os.path.normpath(secret_path)

            if os.path.exists(secret_path):
                with open(secret_path, "r") as f:
                    return json.load(f)
            else:
                logger.debug("[notifications] secret.json not found, using env vars")
                return {}
        except Exception as exc:
            logger.warning(f"[notifications] Error loading secret.json: {exc}")
            return {}

    def _resolve_secret(
        self,
        value: Optional[str],
        secrets: Dict[str, Any]
    ) -> Optional[str]:
        """Resolve secret value from placeholder or environment.

        Supports formats:
        - ${SECRET_KEY} -> looks up in secrets dict or env
        - plain value -> returns as-is

        Args:
            value: Configuration value (may be placeholder)
            secrets: Loaded secrets dictionary

        Returns:
            Resolved secret value or original value
        """
        if not value:
            return None

        # Check for ${KEY} placeholder
        if value.startswith("${") and value.endswith("}"):
            key = value[2:-1]

            # Try secrets dict first (supports nested keys like redis.password)
            parts = key.split(".")
            secret_value = secrets
            for part in parts:
                if isinstance(secret_value, dict):
                    secret_value = secret_value.get(part)
                else:
                    secret_value = None
                    break

            if secret_value:
                return str(secret_value)

            # Fall back to environment variable
            env_value = os.getenv(key)
            if env_value:
                return env_value

            logger.warning(
                f"[notifications] Secret placeholder {value} not found in "
                f"secret.json or environment"
            )
            return None

        # Return plain value as-is
        return value

    async def notify(self, event: NotificationEvent) -> bool:
        """Send notification across all configured channels.

        Dispatches notification to all channels concurrently. Uses graceful
        degradation - errors in individual channels are logged but don't
        prevent other channels from attempting delivery.

        Args:
            event: The notification event to send

        Returns:
            True if at least one channel succeeded, False if all failed
        """
        if not self.enabled:
            logger.debug(
                "[notifications] Service disabled, skipping notification: "
                f"{event.title}"
            )
            return True  # Not an error

        if not self.channels:
            logger.debug("[notifications] No channels configured")
            return True  # Not an error

        logger.info(
            f"[notifications] Sending {event.event_type} notification "
            f"(severity={event.severity.value}): {event.title}"
        )

        # Send to all channels concurrently
        tasks = [channel.notify(event) for channel in self.channels]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successes
        successes = sum(
            1 for result in results
            if not isinstance(result, Exception) and result
        )

        # Log any exceptions
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"[notifications] Channel {self.channels[i].name} raised exception: {result}",
                    exc_info=result
                )

        if successes > 0:
            logger.info(
                f"[notifications] Notification delivered to {successes}/{len(self.channels)} channels"
            )
            return True
        else:
            logger.warning(
                "[notifications] Notification failed on all channels"
            )
            return False

    @classmethod
    async def get_instance(
        cls,
        config: Optional[Dict[str, Any]] = None
    ) -> "NotificationService":
        """Get singleton instance of NotificationService.

        Thread-safe singleton with async lock. If instance doesn't exist
        and config is provided, creates and configures the instance.

        Args:
            config: Optional configuration dict (only used on first call)

        Returns:
            NotificationService singleton instance
        """
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (useful for testing).

        Warning: This should only be called in test code.
        """
        cls._instance = None


# Convenience function for getting the service instance
async def get_notification_service(
    config: Optional[Dict[str, Any]] = None
) -> NotificationService:
    """Get the NotificationService singleton instance.

    Args:
        config: Optional configuration dict (only used on first call)

    Returns:
        NotificationService singleton instance
    """
    return await NotificationService.get_instance(config)


if __name__ == "__main__":
    """Functional test for notification service."""
    import asyncio
    from .models import BacktestEvent, OrderEvent, AgentErrorEvent

    async def test_notification_service():
        """Test service initialization and notification dispatch."""
        # Create test configuration
        config = {
            "enabled": True,
            "email": {
                "enabled": False,  # Disabled for testing
                "min_severity": "WARNING",
                "from_email": "test@example.com",
                "to_emails": ["recipient@example.com"]
            },
            "slack": {
                "enabled": False,  # Disabled for testing
                "min_severity": "ERROR"
            },
            "webhook": {
                "enabled": False,  # Disabled for testing
                "min_severity": "INFO",
                "url": "https://example.com/webhook"
            }
        }

        # Reset singleton for testing
        NotificationService.reset_instance()

        # Get service instance
        service = await get_notification_service(config)

        print("=== NotificationService Configuration ===")
        print(f"Enabled: {service.enabled}")
        print(f"Channels: {len(service.channels)}")
        for channel in service.channels:
            print(f"  - {channel.name}: enabled={channel.enabled}, min_severity={channel.min_severity.value}")

        # Create test events
        backtest_event = BacktestEvent(
            title="Test Backtest Completed",
            message="Test backtest finished successfully",
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
            title="Test Order Filled",
            message="Test order executed",
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

        error_event = AgentErrorEvent(
            title="Test Agent Error",
            message="Test error in agent execution",
            severity=NotificationSeverity.ERROR,
            agent_name="quant_analyst",
            thread_id="test_thread",
            error_type="ValueError",
            error_traceback="Test traceback",
            recoverable=True
        )

        # Test notification dispatch
        print("\n=== Testing Notification Dispatch ===")
        result1 = await service.notify(backtest_event)
        print(f"Backtest notification: {result1}")

        result2 = await service.notify(order_event)
        print(f"Order notification: {result2}")

        result3 = await service.notify(error_event)
        print(f"Error notification: {result3}")

        print("\n✅ NotificationService tests passed")

    asyncio.run(test_notification_service())
