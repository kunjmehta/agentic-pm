"""Slack notification channel using webhooks.

This module implements Slack notifications via incoming webhooks. It supports
color-coded attachments based on severity and formats messages appropriately
for Slack's block-based UI.
"""

import logging
from typing import Optional, Dict, Any
import aiohttp
import os

from .base import NotificationChannel
from ..models import (
    NotificationEvent,
    NotificationSeverity,
    BacktestEvent,
    OrderEvent,
    AgentErrorEvent,
    PortfolioEvent
)


logger = logging.getLogger(__name__)


class SlackChannel(NotificationChannel):
    """Slack notification channel using webhooks.

    Sends formatted messages to Slack using incoming webhooks.
    Messages include color-coded attachments based on severity.

    Attributes:
        webhook_url: Slack incoming webhook URL
    """

    def __init__(
        self,
        enabled: bool = True,
        min_severity: NotificationSeverity = NotificationSeverity.ERROR,
        webhook_url: Optional[str] = None,
        **kwargs
    ):
        """Initialize Slack channel.

        Args:
            enabled: Whether channel is active
            min_severity: Minimum severity to send Slack messages
            webhook_url: Slack incoming webhook URL
            **kwargs: Additional configuration
        """
        super().__init__(
            name="slack",
            enabled=enabled,
            min_severity=min_severity,
            **kwargs
        )

        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")

        # Validate configuration
        if enabled and not self.webhook_url:
            logger.warning(
                "[notifications] Slack channel enabled but no webhook URL provided. "
                "Set SLACK_WEBHOOK_URL in secret.json or environment."
            )
            self.enabled = False

    def _get_severity_color(self, severity: NotificationSeverity) -> str:
        """Get Slack attachment color for severity level.

        Args:
            severity: Notification severity

        Returns:
            Slack color code (good, warning, danger, or hex)
        """
        colors = {
            NotificationSeverity.INFO: "good",        # Green
            NotificationSeverity.WARNING: "warning",  # Orange
            NotificationSeverity.ERROR: "danger",     # Red
            NotificationSeverity.CRITICAL: "#9C27B0"  # Purple
        }
        return colors.get(severity, "#757575")  # Gray default

    def _get_severity_emoji(self, severity: NotificationSeverity) -> str:
        """Get emoji for severity level.

        Args:
            severity: Notification severity

        Returns:
            Emoji string
        """
        emojis = {
            NotificationSeverity.INFO: ":information_source:",
            NotificationSeverity.WARNING: ":warning:",
            NotificationSeverity.ERROR: ":x:",
            NotificationSeverity.CRITICAL: ":rotating_light:"
        }
        return emojis.get(severity, ":bell:")

    def _format_backtest_message(self, event: BacktestEvent) -> Dict[str, Any]:
        """Format Slack message for backtest events.

        Args:
            event: Backtest event

        Returns:
            Slack message payload
        """
        color = self._get_severity_color(event.severity)
        emoji = self._get_severity_emoji(event.severity)

        fields = [
            {
                "title": "Backtest ID",
                "value": event.backtest_id,
                "short": True
            },
            {
                "title": "Strategy",
                "value": event.strategy,
                "short": True
            },
            {
                "title": "Symbol",
                "value": event.symbol,
                "short": True
            },
            {
                "title": "Timeframe",
                "value": event.timeframe,
                "short": True
            },
            {
                "title": "Status",
                "value": event.status.upper(),
                "short": True
            }
        ]

        if event.status == "completed":
            fields.extend([
                {
                    "title": "Sharpe Ratio",
                    "value": f"{event.sharpe_ratio:.2f}" if event.sharpe_ratio else "N/A",
                    "short": True
                },
                {
                    "title": "Total Return",
                    "value": f"{event.total_return:.2f}%" if event.total_return else "N/A",
                    "short": True
                },
                {
                    "title": "Max Drawdown",
                    "value": f"{event.max_drawdown:.2f}%" if event.max_drawdown else "N/A",
                    "short": True
                }
            ])
        elif event.error_message:
            fields.append({
                "title": "Error",
                "value": f"```{event.error_message}```",
                "short": False
            })

        return {
            "text": f"{emoji} *{event.title}*",
            "attachments": [
                {
                    "color": color,
                    "text": event.message,
                    "fields": fields,
                    "footer": "Agentic Trader",
                    "ts": int(event.timestamp.timestamp())
                }
            ]
        }

    def _format_order_message(self, event: OrderEvent) -> Dict[str, Any]:
        """Format Slack message for order events.

        Args:
            event: Order event

        Returns:
            Slack message payload
        """
        color = self._get_severity_color(event.severity)
        emoji = self._get_severity_emoji(event.severity)

        fields = [
            {
                "title": "Order ID",
                "value": event.order_id,
                "short": True
            },
            {
                "title": "Symbol",
                "value": event.symbol,
                "short": True
            },
            {
                "title": "Side",
                "value": event.side.upper(),
                "short": True
            },
            {
                "title": "Quantity",
                "value": str(event.qty),
                "short": True
            },
            {
                "title": "Type",
                "value": event.order_type,
                "short": True
            },
            {
                "title": "Status",
                "value": event.status.upper(),
                "short": True
            }
        ]

        if event.filled_qty is not None:
            fields.append({
                "title": "Filled Qty",
                "value": str(event.filled_qty),
                "short": True
            })

        if event.avg_fill_price is not None:
            fields.append({
                "title": "Avg Fill Price",
                "value": f"${event.avg_fill_price:.2f}",
                "short": True
            })

        if event.rejection_reason:
            fields.append({
                "title": "Rejection Reason",
                "value": event.rejection_reason,
                "short": False
            })

        return {
            "text": f"{emoji} *{event.title}*",
            "attachments": [
                {
                    "color": color,
                    "text": event.message,
                    "fields": fields,
                    "footer": "Agentic Trader",
                    "ts": int(event.timestamp.timestamp())
                }
            ]
        }

    def _format_agent_error_message(self, event: AgentErrorEvent) -> Dict[str, Any]:
        """Format Slack message for agent error events.

        Args:
            event: Agent error event

        Returns:
            Slack message payload
        """
        color = self._get_severity_color(event.severity)
        emoji = self._get_severity_emoji(event.severity)

        fields = [
            {
                "title": "Agent",
                "value": event.agent_name,
                "short": True
            },
            {
                "title": "Thread ID",
                "value": event.thread_id,
                "short": True
            },
            {
                "title": "Error Type",
                "value": event.error_type,
                "short": True
            },
            {
                "title": "Recoverable",
                "value": "Yes" if event.recoverable else "No",
                "short": True
            }
        ]

        if event.node_name:
            fields.append({
                "title": "Node",
                "value": event.node_name,
                "short": True
            })

        # Truncate traceback for Slack (max 3000 chars in field)
        traceback = event.error_traceback[:2900] if event.error_traceback else "N/A"
        if len(event.error_traceback) > 2900:
            traceback += "\n... (truncated)"

        fields.append({
            "title": "Traceback",
            "value": f"```{traceback}```",
            "short": False
        })

        return {
            "text": f"{emoji} *{event.title}*",
            "attachments": [
                {
                    "color": color,
                    "text": event.message,
                    "fields": fields,
                    "footer": "Agentic Trader",
                    "ts": int(event.timestamp.timestamp())
                }
            ]
        }

    def _format_generic_message(self, event: NotificationEvent) -> Dict[str, Any]:
        """Format generic Slack message for any event type.

        Args:
            event: Notification event

        Returns:
            Slack message payload
        """
        color = self._get_severity_color(event.severity)
        emoji = self._get_severity_emoji(event.severity)

        fields = [
            {
                "title": "Event Type",
                "value": event.event_type.upper(),
                "short": True
            },
            {
                "title": "Severity",
                "value": event.severity.value,
                "short": True
            }
        ]

        # Add metadata as fields
        if event.metadata:
            for key, value in event.metadata.items():
                fields.append({
                    "title": key.replace("_", " ").title(),
                    "value": str(value),
                    "short": True
                })

        return {
            "text": f"{emoji} *{event.title}*",
            "attachments": [
                {
                    "color": color,
                    "text": event.message,
                    "fields": fields,
                    "footer": "Agentic Trader",
                    "ts": int(event.timestamp.timestamp())
                }
            ]
        }

    async def send(self, event: NotificationEvent) -> bool:
        """Send Slack notification via webhook.

        Args:
            event: The notification event to send

        Returns:
            True if message sent successfully, False otherwise
        """
        try:
            # Format message based on event type
            if isinstance(event, BacktestEvent):
                payload = self._format_backtest_message(event)
            elif isinstance(event, OrderEvent):
                payload = self._format_order_message(event)
            elif isinstance(event, AgentErrorEvent):
                payload = self._format_agent_error_message(event)
            else:
                payload = self._format_generic_message(event)

            # Send to Slack webhook
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logger.info("[notifications] Slack message sent successfully")
                        return True
                    else:
                        error_text = await response.text()
                        logger.warning(
                            f"[notifications] Slack webhook returned status {response.status}: {error_text}"
                        )
                        return False

        except Exception as exc:
            logger.error(
                f"[notifications] Slack send failed: {exc}",
                exc_info=True
            )
            return False


if __name__ == "__main__":
    """Functional test for Slack channel."""
    import asyncio
    from ..models import BacktestEvent, AgentErrorEvent

    async def test_slack_channel():
        """Test Slack formatting and configuration."""
        # Create channel (will be disabled without webhook URL)
        channel = SlackChannel(
            enabled=True,
            min_severity=NotificationSeverity.INFO
        )

        # Create test backtest event
        backtest_event = BacktestEvent(
            title="Test Backtest Completed",
            message="Test backtest for AAPL using mean_reversion",
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

        # Create test error event
        error_event = AgentErrorEvent(
            title="Test Agent Error",
            message="Test error in quant analyst",
            severity=NotificationSeverity.ERROR,
            agent_name="quant_analyst",
            thread_id="test_thread",
            node_name="test_node",
            error_type="ValueError",
            error_traceback="Traceback (most recent call last):\n  File test.py, line 1\n    test error",
            recoverable=True
        )

        # Test message formatting
        print("=== Backtest Event Slack Payload ===")
        import json
        print(json.dumps(channel._format_backtest_message(backtest_event), indent=2))

        print("\n=== Error Event Slack Payload ===")
        print(json.dumps(channel._format_agent_error_message(error_event), indent=2))

        print("\n✅ Slack channel structure validated")

    asyncio.run(test_slack_channel())
