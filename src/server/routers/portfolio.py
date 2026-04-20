"""Portfolio router — GET /v1/portfolio/status|health|history, WS /v1/portfolio/ws."""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from src.common.utils import get_logger
from src.server.models.endpoints import PortfolioHealthResponse, PortfolioHistoryResponse
from src.server.routers._helpers import dao_context, handle_http_errors, run_in_thread
from src.server.ws_manager import ws_manager

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/portfolio", tags=["portfolio"])


@router.get("/status")
@handle_http_errors
async def portfolio_status() -> Dict[str, Any]:
    """Direct portfolio status without agent reasoning.

    Returns:
        Portfolio status dict from Alpaca.
    """
    from src.agentic.agents.portfolio.skills.portfoliostatus.status import get_portfolio_status_core

    return await run_in_thread(get_portfolio_status_core)


@router.get("/health", response_model=PortfolioHealthResponse)
@handle_http_errors
async def portfolio_health() -> Dict[str, Any]:
    """Risk compliance check against portfolio risk parameters.

    Calls ``check_portfolio_health`` via the FUNCTION_REGISTRY wrapper which
    auto-injects portfolio_status and positions_data.

    Returns:
        Health status with violations, warnings, and checks performed.
    """
    from src.server.helpers import get_function_registry

    health_fn = get_function_registry().get("check_portfolio_health")
    if health_fn is None:
        raise HTTPException(status_code=503, detail="check_portfolio_health not available")
    result = await run_in_thread(health_fn)
    return {
        "status": "success",
        "health": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/history", response_model=PortfolioHistoryResponse)
@handle_http_errors
async def portfolio_history(
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
) -> Dict[str, Any]:
    """Historical portfolio snapshots.

    Args:
        start: Optional start date filter (YYYY-MM-DD).
        end: Optional end date filter (YYYY-MM-DD).

    Returns:
        List of portfolio snapshots with count.
    """
    from src.common.dao.portfolio_dao import PortfolioDAO

    def _fetch():
        with dao_context(PortfolioDAO) as dao:
            return dao.get_snapshot_history(start_date=start, end_date=end)

    history = await run_in_thread(_fetch)
    return {
        "status": "success",
        "snapshots": history,
        "count": len(history),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Valid timeframe options per period to avoid Alpaca 422 errors.
_PERIOD_TIMEFRAME_MAP: Dict[str, set] = {
    "1D": {"1Min", "5Min", "15Min", "1H"},
    "1W": {"1Min", "5Min", "15Min", "1H", "1D"},
    "1M": {"1H", "1D"},
    "3M": {"1D"},
    "1A": {"1D"},
    "ALL": {"1D"},
}


@router.get("/history/alpaca")
@handle_http_errors
async def portfolio_history_alpaca(
    period: str = Query(default="1M", description="Time period: 1D, 1W, 1M, 3M, 1A, all"),
    timeframe: str = Query(default="1D", description="Bar resolution: 1Min, 5Min, 15Min, 1H, 1D"),
    extended_hours: bool = Query(default=False, description="Include pre/post market data"),
) -> Dict[str, Any]:
    """Live portfolio performance history directly from Alpaca.

    Returns equity curve and P&L series from Alpaca's portfolio history API,
    as opposed to ``/history`` which returns locally-stored snapshots.

    Args:
        period: Lookback window. One of ``1D``, ``1W``, ``1M``, ``3M``,
            ``1A``, ``all``. Default ``1M``.
        timeframe: Bar aggregation. Allowed values depend on ``period``
            (e.g. ``1D`` period only supports intraday resolutions).
            Default ``1D``.
        extended_hours: Include extended-hours data. Default False.

    Returns:
        Dict with timestamp list, equity list, profit_loss list,
        profit_loss_pct list, base_value, and timeframe.

    Raises:
        HTTPException 400: If the period+timeframe combination is invalid.
    """
    from src.common.external.alpaca_portfolio import fetch_portfolio_history

    period_upper = period.upper()
    valid_timeframes = _PERIOD_TIMEFRAME_MAP.get(period_upper)
    if valid_timeframes is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {', '.join(_PERIOD_TIMEFRAME_MAP)}",
        )
    if timeframe not in valid_timeframes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Timeframe '{timeframe}' is not valid for period '{period}'. "
                f"Allowed: {', '.join(sorted(valid_timeframes))}"
            ),
        )

    data = await run_in_thread(
        fetch_portfolio_history,
        period=period_upper,
        timeframe=timeframe,
        extended_hours=extended_hours,
    )
    return {
        "status": "success",
        "period": period,
        **data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── WebSocket endpoint ─────────────────────────────────────────────────────────


@router.websocket("/ws")
async def portfolio_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time portfolio updates.

    Clients subscribe and send ``refresh`` messages to pull portfolio data.

    Client Messages:
        {"type": "subscribe"}    - Acknowledge subscription
        {"type": "unsubscribe"}  - Stop receiving updates
        {"type": "refresh"}      - Request immediate portfolio update

    Server Messages:
        {"type": "connection", "message": "Connected to portfolio stream"}
        {"type": "portfolio_update", "data": {...}}
        {"type": "error", "message": "..."}
    """
    await ws_manager.connect(websocket)

    await websocket.send_json({
        "type": "connection",
        "message": "Connected to portfolio stream",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    subscribed = False

    async def _send_portfolio_update() -> None:
        """Fetch and push current portfolio data to the connected client."""
        try:
            from src.server.services.portfolio_service import get_portfolio_snapshot

            snap = await get_portfolio_snapshot()
            await websocket.send_json({
                "type": "portfolio_update",
                "data": {
                    "equity": snap.equity,
                    "cash": snap.cash,
                    "buying_power": snap.buying_power,
                    "unrealized_pl": snap.unrealized_pl,
                    "realized_pl": 0.0,
                    "positions": snap.positions,
                    "timestamp": snap.timestamp,
                },
            })
        except Exception as exc:
            logger.error(f"[ws/portfolio] error fetching portfolio data: {exc}", exc_info=True)
            await websocket.send_json({
                "type": "error",
                "message": f"Failed to fetch portfolio data: {str(exc)}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type", "")

            if msg_type == "subscribe":
                subscribed = True
                await websocket.send_json({
                    "type": "subscribed",
                    "message": "Connected. Send 'refresh' message to get portfolio updates.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            elif msg_type == "unsubscribe":
                subscribed = False
                await websocket.send_json({
                    "type": "unsubscribed",
                    "message": "Portfolio updates stopped",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            elif msg_type == "refresh":
                await _send_portfolio_update()

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

    except WebSocketDisconnect:
        logger.info("[ws/portfolio] client disconnected normally")

    except Exception as exc:
        logger.error(f"[ws/portfolio] connection error: {exc}", exc_info=True)

    finally:
        await ws_manager.disconnect(websocket)


if __name__ == "__main__":
    """Smoke test: verify router routes are defined correctly."""
    print("=" * 60)
    print("routers/portfolio.py smoke test")
    print("=" * 60)

    routes = [r.path for r in router.routes]
    expected = ["/v1/portfolio/status", "/v1/portfolio/health", "/v1/portfolio/history"]
    for path in expected:
        assert path in routes, f"Missing route: {path}"
        print(f"  [OK]  {path}")

    print("\n[ALL OK] routers/portfolio.py smoke test passed")
    print("=" * 60)
