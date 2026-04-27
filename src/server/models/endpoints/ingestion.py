"""Response models for data ingestion endpoints."""

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DataStreamInfo(BaseModel):
    """Sub-section of :class:`IngestionStatusResponse`."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    running: bool = False
    symbols: List[str] = Field(default_factory=list)
    task_name: Optional[str] = None


class IngestionStatusResponse(BaseModel):
    """Response for GET /v1/ingestion/status."""

    data_stream: Any
    cache: Any
    etl: Any
    timestamp: str


class TriggerETLResponse(BaseModel):
    """Response for POST /v1/ingestion/trigger-etl.

    Attributes:
        status: ``"success"`` or ``"error"``.
        message: Human-readable summary.
        total_rows: Indicator rows written, or ``None`` on error.
        symbols: Symbols processed, or ``None`` on error.
        timestamp: ISO-8601 UTC timestamp.
        error: Error detail when ``status == "error"``.
    """

    status: str
    message: str
    total_rows: Optional[int] = None
    symbols: Optional[List[str]] = None
    timestamp: str
    error: Optional[str] = None


class FlushCacheResponse(BaseModel):
    """Response for POST /v1/ingestion/flush-cache.

    Attributes:
        status: ``"success"`` or ``"error"``.
        trades_flushed: Rows written to ``live_trades`` from cache.
        trades_archived: Rows moved to ``historical_trades``.
        message: Human-readable summary.
        timestamp: ISO-8601 UTC timestamp.
        archive_warning: Non-fatal warning if archive step failed.
        error: Present only when ``status == "error"``.
    """

    status: str
    trades_flushed: int = 0
    trades_archived: int = 0
    message: Optional[str] = None
    timestamp: str
    archive_warning: Optional[str] = None
    error: Optional[str] = None
