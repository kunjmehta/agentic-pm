"""Response models for health check endpoints."""

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict


class ComponentStatus(BaseModel):
    """Status dict for one health-check component."""

    model_config = ConfigDict(extra="allow")

    status: str


class HealthResponse(BaseModel):
    """Response for GET /v1/health (liveness).

    Attributes:
        status: Always ``"ok"`` when the server is reachable.
        graph_ready: Whether the LangGraph compiled graph is initialised.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str
    graph_ready: bool
    timestamp: str


class DetailedHealthResponse(BaseModel):
    """Response for GET /v1/health/detailed (per-component).

    Attributes:
        status: ``"ok"`` when all components report OK, else ``"degraded"``.
        components: Map of component name → :class:`ComponentStatus`.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str
    components: Dict[str, Any]
    timestamp: str
