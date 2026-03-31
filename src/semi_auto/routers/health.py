"""Health check router — GET /v1/health, GET /v1/health/detailed."""

from datetime import datetime, timezone

from fastapi import APIRouter

import src.semi_auto.app_state as _state
from src.common.utils import get_logger
from src.semi_auto.models.endpoints import DetailedHealthResponse, HealthResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health():
    """Basic liveness check."""
    return {
        "status": "ok",
        "graph_ready": _state._graph is not None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/detailed", response_model=DetailedHealthResponse)
async def health_detailed():
    """Per-component health check (graph, registry, portfolio DB)."""
    components: dict = {}

    components["graph"] = {"status": "ok" if _state._graph is not None else "not_ready"}

    try:
        from src.semi_auto.registry.functions import AVAILABLE_FUNCTIONS
        components["registry"] = {"status": "ok", "functions": len(AVAILABLE_FUNCTIONS)}
    except Exception as exc:
        components["registry"] = {"status": "error", "error": str(exc)}

    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        snap = dao.get_latest_snapshot()
        dao.close()
        components["portfolio_db"] = {"status": "ok", "latest_snapshot": snap is not None}
    except Exception as exc:
        components["portfolio_db"] = {"status": "error", "error": str(exc)}

    overall = "ok" if all(c.get("status") == "ok" for c in components.values()) else "degraded"
    return {
        "status": overall,
        "components": components,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
