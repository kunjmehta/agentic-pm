"""Unit tests for Redis Stream Publisher.

Tests the Redis stream publishing functionality using mocks
to avoid requiring actual Redis connection.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
import msgpack


class TestRedisStreamPublisher:
    """Test suite for RedisStreamPublisher."""

    @patch("src.common.cache.redis_stream_publisher.RedisManager")
    @patch("src.common.cache.redis_stream_publisher.config")
    def test_initialize_publisher(self, mock_config, mock_redis_manager):
        """Test successful publisher initialization."""
        # Setup mocks
        mock_config.get.return_value = {
            "trades_prefix": "stream:trades:",
            "bars_prefix": "stream:bars:",
            "retention_minutes": 5,
        }

        mock_client = MagicMock()
        mock_redis_manager.return_value.get_client.return_value = mock_client

        from src.common.cache.redis_stream_publisher import RedisStreamPublisher

        # Initialize publisher
        publisher = RedisStreamPublisher()

        assert publisher.trades_prefix == "stream:trades:"
        assert publisher.bars_prefix == "stream:bars:"
        assert publisher.retention_minutes == 5

    @patch("src.common.cache.redis_stream_publisher.RedisManager")
    @patch("src.common.cache.redis_stream_publisher.config")
    def test_publish_trade(self, mock_config, mock_redis_manager):
        """Test publishing trade data to stream."""
        # Setup mocks
        mock_config.get.return_value = {
            "trades_prefix": "stream:trades:",
            "bars_prefix": "stream:bars:",
            "retention_minutes": 5,
        }

        mock_client = MagicMock()
        mock_client.xadd.return_value = b"1710932400000-0"
        mock_redis_manager.return_value.get_client.return_value = mock_client

        from src.common.cache.redis_stream_publisher import RedisStreamPublisher

        publisher = RedisStreamPublisher()

        # Publish trade
        trade_data = {
            "price": 150.25,
            "size": 100,
            "timestamp": "2024-03-20T10:30:00Z",
            "conditions": ["@", "F"],
            "exchange": "Q",
        }

        entry_id = publisher.publish_trade("AAPL", trade_data)

        # Verify
        assert entry_id == "1710932400000-0"
        mock_client.xadd.assert_called_once()

        # Check call arguments
        call_kwargs = mock_client.xadd.call_args.kwargs
        assert call_kwargs["name"] == "stream:trades:AAPL"
        assert "data" in call_kwargs["fields"]
        assert call_kwargs["approximate"] is True

        # Verify msgpack serialization
        serialized_data = call_kwargs["fields"]["data"]
        deserialized = msgpack.unpackb(serialized_data, raw=False)
        assert deserialized == trade_data

    @patch("src.common.cache.redis_stream_publisher.RedisManager")
    @patch("src.common.cache.redis_stream_publisher.config")
    def test_publish_bar(self, mock_config, mock_redis_manager):
        """Test publishing bar data to stream."""
        # Setup mocks
        mock_config.get.return_value = {
            "trades_prefix": "stream:trades:",
            "bars_prefix": "stream:bars:",
            "retention_minutes": 5,
        }

        mock_client = MagicMock()
        mock_client.xadd.return_value = b"1710932400000-0"
        mock_redis_manager.return_value.get_client.return_value = mock_client

        from src.common.cache.redis_stream_publisher import RedisStreamPublisher

        publisher = RedisStreamPublisher()

        # Publish bar
        bar_data = {
            "timestamp": "2024-03-20T10:30:00Z",
            "open": 150.00,
            "high": 150.50,
            "low": 149.75,
            "close": 150.25,
            "volume": 1000000,
            "vwap": 150.15,
        }

        entry_id = publisher.publish_bar("AAPL", bar_data)

        # Verify
        assert entry_id == "1710932400000-0"
        mock_client.xadd.assert_called_once()

        # Check call arguments
        call_kwargs = mock_client.xadd.call_args.kwargs
        assert call_kwargs["name"] == "stream:bars:AAPL"
        assert "data" in call_kwargs["fields"]

        # Verify msgpack serialization
        serialized_data = call_kwargs["fields"]["data"]
        deserialized = msgpack.unpackb(serialized_data, raw=False)
        assert deserialized == bar_data

    @patch("src.common.cache.redis_stream_publisher.RedisManager")
    @patch("src.common.cache.redis_stream_publisher.config")
    def test_get_stream_info(self, mock_config, mock_redis_manager):
        """Test getting stream information."""
        # Setup mocks
        mock_config.get.return_value = {
            "trades_prefix": "stream:trades:",
            "bars_prefix": "stream:bars:",
            "retention_minutes": 5,
        }

        mock_client = MagicMock()
        mock_client.xinfo_stream.return_value = {
            b"length": 100,
            b"first-entry": ["1710932400000-0", {"data": b"..."}],
            b"last-entry": ["1710932500000-0", {"data": b"..."}],
            b"groups": 2,
        }
        mock_redis_manager.return_value.get_client.return_value = mock_client

        from src.common.cache.redis_stream_publisher import RedisStreamPublisher

        publisher = RedisStreamPublisher()

        # Get stream info
        info = publisher.get_stream_info("AAPL", "trades")

        # Verify
        assert info["length"] == 100
        assert info["groups"] == 2
        mock_client.xinfo_stream.assert_called_once_with("stream:trades:AAPL")

    @patch("src.common.cache.redis_stream_publisher.RedisManager")
    @patch("src.common.cache.redis_stream_publisher.config")
    def test_trim_stream(self, mock_config, mock_redis_manager):
        """Test stream trimming."""
        # Setup mocks
        mock_config.get.return_value = {
            "trades_prefix": "stream:trades:",
            "bars_prefix": "stream:bars:",
            "retention_minutes": 5,
        }

        mock_client = MagicMock()
        mock_client.xtrim.return_value = 50
        mock_redis_manager.return_value.get_client.return_value = mock_client

        from src.common.cache.redis_stream_publisher import RedisStreamPublisher

        publisher = RedisStreamPublisher()

        # Trim with maxlen
        trimmed = publisher.trim_stream("AAPL", "trades", maxlen=100)

        assert trimmed == 50
        mock_client.xtrim.assert_called_once()

        # Check call arguments
        call_kwargs = mock_client.xtrim.call_args.kwargs
        assert call_kwargs["maxlen"] == 100
        assert call_kwargs["approximate"] is True

    @patch("src.common.cache.redis_stream_publisher.RedisManager")
    @patch("src.common.cache.redis_stream_publisher.config")
    def test_delete_stream(self, mock_config, mock_redis_manager):
        """Test stream deletion."""
        # Setup mocks
        mock_config.get.return_value = {
            "trades_prefix": "stream:trades:",
            "bars_prefix": "stream:bars:",
            "retention_minutes": 5,
        }

        mock_client = MagicMock()
        mock_client.delete.return_value = 1
        mock_redis_manager.return_value.get_client.return_value = mock_client

        from src.common.cache.redis_stream_publisher import RedisStreamPublisher

        publisher = RedisStreamPublisher()

        # Delete stream
        deleted = publisher.delete_stream("AAPL", "trades")

        assert deleted is True
        mock_client.delete.assert_called_once_with("stream:trades:AAPL")

    @patch("src.common.cache.redis_stream_publisher.RedisManager")
    @patch("src.common.cache.redis_stream_publisher.config")
    def test_publish_with_uppercase_symbol(self, mock_config, mock_redis_manager):
        """Test that symbols are uppercased automatically."""
        # Setup mocks
        mock_config.get.return_value = {
            "trades_prefix": "stream:trades:",
            "bars_prefix": "stream:bars:",
            "retention_minutes": 5,
        }

        mock_client = MagicMock()
        mock_client.xadd.return_value = b"1710932400000-0"
        mock_redis_manager.return_value.get_client.return_value = mock_client

        from src.common.cache.redis_stream_publisher import RedisStreamPublisher

        publisher = RedisStreamPublisher()

        # Publish with lowercase symbol
        trade_data = {"price": 150.25, "size": 100, "timestamp": "2024-03-20T10:30:00Z"}
        publisher.publish_trade("aapl", trade_data)

        # Verify uppercase in stream key
        call_kwargs = mock_client.xadd.call_args.kwargs
        assert call_kwargs["name"] == "stream:trades:AAPL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
