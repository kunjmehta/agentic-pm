"""WebSocket endpoint for real-time market data streaming.

This router provides WebSocket endpoints for streaming real-time market data
(trades and bars) to UI clients. Market data is received from AlpacaDataStreamer
and broadcast via db_stream_handlers.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from src.server.ws_manager import ws_manager
from src.server.helpers import get_alpaca_client
from src.common.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/market", tags=["market"])


@router.post("/internal/broadcast")
async def internal_broadcast(message: Dict[str, Any]) -> Dict[str, bool]:
    """Internal endpoint — ETL process forwards bar/trade updates to WS clients.

    Called by the ETL process broadcaster so that the API's connected ws_manager
    receives real-time data even though ETL runs in a separate OS process.
    """
    await ws_manager.broadcast(message)
    return {"ok": True}


@router.get("/previous-close")
async def get_previous_close(symbols: str = Query(..., description="Comma-separated symbols")):
    """Get previous trading day close prices for % change calculation.

    Fetches the most recent closing price for each symbol by querying Alpaca API
    directly (authoritative source). Searches back up to 5 days to handle weekends
    and holidays.

    Args:
        symbols: Comma-separated list of stock symbols (e.g., "AAPL,MSFT,GOOGL")

    Returns:
        dict: {
            "previous_close": {
                "AAPL": 150.25,
                "MSFT": 380.50,
                ...
            }
        }

    Example:
        GET /v1/market/previous-close?symbols=AAPL,MSFT
        => {"previous_close": {"AAPL": 150.25, "MSFT": 380.50}}
    """
    symbol_list = [s.strip().upper() for s in symbols.split(',')]
    results: Dict[str, Optional[float]] = {}

    client = get_alpaca_client()

    async def _fetch_close(symbol: str) -> tuple[str, float | None]:
        for days_back in range(1, 6):
            end_date = datetime.now() - timedelta(days=days_back)
            start_date = end_date - timedelta(days=1)
            try:
                bars = await asyncio.to_thread(
                    client.get_stock_bars,
                    StockBarsRequest(
                        symbol_or_symbols=symbol,
                        timeframe=TimeFrame.Day,
                        start=start_date,
                        end=end_date,
                    ),
                )
                if symbol in bars and len(bars[symbol]) > 0:
                    price = float(bars[symbol][-1].close)
                    logger.debug(f"Previous close for {symbol}: ${price:.2f} ({days_back} days back)")
                    return symbol, price
            except Exception as exc:
                logger.error(f"Failed to fetch previous close for {symbol}: {exc}")
                return symbol, None
        logger.warning(f"No previous close data found for {symbol} in last 5 days")
        return symbol, None

    pairs = await asyncio.gather(*[_fetch_close(sym) for sym in symbol_list])
    results = dict(pairs)

    return {"previous_close": results}


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
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(project_root))

    print("=" * 60)
    print("market.py smoke tests")
    print("=" * 60)

    # Test 1: Router exists
    assert router is not None, "Router should exist"
    print("  [OK]  Router instantiation")

    # Test 2: Router has correct prefix
    assert router.prefix == "/v1/market", "Router should have /v1/market prefix"
    print("  [OK]  Router prefix")

    # Test 3: Router has routes (WebSocket + GET)
    routes = [route for route in router.routes]
    assert len(routes) >= 2, "Router should have at least 2 routes (WebSocket + previous-close)"
    print(f"  [OK]  Router has {len(routes)} route(s)")

    # Test 4: Previous close endpoint exists
    route_paths = [route.path for route in router.routes]
    assert "/v1/market/previous-close" in route_paths, "Router should have /previous-close endpoint"
    print("  [OK]  Previous close endpoint exists")

    print("\n[ALL OK] market.py smoke tests passed")
