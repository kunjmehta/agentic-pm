"""Order execution router — POST/DELETE /v1/orders/...

Provides direct REST access to all order-execution skill functions outside
the agent reasoning flow.  These endpoints are intentionally thin wrappers
around the registry functions so they remain consistent with what the graph
executor calls.

Endpoints:
    GET  /v1/orders                       List open orders from Alpaca
    POST /v1/orders/execute               Place a market or limit order
    POST /v1/orders/stop                  Place a stop (stop-market) order
    POST /v1/orders/stop-limit            Place a stop-limit order
    POST /v1/orders/close/{symbol}        Liquidate a full position
    POST /v1/orders/scale                 Resize to a target portfolio %
    POST /v1/orders/signal                Execute a strategy buy/sell/hold signal
    DELETE /v1/orders/{order_id}          Cancel a specific order
    DELETE /v1/orders                     Cancel all open orders

All write endpoints (/execute, /stop, /stop-limit, /close, /scale, /signal,
DELETE) go through the same audit trail as the agent — LOG entries are written
but no LangGraph checkpoint is created.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.common.external.alpaca_portfolio import (
    cancel_all_orders as _cancel_all_orders,
    cancel_order as _alpaca_cancel_order,
    fetch_orders,
)
from src.common.utils import get_logger
from src.server.helpers import get_function_registry
from src.server.models.endpoints import (
    OpenOrdersResponse,
    OrderCancelResponse,
    OrderResponse,
    ScalePositionResponse,
    StrategySignalExecutionResponse,
)
from src.server.routers._helpers import handle_http_errors, run_in_thread
from src.server.ws_manager import ws_manager

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/orders", tags=["orders"])


# ── Request bodies ─────────────────────────────────────────────────────────────


class ExecuteOrderRequest(BaseModel):
    """POST /v1/orders/execute request body.

    Attributes:
        symbol: Stock ticker (e.g. "AAPL").
        qty: Number of shares.  Must be > 0.
        side: "buy" or "sell".
        order_type: "market" (default) or "limit".
        limit_price: Required when order_type is "limit".
    """

    symbol: str
    qty: float = Field(..., gt=0, description="Number of shares (must be > 0)")
    side: str = Field(..., pattern="^(buy|sell)$", description="'buy' or 'sell'")
    order_type: str = Field(default="market", pattern="^(market|limit)$")
    limit_price: Optional[float] = Field(default=None, gt=0)


class ScalePositionRequest(BaseModel):
    """POST /v1/orders/scale request body.

    Attributes:
        symbol: Stock ticker.
        target_pct: Target allocation fraction of equity (e.g. 0.05 = 5%).
            Use 0.0 to close the position.
        order_type: "market" (default) or "limit".
        limit_price: Required for limit orders.
    """

    symbol: str
    target_pct: float = Field(..., ge=0.0, le=1.0, description="Target fraction of equity")
    order_type: str = Field(default="market", pattern="^(market|limit)$")
    limit_price: Optional[float] = Field(default=None, gt=0)


class StopOrderRequest(BaseModel):
    """POST /v1/orders/stop request body.

    Attributes:
        symbol: Stock ticker (e.g. "AAPL").
        qty: Number of shares.  Must be > 0.
        side: "buy" or "sell".
        stop_price: Trigger price.  Must be > 0.
        time_in_force: "day" | "gtc" | "ioc" | "fok".  Default "day".
    """

    symbol: str
    qty: float = Field(..., gt=0, description="Number of shares (must be > 0)")
    side: str = Field(..., pattern="^(buy|sell)$", description="'buy' or 'sell'")
    stop_price: float = Field(..., gt=0, description="Trigger price (must be > 0)")
    time_in_force: str = Field(default="day", pattern="^(day|gtc|ioc|fok)$")


class StopLimitOrderRequest(BaseModel):
    """POST /v1/orders/stop-limit request body.

    Attributes:
        symbol: Stock ticker (e.g. "AAPL").
        qty: Number of shares.  Must be > 0.
        side: "buy" or "sell".
        stop_price: Trigger price that activates the limit order.  Must be > 0.
        limit_price: Execution price cap (buy) or floor (sell).  Must be > 0.
        time_in_force: "day" | "gtc" | "ioc" | "fok".  Default "day".
    """

    symbol: str
    qty: float = Field(..., gt=0, description="Number of shares (must be > 0)")
    side: str = Field(..., pattern="^(buy|sell)$", description="'buy' or 'sell'")
    stop_price: float = Field(..., gt=0, description="Stop trigger price (must be > 0)")
    limit_price: float = Field(..., gt=0, description="Limit execution price (must be > 0)")
    time_in_force: str = Field(default="day", pattern="^(day|gtc|ioc|fok)$")


class StrategySignalRequest(BaseModel):
    """POST /v1/orders/signal request body.

    Attributes:
        symbol: Stock ticker.
        signal: "buy" | "sell" | "hold".
        confidence: Conviction score 0–1.  Scales the position size.
        base_position_pct: Max single-position size as fraction of equity.
        order_type: "market" (default) or "limit".
    """

    symbol: str
    signal: str = Field(..., pattern="^(buy|sell|hold)$")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    base_position_pct: float = Field(default=0.05, gt=0.0, le=1.0)
    order_type: str = Field(default="market", pattern="^(market|limit)$")


# ── Helpers ─────────────────────────────────────────────────────────────────────


async def _call_registry(name: str, **kwargs: Any) -> Dict[str, Any]:
    """Resolve, call (in thread), and error-check a registry function.

    Consolidates the repeated pattern across all order endpoints:
    look up the function, run it without blocking the event loop, and
    raise HTTP 500 if the result carries ``status="error"``.

    Args:
        name: Registry function name.
        **kwargs: Keyword arguments forwarded to the function.

    Returns:
        Result dict from the registry function.

    Raises:
        HTTPException: 503 if the function is not registered;
            500 if the function returns ``status="error"``.
    """
    fn = get_function_registry().get(name)
    if fn is None:
        raise HTTPException(status_code=503, detail=f"Function '{name}' not available")
    result: Dict[str, Any] = await run_in_thread(fn, **kwargs)
    if result.get("status") == "error":
        raise HTTPException(
            status_code=500,
            detail=result.get("error", f"'{name}' returned an error"),
        )
    return result


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.websocket("/ws")
async def orders_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time order updates.

    Broadcasts order updates when orders are:
    - Submitted (new order placed)
    - Filled (order executed)
    - Cancelled (order cancelled)
    - Rejected (order rejected by broker)

    Message types sent to clients:
    - connection: Initial connection confirmation
    - order_update: Real-time order status changes
    - error: Error messages

    Args:
        websocket: FastAPI WebSocket connection

    Example order_update message:
        {
            "type": "order_update",
            "order_id": "uuid-123",
            "broker_order_id": "alpaca-456",
            "symbol": "AAPL",
            "side": "buy",
            "qty": 10,
            "status": "submitted",
            "timestamp": "2024-01-15T10:30:45.123456"
        }

    Example filled message:
        {
            "type": "order_update",
            "order_id": "uuid-123",
            "status": "filled",
            "filled_price": 150.25,
            "filled_at": "2024-01-15T10:31:12.456789"
        }
    """
    await ws_manager.connect(websocket)

    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "connection",
            "message": "Connected to orders stream",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        logger.info("[orders] Client connected to orders stream")

        # Keep connection alive
        # (messages are sent via ws_manager.broadcast() from order execution handlers)
        while True:
            # Wait for client messages (ping, etc.)
            data = await websocket.receive_text()
            logger.debug(f"[orders] Received client message: {data}")

    except WebSocketDisconnect:
        logger.info("[orders] Client disconnected from orders stream")
        await ws_manager.disconnect(websocket)
    except Exception as exc:
        logger.error(f"[orders] WebSocket error: {exc}", exc_info=True)
        await ws_manager.disconnect(websocket)


@router.get("", response_model=OpenOrdersResponse)
@handle_http_errors
async def list_open_orders() -> Dict[str, Any]:
    """List all currently open orders from Alpaca.

    Returns:
        OpenOrdersResponse with orders list and count.
    """
    orders = await run_in_thread(fetch_orders, status="open")
    return {
        "status": "success",
        "orders": orders,
        "count": len(orders),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/execute", response_model=OrderResponse)
@handle_http_errors
async def execute_order(request: ExecuteOrderRequest) -> Dict[str, Any]:
    """Place a market or limit order.

    Args:
        request: ExecuteOrderRequest body with symbol, qty, side, order_type,
            and optional limit_price.

    Returns:
        OrderResponse with order details from Alpaca.
    """
    logger.info(
        f"[orders/execute] {request.side.upper()} {request.qty} {request.symbol} "
        f"type={request.order_type}"
    )
    result = await _call_registry(
        "execute_order",
        symbol=request.symbol,
        qty=request.qty,
        side=request.side,
        order_type=request.order_type,
        limit_price=request.limit_price,
    )
    await ws_manager.broadcast({
        "type": "order_update",
        "order_id": result.get("id"),
        "broker_order_id": result.get("id"),
        "symbol": request.symbol,
        "side": request.side,
        "qty": request.qty,
        "status": "submitted",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "status": "success",
        "order": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/stop", response_model=OrderResponse)
@handle_http_errors
async def place_stop_order(request: StopOrderRequest) -> Dict[str, Any]:
    """Place a stop (stop-market) order via Alpaca.

    A stop order becomes a market order when the market price reaches
    ``stop_price``.  Commonly used as a stop-loss on an existing position
    or a breakout entry trigger.

    Args:
        request: StopOrderRequest with symbol, qty, side, stop_price,
            and optional time_in_force.

    Returns:
        OrderResponse with the submitted order details.
    """
    logger.info(
        f"[orders/stop] {request.side.upper()} {request.qty} {request.symbol} "
        f"stop@{request.stop_price}"
    )
    result = await _call_registry(
        "place_stop_order",
        symbol=request.symbol,
        qty=request.qty,
        side=request.side,
        stop_price=request.stop_price,
        time_in_force=request.time_in_force,
    )
    return {"status": "success", "order": result, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/stop-limit", response_model=OrderResponse)
@handle_http_errors
async def place_stop_limit_order(request: StopLimitOrderRequest) -> Dict[str, Any]:
    """Place a stop-limit order via Alpaca.

    When the market price reaches ``stop_price`` a limit order at
    ``limit_price`` is submitted.  Provides both trigger control and
    execution price control — ideal for risk-managed entries/exits.

    Args:
        request: StopLimitOrderRequest with symbol, qty, side, stop_price,
            limit_price, and optional time_in_force.

    Returns:
        OrderResponse with the submitted order details.
    """
    logger.info(
        f"[orders/stop-limit] {request.side.upper()} {request.qty} {request.symbol} "
        f"stop@{request.stop_price} limit@{request.limit_price}"
    )
    result = await _call_registry(
        "place_stop_limit_order",
        symbol=request.symbol,
        qty=request.qty,
        side=request.side,
        stop_price=request.stop_price,
        limit_price=request.limit_price,
        time_in_force=request.time_in_force,
    )
    return {"status": "success", "order": result, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/close/{symbol}", response_model=OrderResponse)
@handle_http_errors
async def close_position(symbol: str) -> Dict[str, Any]:
    """Liquidate the full open position for a symbol at market price.

    Args:
        symbol: Stock ticker whose position to close.

    Returns:
        OrderResponse with the closing order details.
    """
    logger.info(f"[orders/close] closing position for {symbol.upper()}")
    result = await _call_registry("close_position", symbol=symbol)
    return {"status": "success", "order": result, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/scale", response_model=ScalePositionResponse)
@handle_http_errors
async def scale_position(request: ScalePositionRequest) -> Dict[str, Any]:
    """Resize a position to a target percentage of total equity.

    Computes the buy/sell delta required and places the appropriate order.
    A target_pct of 0.0 will close the position entirely.

    Args:
        request: ScalePositionRequest body.

    Returns:
        ScalePositionResponse with action, delta, and order details.
    """
    logger.info(
        f"[orders/scale] {request.symbol} → {request.target_pct:.1%} "
        f"type={request.order_type}"
    )
    result = await _call_registry(
        "scale_position",
        symbol=request.symbol,
        target_pct=request.target_pct,
        order_type=request.order_type,
        limit_price=request.limit_price,
    )
    return {
        "status": "success",
        **{k: v for k, v in result.items() if k != "timestamp"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/signal", response_model=StrategySignalExecutionResponse)
@handle_http_errors
async def execute_strategy_signal(request: StrategySignalRequest) -> Dict[str, Any]:
    """Translate a strategy signal into a live Alpaca order.

    Confidence scales the position size: a buy with confidence=0.5 and
    base_position_pct=0.05 targets 2.5% of equity.

    Args:
        request: StrategySignalRequest body.

    Returns:
        StrategySignalExecutionResponse with action and order details.
    """
    logger.info(
        f"[orders/signal] {request.symbol} signal={request.signal} "
        f"confidence={request.confidence:.2f}"
    )
    result = await _call_registry(
        "execute_strategy_signal",
        symbol=request.symbol,
        signal=request.signal,
        confidence=request.confidence,
        base_position_pct=request.base_position_pct,
        order_type=request.order_type,
    )
    return {
        "status": "success",
        **{k: v for k, v in result.items() if k != "timestamp"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.delete("/{order_id}", response_model=OrderCancelResponse)
@handle_http_errors
async def cancel_order(order_id: str) -> Dict[str, Any]:
    """Cancel an open order by its Alpaca UUID.

    Args:
        order_id: Alpaca order UUID string.

    Returns:
        OrderCancelResponse confirming cancellation.
    """
    logger.info(f"[orders/cancel] order_id={order_id}")
    await run_in_thread(_alpaca_cancel_order, order_id=order_id)
    return {
        "status": "success",
        "order_id": order_id,
        "message": f"Order {order_id} cancelled",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.delete("", response_model=OrderCancelResponse)
@handle_http_errors
async def cancel_all_orders() -> Dict[str, Any]:
    """Cancel all open orders.

    Returns:
        OrderCancelResponse with count of cancelled orders.
    """
    logger.info("[orders/cancel_all] cancelling all open orders")
    result = await run_in_thread(_cancel_all_orders)
    count = result.get("cancelled_count", 0) if isinstance(result, dict) else 0
    return {
        "status": "success",
        "message": f"Cancelled {count} open orders",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/reconcile")
@handle_http_errors
async def reconcile_orders() -> Dict[str, Any]:
    """Reconcile submitted orders against Alpaca fill data.

    Fetches all ``live_orders`` with ``status='submitted'``, queries Alpaca
    for their current state, and updates ``filled_at`` / ``filled_price`` /
    ``status`` for any that have been filled or cancelled.

    Also propagates ``status='filled'`` back to ``strategy_results`` for
    orders linked to a signal via ``signal_id``.

    Returns:
        Dict with reconciled_count, skipped_count, signals_updated, timestamp.
    """
    from src.server.services.order_service import reconcile_submitted_orders

    logger.info("[orders/reconcile] starting fill reconciliation")
    result = await reconcile_submitted_orders()
    return {
        "status": "success",
        "reconciled_count": result.reconciled_count,
        "skipped_count": result.skipped_count,
        "signals_updated": result.signals_updated,
        "timestamp": result.timestamp,
    }


if __name__ == "__main__":
    """Smoke test: verify router routes are defined correctly."""
    print("=" * 60)
    print("routers/orders.py smoke tests")
    print("=" * 60)

    routes = [r.path for r in router.routes]
    expected = [
        "/v1/orders",
        "/v1/orders/execute",
        "/v1/orders/scale",
        "/v1/orders/signal",
        "/v1/orders/close/{symbol}",
        "/v1/orders/{order_id}",
    ]
    for path in expected:
        assert path in routes, f"Missing route: {path}"
        print(f"  [OK]  {path}")

    print("\n[ALL OK] routers/orders.py smoke tests passed")
