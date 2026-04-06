"""WebSocket endpoint for real-time market data streaming.

This router provides WebSocket endpoints for streaming real-time market data
(trades and bars) to UI clients. Market data is received from AlpacaDataStreamer
and broadcast via db_stream_handlers.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime, timezone
from src.semi_auto.ws_manager import ws_manager
from src.common.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/market", tags=["market"])


@router.websocket("/ws")
async def market_data_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time market data (trades and bars).

    Receives broadcasts from AlpacaDataStreamer via db_stream_handlers.
    Market data messages are automatically broadcast to all connected clients
    when trades or bars are received from Alpaca WebSocket.

    Message types sent to clients:
    - connection: Initial connection confirmation
    - trade_update: Real-time trade data
    - bar_update: Real-time bar/candle data
    - error: Error messages

    Args:
        websocket: FastAPI WebSocket connection

    Example trade_update message:
        {
            "type": "trade_update",
            "symbol": "AAPL",
            "price": 150.25,
            "size": 100,
            "timestamp": "2024-01-15T10:30:45.123456",
            "exchange": "Q"
        }

    Example bar_update message:
        {
            "type": "bar_update",
            "symbol": "AAPL",
            "timestamp": "2024-01-15T10:30:00",
            "timeframe": "1Min",
            "open": 150.00,
            "high": 150.50,
            "low": 149.90,
            "close": 150.25,
            "volume": 50000,
            "vwap": 150.20
        }
    """
    await ws_manager.connect(websocket)

    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "connection",
            "message": "Connected to market data stream",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        logger.info(f"[market] Client connected to market stream")

        # Keep connection alive
        # (messages are sent via ws_manager.broadcast() from db_stream_handlers)
        while True:
            # Wait for client messages (ping, subscribe requests, etc.)
            data = await websocket.receive_text()

            # Optional: Handle client subscriptions for specific symbols
            # For MVP, broadcast all market data to all clients
            logger.debug(f"[market] Received client message: {data}")

    except WebSocketDisconnect:
        logger.info("[market] Client disconnected from market stream")
        await ws_manager.disconnect(websocket)
    except Exception as exc:
        logger.error(f"[market] WebSocket error: {exc}", exc_info=True)
        await ws_manager.disconnect(websocket)


if __name__ == "__main__":
    """Smoke test: verify router instantiation."""
    print("=" * 60)
    print("market.py smoke tests")
    print("=" * 60)

    # Test 1: Router exists
    assert router is not None, "Router should exist"
    print("  [OK]  Router instantiation")

    # Test 2: Router has correct prefix
    assert router.prefix == "/v1/market", "Router should have /v1/market prefix"
    print("  [OK]  Router prefix")

    # Test 3: Router has WebSocket route
    routes = [route for route in router.routes]
    assert len(routes) > 0, "Router should have routes"
    print(f"  [OK]  Router has {len(routes)} route(s)")

    print("\n[ALL OK] market.py smoke tests passed")
