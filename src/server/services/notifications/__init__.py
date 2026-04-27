"""Multi-channel notification system for critical trading events."""

from .notification_service import NotificationService, get_notification_service
from .models import (
    NotificationEvent,
    BacktestEvent,
    OrderEvent,
    AgentErrorEvent,
    PortfolioEvent,
    NotificationSeverity
)

__all__ = [
    "NotificationService",
    "get_notification_service",
    "NotificationEvent",
    "BacktestEvent",
    "OrderEvent",
    "AgentErrorEvent",
    "PortfolioEvent",
    "NotificationSeverity"
]
