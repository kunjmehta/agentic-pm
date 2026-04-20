"""Response models for configuration and root endpoints."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConfigResponse(BaseModel):
    """Response for GET /v1/config.

    Attributes:
        config: Full configuration dictionary.
        timestamp: ISO-8601 UTC timestamp.
    """

    config: Dict[str, Any]
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ConfigSectionResponse(BaseModel):
    """Response for GET /v1/config/{section}.

    Attributes:
        section: Section name requested.
        config: Configuration dict for the requested section.
        timestamp: ISO-8601 UTC timestamp.
    """

    section: str
    config: Dict[str, Any]
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class WatchlistEntryResponse(BaseModel):
    """Response for POST /v1/config/watchlist/add and DELETE /v1/config/watchlist/{symbol}.

    Attributes:
        status: "success" | "error".
        action: "added" | "removed".
        symbol: Ticker symbol.
        watchlist: Updated watchlist array.
        message: Human-readable confirmation.
        error: Error message on failure.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str
    action: Optional[str] = None
    symbol: Optional[str] = None
    watchlist: Optional[List[str]] = None
    message: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ConfigReloadResponse(BaseModel):
    """Response for POST /v1/config/reload.

    Attributes:
        status: "success" | "error".
        message: Human-readable confirmation.
        config: Reloaded configuration dict.
        error: Error message on failure.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str
    message: str
    config: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class RootResponse(BaseModel):
    """Response for GET /.

    Attributes:
        name: API name.
        version: Semver string.
        description: One-line description.
        port: Configured port.
        endpoints: Map of path → description.
    """

    name: str
    version: str
    description: str
    port: Any
    endpoints: Dict[str, str]
