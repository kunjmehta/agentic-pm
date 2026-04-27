"""Email notification channel using SendGrid.

This module implements email notifications via the SendGrid API. It supports
HTML templates with severity-based styling and handles configuration from
secret.json for API credentials.
"""

import logging
from typing import List, Optional
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


class EmailChannel(NotificationChannel):
    """Email notification channel using SendGrid API.

    Sends formatted HTML emails with severity-based color coding.
    Supports templating for different event types.

    Attributes:
        api_key: SendGrid API key
        from_email: Sender email address
        to_emails: List of recipient email addresses
    """

    def __init__(
        self,
        enabled: bool = True,
        min_severity: NotificationSeverity = NotificationSeverity.WARNING,
        api_key: Optional[str] = None,
        from_email: str = "trading@yourcompany.com",
        to_emails: Optional[List[str]] = None,
        **kwargs
    ):
        """Initialize email channel.

        Args:
            enabled: Whether channel is active
            min_severity: Minimum severity to send emails
            api_key: SendGrid API key (from secret.json or env)
            from_email: Sender email address
            to_emails: List of recipient email addresses
            **kwargs: Additional configuration
        """
        super().__init__(
            name="email",
            enabled=enabled,
            min_severity=min_severity,
            **kwargs
        )

        self.api_key = api_key or os.getenv("SENDGRID_API_KEY")
        self.from_email = from_email
        self.to_emails = to_emails or []

        # Validate configuration
        if enabled and not self.api_key:
            logger.warning(
                "[notifications] Email channel enabled but no API key provided. "
                "Set SENDGRID_API_KEY in secret.json or environment."
            )
            self.enabled = False

        if enabled and not self.to_emails:
            logger.warning(
                "[notifications] Email channel enabled but no recipients configured."
            )
            self.enabled = False

    def _get_severity_color(self, severity: NotificationSeverity) -> str:
        """Get HTML color code for severity level.

        Args:
            severity: Notification severity

        Returns:
            Hex color code
        """
        colors = {
            NotificationSeverity.INFO: "#2196F3",      # Blue
            NotificationSeverity.WARNING: "#FF9800",   # Orange
            NotificationSeverity.ERROR: "#F44336",     # Red
            NotificationSeverity.CRITICAL: "#9C27B0"   # Purple
        }
        return colors.get(severity, "#757575")  # Gray default

    def _format_backtest_email(self, event: BacktestEvent) -> str:
        """Format HTML email for backtest events.

        Args:
            event: Backtest event

        Returns:
            HTML email body
        """
        color = self._get_severity_color(event.severity)

        metrics_html = ""
        if event.status == "completed":
            metrics_html = f"""
            <table style="width: 100%; margin: 20px 0; border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;"><strong>Sharpe Ratio</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{event.sharpe_ratio:.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;"><strong>Total Return</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{event.total_return:.2f}%</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;"><strong>Max Drawdown</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{event.max_drawdown:.2f}%</td>
                </tr>
            </table>
            """
        elif event.error_message:
            metrics_html = f"""
            <div style="background-color: #ffebee; padding: 15px; border-radius: 4px; margin: 20px 0;">
                <strong>Error:</strong> {event.error_message}
            </div>
            """

        return f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: {color}; color: white; padding: 20px; border-radius: 4px 4px 0 0;">
                <h2 style="margin: 0;">{event.title}</h2>
            </div>
            <div style="background-color: #f5f5f5; padding: 20px; border-radius: 0 0 4px 4px;">
                <p>{event.message}</p>
                <table style="width: 100%; margin: 15px 0;">
                    <tr>
                        <td><strong>Backtest ID:</strong></td>
                        <td>{event.backtest_id}</td>
                    </tr>
                    <tr>
                        <td><strong>Strategy:</strong></td>
                        <td>{event.strategy}</td>
                    </tr>
                    <tr>
                        <td><strong>Symbol:</strong></td>
                        <td>{event.symbol}</td>
                    </tr>
                    <tr>
                        <td><strong>Timeframe:</strong></td>
                        <td>{event.timeframe}</td>
                    </tr>
                    <tr>
                        <td><strong>Status:</strong></td>
                        <td><strong>{event.status.upper()}</strong></td>
                    </tr>
                </table>
                {metrics_html}
                <p style="color: #757575; font-size: 12px; margin-top: 20px;">
                    Timestamp: {event.timestamp.isoformat()}
                </p>
            </div>
        </div>
        """

    def _format_generic_email(self, event: NotificationEvent) -> str:
        """Format generic HTML email for any event type.

        Args:
            event: Notification event

        Returns:
            HTML email body
        """
        color = self._get_severity_color(event.severity)

        metadata_html = ""
        if event.metadata:
            metadata_rows = "".join([
                f"<tr><td style='padding: 8px; border: 1px solid #ddd;'><strong>{k}</strong></td>"
                f"<td style='padding: 8px; border: 1px solid #ddd;'>{v}</td></tr>"
                for k, v in event.metadata.items()
            ])
            metadata_html = f"""
            <table style="width: 100%; margin: 20px 0; border-collapse: collapse;">
                {metadata_rows}
            </table>
            """

        return f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: {color}; color: white; padding: 20px; border-radius: 4px 4px 0 0;">
                <h2 style="margin: 0;">{event.title}</h2>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">
                    {event.severity.value} | {event.event_type.upper()}
                </p>
            </div>
            <div style="background-color: #f5f5f5; padding: 20px; border-radius: 0 0 4px 4px;">
                <p style="font-size: 16px; line-height: 1.5;">{event.message}</p>
                {metadata_html}
                <p style="color: #757575; font-size: 12px; margin-top: 20px;">
                    Timestamp: {event.timestamp.isoformat()}
                </p>
            </div>
        </div>
        """

    async def send(self, event: NotificationEvent) -> bool:
        """Send email notification via SendGrid.

        Args:
            event: The notification event to send

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            # Format email based on event type
            if isinstance(event, BacktestEvent):
                html_content = self._format_backtest_email(event)
            else:
                html_content = self._format_generic_email(event)

            # Import SendGrid here to avoid import errors if not installed
            try:
                from sendgrid import SendGridAPIClient
                from sendgrid.helpers.mail import Mail, Email, To, Content
            except ImportError:
                logger.error(
                    "[notifications] SendGrid not installed. "
                    "Run: pip install sendgrid>=6.11.0"
                )
                return False

            # Create email message
            message = Mail(
                from_email=Email(self.from_email),
                to_emails=[To(email) for email in self.to_emails],
                subject=f"[{event.severity.value}] {event.title}",
                html_content=Content("text/html", html_content)
            )

            # Send via SendGrid API
            sg = SendGridAPIClient(api_key=self.api_key)
            response = sg.send(message)

            if response.status_code in (200, 201, 202):
                logger.info(
                    f"[notifications] Email sent successfully to {len(self.to_emails)} recipients"
                )
                return True
            else:
                logger.warning(
                    f"[notifications] SendGrid returned status {response.status_code}"
                )
                return False

        except Exception as exc:
            logger.error(
                f"[notifications] Email send failed: {exc}",
                exc_info=True
            )
            return False


if __name__ == "__main__":
    """Functional test for email channel."""
    import asyncio
    from ..models import BacktestEvent

    async def test_email_channel():
        """Test email formatting and configuration."""
        # Create channel (will be disabled without API key)
        channel = EmailChannel(
            enabled=True,
            min_severity=NotificationSeverity.INFO,
            from_email="test@example.com",
            to_emails=["recipient@example.com"]
        )

        # Create test event
        event = BacktestEvent(
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

        # Test HTML formatting
        html = channel._format_backtest_email(event)
        print("=== Generated HTML Email ===")
        print(html)

        # Test send (will fail without API key, but validates flow)
        print("\n=== Testing Send (expected to fail without API key) ===")
        result = await channel.notify(event)
        print(f"Send result: {result}")

        print("\n✅ Email channel structure validated")

    asyncio.run(test_email_channel())
