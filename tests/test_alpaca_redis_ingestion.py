"""Unit tests for Alpaca Redis Ingestion service.

Tests the AlpacaRedisIngestion class that subscribes to Alpaca WebSocket
and publishes data to Redis Streams.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestAlpacaRedisIngestion:
    """Test suite for AlpacaRedisIngestion."""

    @patch("src.ingestion.alpaca_redis_ingestion.RedisStreamPublisher")
    @patch("src.ingestion.alpaca_redis_ingestion.secrets")
    @patch("src.ingestion.alpaca_redis_ingestion.config")
    def test_initialization(self, mock_config, mock_secrets, mock_publisher_class):
        """Test service initialization with mocked dependencies."""
        from src.ingestion.alpaca_redis_ingestion import AlpacaRedisIngestion

        # Mock configuration
        mock_config.get.return_value = {
            "AAPL": {"enabled": True},
            "TSLA": {"enabled": False},
            "MSFT": {"enabled": True},
        }
        mock_secrets.get.side_effect = lambda key: {
            "alpaca.api_key": "test_api_key",
            "alpaca.secret_key": "test_secret_key",
        }[key]

        # Create service
        service = AlpacaRedisIngestion()

        # Verify initialization
        assert service.api_key == "test_api_key"
        assert service.secret_key == "test_secret_key"
        assert "AAPL" in service.symbols
        assert "MSFT" in service.symbols
        assert "TSLA" not in service.symbols  # disabled
        assert service.running is False
        assert service._shutdown_requested is False

    @patch("src.ingestion.alpaca_redis_ingestion.RedisStreamPublisher")
    @patch("src.ingestion.alpaca_redis_ingestion.secrets")
    @patch("src.ingestion.alpaca_redis_ingestion.config")
    def test_load_watchlist_symbols(self, mock_config, mock_secrets, mock_publisher_class):
        """Test watchlist symbol loading from config."""
        from src.ingestion.alpaca_redis_ingestion import AlpacaRedisIngestion

        # Mock configuration
        mock_config.get.return_value = {
            "AAPL": {"enabled": True, "strategies": ["mean_reversion"]},
            "TSLA": {"enabled": True, "strategies": ["momentum_burst"]},
            "GOOGL": {"enabled": False, "strategies": []},
        }
        mock_secrets.get.side_effect = lambda key: {
            "alpaca.api_key": "key",
            "alpaca.secret_key": "secret",
        }[key]

        service = AlpacaRedisIngestion()

        assert len(service.symbols) == 2
        assert "AAPL" in service.symbols
        assert "TSLA" in service.symbols
        assert "GOOGL" not in service.symbols

    @patch("src.ingestion.alpaca_redis_ingestion.RedisStreamPublisher")
    @patch("src.ingestion.alpaca_redis_ingestion.secrets")
    @patch("src.ingestion.alpaca_redis_ingestion.config")
    def test_exponential_backoff_calculation(
        self, mock_config, mock_secrets, mock_publisher_class
    ):
        """Test exponential backoff delay calculation."""
        from src.ingestion.alpaca_redis_ingestion import AlpacaRedisIngestion

        # Mock dependencies
        mock_config.get.return_value = {"AAPL": {"enabled": True}}
        mock_secrets.get.side_effect = lambda key: {
            "alpaca.api_key": "key",
            "alpaca.secret_key": "secret",
        }[key]

        service = AlpacaRedisIngestion(base_retry_delay=2, max_retry_delay=60)

        # Test exponential backoff: base_delay * 2^retry_count
        assert service._calculate_retry_delay(0) == 2  # 2 * 2^0 = 2
        assert service._calculate_retry_delay(1) == 4  # 2 * 2^1 = 4
        assert service._calculate_retry_delay(2) == 8  # 2 * 2^2 = 8
        assert service._calculate_retry_delay(3) == 16  # 2 * 2^3 = 16
        assert service._calculate_retry_delay(4) == 32  # 2 * 2^4 = 32
        assert service._calculate_retry_delay(5) == 60  # capped at max_delay
        assert service._calculate_retry_delay(10) == 60  # still capped

    @pytest.mark.asyncio
    @patch("src.ingestion.alpaca_redis_ingestion.RedisStreamPublisher")
    @patch("src.ingestion.alpaca_redis_ingestion.secrets")
    @patch("src.ingestion.alpaca_redis_ingestion.config")
    async def test_on_trade_handler(self, mock_config, mock_secrets, mock_publisher_class):
        """Test trade data handler converts and publishes correctly."""
        from src.ingestion.alpaca_redis_ingestion import AlpacaRedisIngestion

        # Mock dependencies
        mock_config.get.return_value = {"AAPL": {"enabled": True}}
        mock_secrets.get.side_effect = lambda key: {
            "alpaca.api_key": "key",
            "alpaca.secret_key": "secret",
        }[key]

        # Mock publisher instance
        mock_publisher = MagicMock()
        mock_publisher.publish_trade.return_value = "test-entry-id-123"
        mock_publisher_class.return_value = mock_publisher

        service = AlpacaRedisIngestion()

        # Create mock trade object
        mock_trade = MagicMock()
        mock_trade.symbol = "AAPL"
        mock_trade.price = 150.25
        mock_trade.size = 100
        mock_trade.timestamp.isoformat.return_value = "2024-03-20T10:30:00Z"
        mock_trade.conditions = ["@", "F"]
        mock_trade.exchange = "Q"
        mock_trade.id = 12345
        mock_trade.tape = "C"

        # Call handler
        await service._on_trade(mock_trade)

        # Verify publish_trade was called with correct data
        mock_publisher.publish_trade.assert_called_once()
        call_args = mock_publisher.publish_trade.call_args
        assert call_args[0][0] == "AAPL"  # symbol
        trade_data = call_args[0][1]  # trade_data dict
        assert trade_data["price"] == 150.25
        assert trade_data["size"] == 100
        assert trade_data["timestamp"] == "2024-03-20T10:30:00Z"
        assert trade_data["conditions"] == ["@", "F"]
        assert trade_data["exchange"] == "Q"

    @pytest.mark.asyncio
    @patch("src.ingestion.alpaca_redis_ingestion.RedisStreamPublisher")
    @patch("src.ingestion.alpaca_redis_ingestion.secrets")
    @patch("src.ingestion.alpaca_redis_ingestion.config")
    async def test_on_bar_handler(self, mock_config, mock_secrets, mock_publisher_class):
        """Test bar data handler converts and publishes correctly."""
        from src.ingestion.alpaca_redis_ingestion import AlpacaRedisIngestion

        # Mock dependencies
        mock_config.get.return_value = {"AAPL": {"enabled": True}}
        mock_secrets.get.side_effect = lambda key: {
            "alpaca.api_key": "key",
            "alpaca.secret_key": "secret",
        }[key]

        # Mock publisher instance
        mock_publisher = MagicMock()
        mock_publisher.publish_bar.return_value = "test-entry-id-456"
        mock_publisher_class.return_value = mock_publisher

        service = AlpacaRedisIngestion()

        # Create mock bar object
        mock_bar = MagicMock()
        mock_bar.symbol = "AAPL"
        mock_bar.timestamp.isoformat.return_value = "2024-03-20T10:30:00Z"
        mock_bar.open = 150.00
        mock_bar.high = 150.50
        mock_bar.low = 149.75
        mock_bar.close = 150.25
        mock_bar.volume = 1000000
        mock_bar.vwap = 150.15
        mock_bar.trade_count = 1523

        # Call handler
        await service._on_bar(mock_bar)

        # Verify publish_bar was called with correct data
        mock_publisher.publish_bar.assert_called_once()
        call_args = mock_publisher.publish_bar.call_args
        assert call_args[0][0] == "AAPL"  # symbol
        bar_data = call_args[0][1]  # bar_data dict
        assert bar_data["open"] == 150.00
        assert bar_data["high"] == 150.50
        assert bar_data["low"] == 149.75
        assert bar_data["close"] == 150.25
        assert bar_data["volume"] == 1000000
        assert bar_data["vwap"] == 150.15

    @patch("src.ingestion.alpaca_redis_ingestion.RedisStreamPublisher")
    @patch("src.ingestion.alpaca_redis_ingestion.secrets")
    @patch("src.ingestion.alpaca_redis_ingestion.config")
    def test_get_status(self, mock_config, mock_secrets, mock_publisher_class):
        """Test status reporting."""
        from src.ingestion.alpaca_redis_ingestion import AlpacaRedisIngestion

        # Mock dependencies
        mock_config.get.return_value = {"AAPL": {"enabled": True}}
        mock_secrets.get.side_effect = lambda key: {
            "alpaca.api_key": "key",
            "alpaca.secret_key": "secret",
        }[key]

        service = AlpacaRedisIngestion()
        status = service.get_status()

        assert "running" in status
        assert "symbols" in status
        assert "feed" in status
        assert "shutdown_requested" in status
        assert status["running"] is False
        assert "AAPL" in status["symbols"]
        assert status["feed"] == "iex"


if __name__ == "__main__":
    """Run tests with pytest."""
    pytest.main([__file__, "-v", "--tb=short"])
