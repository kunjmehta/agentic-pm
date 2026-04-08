"""Unit tests for Redis WebSocket Proxy.

Tests the WebSocket proxy functionality using mocks to avoid
requiring actual Redis connection and WebSocket clients.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio


class TestRedisWSProxy:
    """Test suite for Redis WebSocket proxy."""

    @patch("src.server.routers.redis_ws_proxy.config")
    @patch("src.server.routers.redis_ws_proxy.RedisStreamConsumer")
    @pytest.mark.asyncio
    async def test_websocket_connection_accepted(self, mock_consumer_class, mock_config):
        """Test that WebSocket connection is accepted."""
        from src.server.routers.redis_ws_proxy import redis_stream_proxy

        # Setup mocks
        mock_config.get.return_value = True  # Redis enabled

        mock_websocket = AsyncMock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_json = AsyncMock()
        mock_websocket.receive_text = AsyncMock(side_effect=asyncio.CancelledError)

        mock_consumer = MagicMock()
        mock_consumer.subscribe_trades = MagicMock()
        mock_consumer.subscribe_bars = MagicMock()
        mock_consumer.stop = MagicMock()
        mock_consumer.run = AsyncMock()
        mock_consumer_class.return_value = mock_consumer

        # Test connection
        try:
            await redis_stream_proxy(mock_websocket, "AAPL")
        except asyncio.CancelledError:
            pass

        # Verify WebSocket accepted
        mock_websocket.accept.assert_called_once()

        # Verify connection message sent
        assert mock_websocket.send_json.call_count >= 1
        first_call = mock_websocket.send_json.call_args_list[0]
        message = first_call[0][0]
        assert message["type"] == "connection"
        assert message["symbol"] == "AAPL"

    @patch("src.server.routers.redis_ws_proxy.config")
    @patch("src.server.routers.redis_ws_proxy.RedisStreamConsumer")
    @pytest.mark.asyncio
    async def test_consumer_subscriptions(self, mock_consumer_class, mock_config):
        """Test that consumer subscribes to both trades and bars."""
        from src.server.routers.redis_ws_proxy import redis_stream_proxy

        # Setup mocks
        mock_config.get.return_value = True  # Redis enabled

        mock_websocket = AsyncMock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_json = AsyncMock()
        mock_websocket.receive_text = AsyncMock(side_effect=asyncio.CancelledError)

        mock_consumer = MagicMock()
        mock_consumer.subscribe_trades = MagicMock()
        mock_consumer.subscribe_bars = MagicMock()
        mock_consumer.stop = MagicMock()
        mock_consumer.run = AsyncMock()
        mock_consumer_class.return_value = mock_consumer

        # Test connection
        try:
            await redis_stream_proxy(mock_websocket, "AAPL")
        except asyncio.CancelledError:
            pass

        # Verify subscriptions
        mock_consumer.subscribe_trades.assert_called_once()
        mock_consumer.subscribe_bars.assert_called_once()

        # Check subscription arguments
        trades_call = mock_consumer.subscribe_trades.call_args
        bars_call = mock_consumer.subscribe_bars.call_args

        assert trades_call[0][0] == ["AAPL"], "Should subscribe to AAPL trades"
        assert bars_call[0][0] == ["AAPL"], "Should subscribe to AAPL bars"

    @patch("src.server.routers.redis_ws_proxy.config")
    @patch("src.server.routers.redis_ws_proxy.RedisStreamConsumer")
    @pytest.mark.asyncio
    async def test_consumer_cleanup_on_disconnect(self, mock_consumer_class, mock_config):
        """Test that consumer is stopped and cleaned up on disconnect."""
        from src.server.routers.redis_ws_proxy import redis_stream_proxy

        # Setup mocks
        mock_config.get.return_value = True  # Redis enabled

        mock_websocket = AsyncMock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_json = AsyncMock()
        mock_websocket.receive_text = AsyncMock(side_effect=asyncio.CancelledError)

        mock_consumer = MagicMock()
        mock_consumer.subscribe_trades = MagicMock()
        mock_consumer.subscribe_bars = MagicMock()
        mock_consumer.stop = MagicMock()
        mock_consumer.run = AsyncMock()
        mock_consumer_class.return_value = mock_consumer

        # Test connection
        try:
            await redis_stream_proxy(mock_websocket, "AAPL")
        except asyncio.CancelledError:
            pass

        # Verify consumer stopped
        mock_consumer.stop.assert_called_once()

    @patch("src.server.routers.redis_ws_proxy.config")
    @pytest.mark.asyncio
    async def test_redis_disabled_closes_connection(self, mock_config):
        """Test that connection is closed when Redis is disabled."""
        from src.server.routers.redis_ws_proxy import redis_stream_proxy

        # Setup mocks
        mock_config.get.return_value = False  # Redis disabled

        mock_websocket = AsyncMock()
        mock_websocket.close = AsyncMock()

        # Test connection
        await redis_stream_proxy(mock_websocket, "AAPL")

        # Verify WebSocket closed
        mock_websocket.close.assert_called_once_with(
            code=1011, reason="Redis is not enabled"
        )

    @patch("src.server.routers.redis_ws_proxy.config")
    @patch("src.common.cache.redis_manager.RedisManager")
    @pytest.mark.asyncio
    async def test_health_check_redis_enabled(self, mock_redis_manager, mock_config):
        """Test health check when Redis is enabled and healthy."""
        from src.server.routers.redis_ws_proxy import redis_health

        # Setup mocks
        mock_config.get.return_value = True  # Redis enabled

        mock_mgr = MagicMock()
        mock_mgr.health_check.return_value = True
        mock_mgr.get_info.return_value = {"redis_version": "7.0.0"}
        mock_redis_manager.return_value = mock_mgr

        # Test health check
        result = await redis_health()

        assert result["healthy"] is True
        assert result["enabled"] is True
        assert "Redis connection healthy" in result["message"]

    @patch("src.server.routers.redis_ws_proxy.config")
    @pytest.mark.asyncio
    async def test_health_check_redis_disabled(self, mock_config):
        """Test health check when Redis is disabled."""
        from src.server.routers.redis_ws_proxy import redis_health

        # Setup mocks
        mock_config.get.return_value = False  # Redis disabled

        # Test health check
        result = await redis_health()

        assert result["healthy"] is False
        assert result["enabled"] is False
        assert "Redis is disabled" in result["message"]

    @patch("src.server.routers.redis_ws_proxy.config")
    @patch("src.server.routers.redis_ws_proxy.RedisStreamConsumer")
    @pytest.mark.asyncio
    async def test_symbol_uppercased(self, mock_consumer_class, mock_config):
        """Test that symbol is automatically uppercased."""
        from src.server.routers.redis_ws_proxy import redis_stream_proxy

        # Setup mocks
        mock_config.get.return_value = True  # Redis enabled

        mock_websocket = AsyncMock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_json = AsyncMock()
        mock_websocket.receive_text = AsyncMock(side_effect=asyncio.CancelledError)

        mock_consumer = MagicMock()
        mock_consumer.subscribe_trades = MagicMock()
        mock_consumer.subscribe_bars = MagicMock()
        mock_consumer.stop = MagicMock()
        mock_consumer.run = AsyncMock()
        mock_consumer_class.return_value = mock_consumer

        # Test with lowercase symbol
        try:
            await redis_stream_proxy(mock_websocket, "aapl")
        except asyncio.CancelledError:
            pass

        # Verify subscriptions use uppercase
        trades_call = mock_consumer.subscribe_trades.call_args
        bars_call = mock_consumer.subscribe_bars.call_args

        assert trades_call[0][0] == ["AAPL"], "Should uppercase symbol for trades"
        assert bars_call[0][0] == ["AAPL"], "Should uppercase symbol for bars"

        # Verify connection message has uppercase symbol
        connection_msg = mock_websocket.send_json.call_args_list[0][0][0]
        assert connection_msg["symbol"] == "AAPL", "Should uppercase symbol in message"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
