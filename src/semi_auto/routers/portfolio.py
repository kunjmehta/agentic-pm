"""Portfolio router — GET /v1/portfolio/status|health|history, WS /v1/portfolio/ws."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from src.common.utils import get_logger
from src.semi_auto.models.endpoints import PortfolioHealthResponse, PortfolioHistoryResponse
from src.semi_auto.ws_manager import ws_manager

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/portfolio", tags=["portfolio"])


@router.get("/status")
async def portfolio_status():
    """Direct portfolio status without agent reasoning.

    Returns:
        Portfolio status dict from Alpaca.
    """
    try:
        from src.agentic.agents.portfolio.skills.portfoliostatus.status import get_portfolio_status_core
        return get_portfolio_status_core()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health", response_model=PortfolioHealthResponse)
async def portfolio_health():
    """Risk compliance check against portfolio risk parameters.

    Calls ``check_portfolio_health`` via the FUNCTION_REGISTRY wrapper which
    auto-injects portfolio_status and positions_data.

    Returns:
        Health status with violations, warnings, and checks performed.
    """
    try:
        from src.semi_auto.registry.functions import AVAILABLE_FUNCTIONS
        health_fn = AVAILABLE_FUNCTIONS.get("check_portfolio_health")
        if health_fn is None:
            raise HTTPException(status_code=503, detail="check_portfolio_health not available")
        result = health_fn()
        return {
            "status": "success",
            "health": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[portfolio/health] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history", response_model=PortfolioHistoryResponse)
async def portfolio_history(
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
):
    """Historical portfolio snapshots.

    Args:
        start: Optional start date filter (YYYY-MM-DD).
        end: Optional end date filter (YYYY-MM-DD).

    Returns:
        List of portfolio snapshots with count.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        history = dao.get_snapshot_history(start_date=start, end_date=end)
        dao.close()
        return {
            "status": "success",
            "snapshots": history,
            "count": len(history),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[portfolio/history] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# Valid timeframe options per period to avoid Alpaca 422 errors.
_PERIOD_TIMEFRAME_MAP: dict = {
    "1D": {"1Min", "5Min", "15Min", "1H"},
    "1W": {"1Min", "5Min", "15Min", "1H", "1D"},
    "1M": {"1H", "1D"},
    "3M": {"1D"},
    "1A": {"1D"},
    "all": {"1D"},
}


@router.get("/history/alpaca")
async def portfolio_history_alpaca(
    period: str = Query(default="1M", description="Time period: 1D, 1W, 1M, 3M, 1A, all"),
    timeframe: str = Query(default="1D", description="Bar resolution: 1Min, 5Min, 15Min, 1H, 1D"),
    extended_hours: bool = Query(default=False, description="Include pre/post market data"),
):
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
        400: If the period+timeframe combination is invalid.
        500: If the Alpaca API request fails.
    """
    valid_timeframes = _PERIOD_TIMEFRAME_MAP.get(period.upper())
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
    try:
        from src.common.external.alpaca_portfolio import fetch_portfolio_history
        data = fetch_portfolio_history(
            period=period.upper(),
            timeframe=timeframe,
            extended_hours=extended_hours,
        )
        return {
            "status": "success",
            "period": period,
            **data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[portfolio/history/alpaca] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── WebSocket endpoint ─────────────────────────────────────────────────────
@router.websocket("/ws")
async def portfolio_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time portfolio updates (DISABLED).

    Clients can subscribe to receive portfolio updates every 3 seconds.
    Updates include account equity, cash, buying power, P&L, and positions.

    Client Messages:
        {"type": "subscribe"}    - Start receiving portfolio updates
        {"type": "unsubscribe"}  - Stop receiving updates
        {"type": "refresh"}      - Request immediate portfolio update

    Server Messages:
        {"type": "connection", "message": "Connected to portfolio stream"}
        {"type": "portfolio_update", "data": {...}}
        {"type": "error", "message": "..."}

    Portfolio Update Data Structure:
        {
            "type": "portfolio_update",
            "data": {
                "equity": float,              # Total account value
                "cash": float,                # Available cash
                "buying_power": float,        # Margin buying power
                "unrealized_pl": float,       # Total unrealized P&L
                "realized_pl": float,         # Total realized P&L today
                "positions": [
                    {
                        "symbol": str,
                        "qty": float,
                        "market_value": float,
                        "unrealized_pl": float,
                        "avg_entry_price": float,
                        "current_price": float,
                        "side": "long" | "short"
                    },
                    ...
                ],
                "timestamp": "ISO-8601"
            }
        }

    Connection Lifecycle:
        1. Client connects
        2. Server sends connection confirmation
        3. Client sends {"type": "subscribe"}
        4. Server begins sending portfolio_update every 3s
        5. Client can send {"type": "refresh"} for immediate update
        6. Client sends {"type": "unsubscribe"} to pause updates
        7. Client disconnects or connection error

    Example:
        # JavaScript client
        const ws = new WebSocket('ws://localhost:8000/v1/portfolio/ws');
        ws.onopen = () => {
            ws.send(JSON.stringify({type: 'subscribe'}));
        };
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'portfolio_update') {
                console.log('Portfolio:', data.data);
            }
        };
    """
    await ws_manager.connect(websocket)

    # Send connection confirmation
    await websocket.send_json({
        "type": "connection",
        "message": "Connected to portfolio stream",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # State tracking
    subscribed = False
    update_task: Optional[asyncio.Task] = None

    async def send_portfolio_update():
        """Fetch and send current portfolio data to the client."""
        try:
            # Fetch account info
            from src.common.external.alpaca_portfolio import (
                fetch_account_info,
                fetch_positions,
            )

            account = fetch_account_info()
            positions = fetch_positions()

            # Calculate totals
            total_unrealized_pl = sum(
                float(p.get("unrealized_pl", 0)) for p in positions
            )

            # Format positions for client
            formatted_positions = [
                {
                    "symbol": p["symbol"],
                    "qty": p["qty"],
                    "market_value": p["market_value"],
                    "unrealized_pl": p["unrealized_pl"],
                    "avg_entry_price": p["avg_entry_price"],
                    "current_price": p["current_price"],
                    "side": p["side"],
                }
                for p in positions
            ]

            # Send update
            await websocket.send_json({
                "type": "portfolio_update",
                "data": {
                    "equity": account["equity"],
                    "cash": account["cash"],
                    "buying_power": account["buying_power"],
                    "unrealized_pl": total_unrealized_pl,
                    "realized_pl": 0.0,  # Would need to calculate from daily trades
                    "positions": formatted_positions,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })

            logger.debug(
                f"[ws/portfolio] sent update: equity=${account['equity']:.2f}, "
                f"positions={len(positions)}"
            )

        except Exception as exc:
            logger.error(f"[ws/portfolio] error fetching portfolio data: {exc}", exc_info=True)
            await websocket.send_json({
                "type": "error",
                "message": f"Failed to fetch portfolio data: {str(exc)}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    async def periodic_update_loop():
        """Background task - DISABLED automatic polling to reduce API calls.

        Portfolio updates now only sent when client explicitly requests via 'refresh' message.
        """
        # Automatic polling disabled - client must explicitly request updates
        while subscribed:
            try:
                await asyncio.sleep(60.0)  # Keep task alive but don't poll
            except asyncio.CancelledError:
                break

    try:
        while True:
            # Wait for client messages
            message = await websocket.receive_json()
            msg_type = message.get("type", "")

            logger.debug(f"[ws/portfolio] received message: {msg_type}")

            if msg_type == "subscribe":
                if not subscribed:
                    subscribed = True
                    # Start periodic update task
                    update_task = asyncio.create_task(periodic_update_loop())
                    logger.info("[ws/portfolio] client subscribed (manual refresh only)")
                    await websocket.send_json({
                        "type": "subscribed",
                        "message": "Connected. Send 'refresh' message to get portfolio updates.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

            elif msg_type == "unsubscribe":
                if subscribed:
                    subscribed = False
                    if update_task:
                        update_task.cancel()
                        update_task = None
                    logger.info("[ws/portfolio] client unsubscribed from updates")
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "message": "Portfolio updates stopped",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

            elif msg_type == "refresh":
                # Immediate portfolio update regardless of subscription
                await send_portfolio_update()
                logger.debug("[ws/portfolio] manual refresh requested")

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
        # Cleanup
        if update_task:
            update_task.cancel()
        await ws_manager.disconnect(websocket)
        logger.info("[ws/portfolio] connection cleaned up")
