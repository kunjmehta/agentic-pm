"""Admin router — POST /v1/admin/cleanup, GET /v1/admin/stats."""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from src.common.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.post("/cleanup")
async def admin_cleanup(dry_run: bool = Query(default=True)):
    """Delete expired threads from portfolio DB.

    Args:
        dry_run: If True, only count; don't delete.

    Returns:
        Cleanup result dict.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        result = dao.cleanup_expired_threads(dry_run=dry_run)
        dao.close()
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stats")
async def admin_stats():
    """Return basic database statistics.

    Returns:
        Dict with row counts per table.
    """
    stats: Dict[str, Any] = {}
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        stats["portfolio_db"] = {
            "interactions": len(dao.get_interaction_history("", "semi_auto_pm", 9999)),
        }
        snap = dao.get_latest_snapshot()
        stats["portfolio_db"]["latest_snapshot"] = snap.get("date_only") if snap else None
        dao.close()
    except Exception as exc:
        stats["portfolio_db"] = {"error": str(exc)}

    return {"stats": stats, "timestamp": datetime.now(timezone.utc).isoformat()}
