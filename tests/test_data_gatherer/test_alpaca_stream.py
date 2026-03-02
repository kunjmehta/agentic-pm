"""Unit tests for Alpaca Data Streamer (SDK-based).

Tests the AlpacaDataStreamer class using alpaca-py SDK.
Run with: pytest tests/test_data_gatherer/test_alpaca_stream.py -v
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import Mock, patch
from alpaca.data.enums import DataFeed
from src.data_gatherer.alpaca_stream import AlpacaDataStreamer


class TestAlpacaDataStreamer:
    """Test suite for AlpacaDataStreamer class."""

    def test_init_with_credentials(self):
        """Test initialization with explicit credentials and defaults."""
        streamer = AlpacaDataStreamer(
            symbol="aapl",  # Test lowercase conversion
            api_key="test_key",
            secret_key="test_secret"
        )

        assert streamer.symbol == "AAPL"
        assert streamer.api_key == "test_key"
        assert streamer.secret_key == "test_secret"
        assert streamer.feed == DataFeed.IEX
        assert streamer.max_retries == 3
        assert streamer.retry_delay == 5

    def test_init_custom_retries(self):
        """Test custom retry configuration."""
        streamer = AlpacaDataStreamer(
            symbol="AAPL",
            api_key="key",
            secret_key="secret",
            max_retries=5,
            retry_delay=10
        )

        assert streamer.max_retries == 5
        assert streamer.retry_delay == 10

    def test_subscribe_trades(self):
        """Test subscribing to trades."""
        streamer = AlpacaDataStreamer(
            symbol="AAPL",
            api_key="key",
            secret_key="secret"
        )

        async def mock_handler(trade):
            pass

        with patch.object(streamer.stream, 'subscribe_trades') as mock_subscribe:
            streamer.subscribe_trades(mock_handler)

            mock_subscribe.assert_called_once_with(mock_handler, "AAPL")
            assert streamer._trade_handler == mock_handler

    def test_subscribe_bars(self):
        """Test subscribing to bars."""
        streamer = AlpacaDataStreamer(
            symbol="AAPL",
            api_key="key",
            secret_key="secret"
        )

        async def mock_handler(bar):
            pass

        with patch.object(streamer.stream, 'subscribe_bars') as mock_subscribe:
            streamer.subscribe_bars(mock_handler)

            mock_subscribe.assert_called_once_with(mock_handler, "AAPL")
            assert streamer._bar_handler == mock_handler

    def test_subscribe_statuses(self):
        """Test subscribing to trading statuses."""
        streamer = AlpacaDataStreamer(
            symbol="AAPL",
            api_key="key",
            secret_key="secret"
        )

        async def mock_handler(status):
            pass

        with patch.object(streamer.stream, 'subscribe_trading_statuses') as mock_subscribe:
            streamer.subscribe_statuses(mock_handler)

            mock_subscribe.assert_called_once_with(mock_handler, "AAPL")
            assert streamer._status_handler == mock_handler

    def test_stop(self):
        """Test graceful stop."""
        streamer = AlpacaDataStreamer(
            symbol="AAPL",
            api_key="key",
            secret_key="secret"
        )

        streamer.running = True

        with patch.object(streamer.stream, 'stop') as mock_stop:
            streamer.stop()

            assert streamer.running is False
            mock_stop.assert_called_once()

    def test_stop_with_error(self):
        """Test stop handles errors gracefully."""
        streamer = AlpacaDataStreamer(
            symbol="AAPL",
            api_key="key",
            secret_key="secret"
        )

        streamer.running = True

        with patch.object(streamer.stream, 'stop', side_effect=Exception("Stop error")):
            # Should not raise, just print error
            streamer.stop()

            assert streamer.running is False


class TestDefaultHandlers:
    """Test default handlers."""

    @pytest.mark.asyncio
    async def test_default_trade_handler(self):
        """Test default trade handler doesn't raise."""
        from src.data_gatherer.alpaca_stream import default_trade_handler

        # Mock trade object
        mock_trade = Mock()
        mock_trade.symbol = "AAPL"
        mock_trade.price = 182.52
        mock_trade.size = 100
        mock_trade.exchange = "NASDAQ"
        mock_trade.timestamp = "2024-02-17T14:30:00Z"

        # Should not raise
        await default_trade_handler(mock_trade)

    @pytest.mark.asyncio
    async def test_default_bar_handler(self):
        """Test default bar handler doesn't raise."""
        from src.data_gatherer.alpaca_stream import default_bar_handler

        # Mock bar object
        mock_bar = Mock()
        mock_bar.symbol = "AAPL"
        mock_bar.open = 181.0
        mock_bar.high = 183.0
        mock_bar.low = 180.0
        mock_bar.close = 182.0
        mock_bar.volume = 1000000
        mock_bar.timestamp = "2024-02-17"

        # Should not raise
        await default_bar_handler(mock_bar)

    @pytest.mark.asyncio
    async def test_default_status_handler(self):
        """Test default status handler doesn't raise."""
        from src.data_gatherer.alpaca_stream import default_status_handler

        # Mock status object
        mock_status = Mock()
        mock_status.symbol = "AAPL"
        mock_status.status_code = "H"
        mock_status.status_message = "Halted"
        mock_status.timestamp = "2024-02-17T14:30:00Z"

        # Should not raise
        await default_status_handler(mock_status)


if __name__ == "__main__":
    """Run tests with pytest."""
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
