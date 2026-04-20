"""Response models for admin endpoints."""

from typing import Any, Dict, Optional

from pydantic import BaseModel


class CleanupResponse(BaseModel):
    """Response for POST /v1/admin/cleanup.

    Attributes:
        status: ``"success"`` or ``"error"``.
        deleted_count: Number of expired threads removed.
        dry_run: Whether this was a dry run (no actual deletion).
        detail: Optional error or informational message.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str
    deleted_count: int = 0
    dry_run: bool = True
    detail: Optional[str] = None
    timestamp: str


class AdminStatsResponse(BaseModel):
    """Response for GET /v1/admin/stats.

    Attributes:
        interactions: Total stored interaction count.
        turn_count: Total agent turn count.
        latest_snapshot: Most recent portfolio snapshot dict, or ``None``.
        timestamp: ISO-8601 UTC timestamp.
    """

    interactions: int = 0
    turn_count: int = 0
    latest_snapshot: Optional[Dict[str, Any]] = None
    timestamp: str
