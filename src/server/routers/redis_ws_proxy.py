"""WebSocket proxy for Redis Streams to UI clients.

This router provides WebSocket endpoints that proxy Redis Stream data
to browser clients for real-time market data updates. Each WebSocket
connection creates a dedicated RedisStreamConsumer instance for
per-client subscription management.

Usage:
    # Client connects via WebSocket
    ws = new WebSocket('ws://localhost:8000/v1/redis/stream/AAPL')

    # Receive real-time trades and bars
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.type === 'trade') {
            console.log(`Trade: ${data.symbol} @ ${data.price}`)
        } else if (data.type === 'bar') {
            console.log(`Bar: ${data.symbol} OHLCV`)
        }
    }
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.common.cache.redis_stream_consumer import RedisStreamConsumer
from src.common.utils import get_logger, config

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/redis", tags=["redis"])


@router.websocket("/stream/{symbol}")
async def redis_stream_proxy(websocket: WebSocket, symbol: str):
    """WebSocket endpoint for Redis Stream proxy.

    Creates a dedicated Redis Stream consumer for this client and forwards
    both trades and bars for the requested symbol as JSON.

    Args:
        websocket: FastAPI WebSocket connection
        symbol: Stock ticker symbol (e.g., "AAPL")

    Message types sent to client:
        {
            "type": "connection",
            "message": "Connected to Redis stream for AAPL",
            "symbol": "AAPL",
            "timestamp": "2024-03-20T10:30:00Z"
        }

        {
            "type": "trade",
            "symbol": "AAPL",
            "price": 150.25,
            "size": 100,
            "timestamp": "2024-03-20T10:30:45.123456Z",
            "exchange": "Q",
            "conditions": ["@"],
            ... (other trade fields)
        }

        {
            "type": "bar",
            "symbol": "AAPL",
            "timestamp": "2024-03-20T10:30:00Z",
            "timeframe": "1Min",
            "open": 150.00,
            "high": 150.50,
            "low": 149.75,
            "close": 150.25,
            "volume": 1000000,
            "vwap": 150.15,
            ... (other bar fields)
        }

        {
            "type": "error",
            "message": "Error description",
            "timestamp": "2024-03-20T10:30:00Z"
        }

        {
            "type": "disconnect",
            "message": "Consumer stopped",
            "timestamp": "2024-03-20T10:30:00Z"
        }
    """
    symbol = symbol.upper()
    consumer: Optional[RedisStreamConsumer] = None
    consumer_task: Optional[asyncio.Task] = None

    # Check if Redis is enabled
    if not config.get("redis.enabled", default=False):
        await websocket.close(code=1011, reason="Redis is not enabled")
        logger.warning(f"[redis-ws] Client attempted connection but Redis is disabled")
        return

    try:
        # Accept WebSocket connection
        await websocket.accept()
        logger.info(f"[redis-ws] Client connected for {symbol}")

        # Send connection confirmation
        await websocket.send_json({
            "type": "connection",
            "message": f"Connected to Redis stream for {symbol}",
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Create Redis Stream consumer
        consumer = RedisStreamConsumer()

        # Define handler to forward data to WebSocket
        async def forward_to_ws(data: dict):
            """Forward Redis message to WebSocket client as JSON.

            Args:
                data: Deserialized message data from Redis Stream
            """
            try:
                # Determine message type from data structure
                # Trade data has 'trade_id', bar data has 'timeframe'
                if 'trade_id' in data or 'conditions' in data:
                    message_type = "trade"
                elif 'timeframe' in data or 'vwap' in data:
                    message_type = "bar"
                else:
                    message_type = "data"  # Generic fallback

                # Add type field and send
                message = {
                    "type": message_type,
                    **data
                }

                await websocket.send_json(message)
                logger.debug(f"[redis-ws] Forwarded {message_type} to client: {symbol}")

            except WebSocketDisconnect:
                logger.info(f"[redis-ws] Client disconnected during forward: {symbol}")
                raise

            except Exception as exc:
                logger.error(f"[redis-ws] Error forwarding to WebSocket: {exc}", exc_info=True)
                # Don't raise - keep connection alive for subsequent messages

        # Subscribe to both trades and bars for this symbol
        consumer.subscribe_trades([symbol], forward_to_ws)
        consumer.subscribe_bars([symbol], forward_to_ws)

        logger.info(f"[redis-ws] Subscribed to trades and bars for {symbol}")

        # Start consumer loop as background task
        consumer_task = asyncio.create_task(consumer.run())

        # Keep WebSocket connection alive
        # Listen for client messages (ping, unsubscribe, etc.)
        while True:
            try:
                # Wait for client messages (optional - for future features)
                data = await websocket.receive_text()
                logger.debug(f"[redis-ws] Received client message: {data}")

                # Future enhancement: Handle client commands
                # - "ping" -> send "pong"
                # - "unsubscribe" -> stop consumer
                # - "subscribe:MSFT" -> add new symbol

            except WebSocketDisconnect:
                logger.info(f"[redis-ws] Client disconnected: {symbol}")
                break

    except WebSocketDisconnect:
        logger.info(f"[redis-ws] Client disconnected during setup: {symbol}")

    except Exception as exc:
        logger.error(f"[redis-ws] WebSocket error for {symbol}: {exc}", exc_info=True)

        # Try to send error message to client
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except:
            pass

    finally:
        # Cleanup: stop consumer and close connection
        if consumer:
            logger.info(f"[redis-ws] Stopping consumer for {symbol}")
            consumer.stop()

        if consumer_task and not consumer_task.done():
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

        # Send disconnect message (if connection still alive)
        try:
            await websocket.send_json({
                "type": "disconnect",
                "message": "Consumer stopped",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except:
            pass

        logger.info(f"[redis-ws] Cleanup complete for {symbol}")


@router.get("/health")
async def redis_health():
    """Check Redis connection health.

    Returns:
        dict: Health status and connection info
    """
    from src.common.cache.redis_manager import RedisManager

    try:
        redis_enabled = config.get("redis.enabled", default=False)

        if not redis_enabled:
            return {
                "healthy": False,
                "enabled": False,
                "message": "Redis is disabled in configuration"
            }

        redis_mgr = RedisManager()
        is_healthy = redis_mgr.health_check()

        return {
            "healthy": is_healthy,
            "enabled": True,
            "message": "Redis connection healthy" if is_healthy else "Redis connection failed",
            "info": redis_mgr.get_info() if is_healthy else {}
        }

    except Exception as exc:
        logger.error(f"Redis health check failed: {exc}", exc_info=True)
        return {
            "healthy": False,
            "enabled": True,
            "message": f"Health check error: {str(exc)}"
        }


if __name__ == "__main__":
    """Test WebSocket proxy with mock client."""
    import sys
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(project_root))

    print("=" * 60)
    print("RedisWSProxy Tests")
    print("=" * 60)

    # Test 1: Router instantiation
    print("\n[Test 1] Router instantiation:")
    assert router is not None, "Router should exist"
    assert router.prefix == "/v1/redis", "Router should have /v1/redis prefix"
    print("  [OK] Router created with correct prefix")

    # Test 2: Routes registered
    print("\n[Test 2] Routes registered:")
    routes = [route for route in router.routes]
    route_paths = [route.path for route in routes]

    assert "/v1/redis/stream/{symbol}" in route_paths, "Should have WebSocket stream endpoint"
    assert "/v1/redis/health" in route_paths, "Should have health check endpoint"
    print(f"  [OK] Router has {len(routes)} route(s)")
    for path in route_paths:
        print(f"    - {path}")

    # Test 3: Health check (without Redis connection)
    print("\n[Test 3] Health check endpoint:")
    import asyncio

    async def test_health():
        result = await redis_health()
        print(f"  Health status: {result}")
        return result

    health_result = asyncio.run(test_health())
    print("  [OK] Health check endpoint functional")

    print("\n" + "=" * 60)
    print("✓ All RedisWSProxy router tests passed")
    print("=" * 60)

    print("\n[Manual Testing]")
    print("To test the WebSocket proxy:")
    print("  1. Ensure Redis is enabled and configured")
    print("  2. Start the FastAPI server: python src/server/main.py")
    print("  3. Connect WebSocket client:")
    print("     ws://localhost:8000/v1/redis/stream/AAPL")
    print("  4. Run ingestion script to publish data")
    print("  5. Observe real-time messages in browser console")
    print("\nJavaScript test client:")
    print("""
    const ws = new WebSocket('ws://localhost:8000/v1/redis/stream/AAPL');

    ws.onopen = () => console.log('Connected');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log(`[${data.type}]`, data);
    };
    ws.onerror = (error) => console.error('WebSocket error:', error);
    ws.onclose = () => console.log('Disconnected');
    """)
