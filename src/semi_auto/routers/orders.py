"""Order execution router — POST/DELETE /v1/orders/...

Provides direct REST access to all order-execution skill functions outside
the agent reasoning flow.  These endpoints are intentionally thin wrappers
around the registry functions so they remain consistent with what the graph
executor calls.

Endpoints:
    GET  /v1/orders                       List open orders from Alpaca
    POST /v1/orders/execute               Place a market or limit order
    POST /v1/orders/close/{symbol}        Liquidate a full position
    POST /v1/orders/scale                 Resize to a target portfolio %
    POST /v1/orders/signal                Execute a strategy buy/sell/hold signal
    DELETE /v1/orders/{order_id}          Cancel a specific order
    DELETE /v1/orders                     Cancel all open orders

All write endpoints (/execute, /close, /scale, /signal, DELETE) go through
the same audit trail as the agent — LOG entries are written but no LangGraph
checkpoint is created.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.common.external.alpaca_portfolio import (
    cancel_all_orders as _cancel_all_orders,
    cancel_order as _alpaca_cancel_order,
    fetch_orders,
)
from src.common.utils import get_logger
from src.semi_auto.models.endpoints import (
    OpenOrdersResponse,
    OrderCancelResponse,
    OrderResponse,
    ScalePositionResponse,
    StrategySignalExecutionResponse,
)

from src.semi_auto.registry.functions import AVAILABLE_FUNCTIONS

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


def _registry_fn(name: str):
    """Resolve a function from the registry, raising 503 if unavailable.

    Args:
        name: Registry function name.

    Returns:
        Callable registered under ``name``.

    Raises:
        HTTPException: 503 if the function is not registered.
    """
    fn = AVAILABLE_FUNCTIONS.get(name)
    if fn is None:
        raise HTTPException(status_code=503, detail=f"Function '{name}' not available")
    return fn


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=OpenOrdersResponse)
async def list_open_orders():
    """List all currently open orders from Alpaca.

    Returns:
        OpenOrdersResponse with orders list and count.
    """
    try:
        orders = fetch_orders(status="open")
        return {
            "status": "success",
            "orders": orders,
            "count": len(orders),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[orders/list] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/execute", response_model=OrderResponse)
async def execute_order(request: ExecuteOrderRequest):
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
    try:
        fn = _registry_fn("execute_order")
        result = fn(
            symbol=request.symbol,
            qty=request.qty,
            side=request.side,
            order_type=request.order_type,
            limit_price=request.limit_price,
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("error", "Order failed"))
        return {
            "status": "success",
            "order": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[orders/execute] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/close/{symbol}", response_model=OrderResponse)
async def close_position(symbol: str):
    """Liquidate the full open position for a symbol at market price.

    Args:
        symbol: Stock ticker whose position to close.

    Returns:
        OrderResponse with the closing order details.
    """
    logger.info(f"[orders/close] closing position for {symbol.upper()}")
    try:
        fn = _registry_fn("close_position")
        result = fn(symbol=symbol)
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("error", "Close failed"))
        return {
            "status": "success",
            "order": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[orders/close/{symbol}] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/scale", response_model=ScalePositionResponse)
async def scale_position(request: ScalePositionRequest):
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
    try:
        fn = _registry_fn("scale_position")
        result = fn(
            symbol=request.symbol,
            target_pct=request.target_pct,
            order_type=request.order_type,
            limit_price=request.limit_price,
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("error", "Scale failed"))
        return {
            "status": "success",
            **{k: v for k, v in result.items() if k not in ("timestamp",)},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[orders/scale] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/signal", response_model=StrategySignalExecutionResponse)
async def execute_strategy_signal(request: StrategySignalRequest):
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
    try:
        fn = _registry_fn("execute_strategy_signal")
        result = fn(
            symbol=request.symbol,
            signal=request.signal,
            confidence=request.confidence,
            base_position_pct=request.base_position_pct,
            order_type=request.order_type,
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("error", "Signal execution failed"))
        return {
            "status": "success",
            **{k: v for k, v in result.items() if k not in ("timestamp",)},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[orders/signal] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{order_id}", response_model=OrderCancelResponse)
async def cancel_order(order_id: str):
    """Cancel an open order by its Alpaca UUID.

    Args:
        order_id: Alpaca order UUID string.

    Returns:
        OrderCancelResponse confirming cancellation.
    """
    logger.info(f"[orders/cancel] order_id={order_id}")
    try:
        result = _alpaca_cancel_order(order_id=order_id)
        return {
            "status": "success",
            "order_id": order_id,
            "message": f"Order {order_id} cancelled",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[orders/cancel/{order_id}] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("", response_model=OrderCancelResponse)
async def cancel_all_orders():
    """Cancel all open orders.

    Returns:
        OrderCancelResponse with count of cancelled orders.
    """
    logger.info("[orders/cancel_all] cancelling all open orders")
    try:
        result = _cancel_all_orders()
        count = result.get("cancelled_count", 0)
        return {
            "status": "success",
            "message": f"Cancelled {count} open orders",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[orders/cancel_all] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/reconcile")
async def reconcile_orders():
    """Reconcile submitted orders against Alpaca fill data.

    Fetches all ``live_orders`` with ``status='submitted'``, queries Alpaca
    for their current state, and updates ``filled_at`` / ``filled_price`` /
    ``status`` for any that have been filled or cancelled.

    Also propagates ``status='filled'`` back to ``strategy_results`` for
    orders linked to a signal via ``signal_id``.

    Returns:
        Dict with reconciled_count, skipped_count, timestamp.
    """
    from src.common.dao import OrdersDAO
    from src.common.dao.strategy_dao import StrategyDAO
    from src.common.external.alpaca_portfolio import fetch_orders

    logger.info("[orders/reconcile] starting fill reconciliation")
    try:
        orders_dao = OrdersDAO()
        submitted = orders_dao.get_submitted_orders()

        if not submitted:
            orders_dao.close()
            return {
                "status": "success",
                "reconciled_count": 0,
                "skipped_count": 0,
                "message": "No submitted orders to reconcile",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Fetch recent closed orders from Alpaca (covers fills + cancellations).
        broker_orders = fetch_orders(status="closed", limit=200)
        broker_map = {o["id"]: o for o in broker_orders}

        reconciled = 0
        skipped = 0
        signal_ids_filled: list = []

        for row in submitted:
            bid = row.get("broker_order_id")
            if not bid or bid not in broker_map:
                skipped += 1
                continue

            alpaca_order = broker_map[bid]
            alpaca_status = alpaca_order.get("status", "")

            if alpaca_status == "filled":
                filled_at_raw = alpaca_order.get("filled_at")
                filled_at = (
                    datetime.fromisoformat(filled_at_raw.replace("Z", "+00:00"))
                    if filled_at_raw
                    else datetime.now(timezone.utc)
                )
                filled_price = alpaca_order.get("filled_avg_price") or 0.0
                orders_dao.update_fill(
                    broker_order_id=bid,
                    filled_at=filled_at,
                    filled_price=float(filled_price),
                )
                if row.get("signal_id"):
                    signal_ids_filled.append(row["signal_id"])
                reconciled += 1
            elif alpaca_status in ("canceled", "expired", "rejected"):
                orders_dao.update_status(broker_order_id=bid, status=alpaca_status)
                reconciled += 1

        # Propagate fill status to strategy_results for linked signals.
        if signal_ids_filled:
            s_dao = StrategyDAO()
            for sid in signal_ids_filled:
                s_dao.execute(
                    "UPDATE strategy_results SET status = 'filled' WHERE id = ?",
                    (sid,),
                )
            s_dao.close()

        orders_dao.close()
        logger.info(
            f"[orders/reconcile] reconciled={reconciled} skipped={skipped} "
            f"signals_updated={len(signal_ids_filled)}"
        )
        return {
            "status": "success",
            "reconciled_count": reconciled,
            "skipped_count": skipped,
            "signals_updated": len(signal_ids_filled),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"[orders/reconcile] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


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
