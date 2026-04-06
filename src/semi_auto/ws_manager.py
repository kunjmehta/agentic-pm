"""WebSocket connection manager for real-time portfolio updates.

Manages active WebSocket connections and provides broadcasting capabilities
for sending portfolio updates to all connected clients.
"""

import asyncio
from datetime import datetime, timezone
from typing import Set

from fastapi import WebSocket
from src.common.utils import get_logger

logger = get_logger(__name__)


class PortfolioWSManager:
    """Manages WebSocket connections for portfolio updates.

    Tracks active connections, handles broadcasting messages to all clients,
    and manages connection lifecycle (connect, disconnect, cleanup).

    Attributes:
        active_connections: Set of active WebSocket connections.
    """

    def __init__(self):
        """Initialize the WebSocket manager with empty connection set."""
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            websocket: FastAPI WebSocket instance to register.
        """
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"[ws] Client connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister and close a WebSocket connection.

        Args:
            websocket: FastAPI WebSocket instance to unregister.
        """
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"[ws] Client disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, websocket: WebSocket) -> None:
        """Send a message to a specific WebSocket client.

        Args:
            message: Message dict to send (will be JSON-serialized).
            websocket: Target WebSocket connection.
        """
        try:
            await websocket.send_json(message)
        except Exception as exc:
            logger.warning(f"[ws] Failed to send personal message: {exc}")
            await self.disconnect(websocket)

    async def broadcast(self, message: dict) -> None:
        """Broadcast a message to all active WebSocket clients.

        Automatically removes dead connections that fail to receive.

        Args:
            message: Message dict to broadcast (will be JSON-serialized).
        """
        if not self.active_connections:
            return

        dead_connections = set()

        async with self._lock:
            for connection in self.active_connections.copy():
                try:
                    await connection.send_json(message)
                except Exception as exc:
                    logger.warning(f"[ws] Failed to broadcast to client: {exc}")
                    dead_connections.add(connection)

        # Remove dead connections outside the lock
        for dead in dead_connections:
            await self.disconnect(dead)

    async def broadcast_error(self, error_message: str) -> None:
        """Broadcast an error message to all connected clients.

        Args:
            error_message: Human-readable error message.
        """
        await self.broadcast({
            "type": "error",
            "message": error_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_connection_count(self) -> int:
        """Get the current number of active connections.

        Returns:
            Number of active WebSocket connections.
        """
        return len(self.active_connections)


# Global singleton instance
ws_manager = PortfolioWSManager()


if __name__ == "__main__":
    """Smoke test: verify PortfolioWSManager instantiation."""
    print("=" * 60)
    print("ws_manager.py smoke tests")
    print("=" * 60)

    # Test 1: Instantiation
    manager = PortfolioWSManager()
    assert manager.get_connection_count() == 0, "Initial connection count should be 0"
    print("  [OK]  PortfolioWSManager instantiation")

    # Test 2: Singleton instance
    assert ws_manager is not None, "Global ws_manager should exist"
    assert isinstance(ws_manager, PortfolioWSManager), "Should be PortfolioWSManager instance"
    print("  [OK]  Global ws_manager singleton")

    # Test 3: Methods exist
    assert hasattr(manager, "connect"), "Should have connect method"
    assert hasattr(manager, "disconnect"), "Should have disconnect method"
    assert hasattr(manager, "broadcast"), "Should have broadcast method"
    assert hasattr(manager, "broadcast_error"), "Should have broadcast_error method"
    assert hasattr(manager, "send_personal_message"), "Should have send_personal_message method"
    assert hasattr(manager, "get_connection_count"), "Should have get_connection_count method"
    print("  [OK]  All required methods present")

    print("\n[ALL OK] ws_manager.py smoke tests passed")
