"""Tests for AlpacaDataStreamer threading behavior."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import threading
from unittest.mock import patch, MagicMock
from src.data_gatherer.alpaca_stream import AlpacaDataStreamer


class TestSignalHandlerSetup:
    """Test signal handler setup in different thread contexts."""

    @patch('src.data_gatherer.alpaca_stream.StockDataStream')
    def test_signal_handler_setup_in_main_thread(self, mock_stream):
        """Test that signal handlers are set up when in main thread."""
        # This test runs in main thread by default
        streamer = AlpacaDataStreamer(symbol="AAPL")

        # Mock the signal.signal to avoid actual signal registration
        with patch('src.data_gatherer.alpaca_stream.signal.signal') as mock_signal:
            streamer._setup_signal_handlers()

            # Should call signal.signal twice (SIGINT and SIGTERM)
            assert mock_signal.call_count == 2

    @patch('src.data_gatherer.alpaca_stream.StockDataStream')
    def test_signal_handler_skipped_in_background_thread(self, mock_stream):
        """Test that signal handlers are skipped when not in main thread."""
        # This test runs in main thread, but we'll mock threading.current_thread()
        streamer = AlpacaDataStreamer(symbol="AAPL")

        # Create a mock thread that is NOT the main thread
        mock_thread = MagicMock()
        mock_main_thread = MagicMock()

        with patch('src.data_gatherer.alpaca_stream.threading.current_thread', return_value=mock_thread):
            with patch('src.data_gatherer.alpaca_stream.threading.main_thread', return_value=mock_main_thread):
                with patch('src.data_gatherer.alpaca_stream.signal.signal') as mock_signal:
                    streamer._setup_signal_handlers()

                    # Should NOT call signal.signal (skipped because not in main thread)
                    assert mock_signal.call_count == 0

    @patch('src.data_gatherer.alpaca_stream.StockDataStream')
    def test_streamer_initialization(self, mock_stream):
        """Test basic streamer initialization."""
        streamer = AlpacaDataStreamer(symbol="AAPL")

        assert streamer.symbol == "AAPL"
        assert streamer.running is False
        assert streamer._shutdown_requested is False
        assert streamer._trade_handler is None
        assert streamer._bar_handler is None
        assert streamer._status_handler is None

    @patch('src.data_gatherer.alpaca_stream.StockDataStream')
    def test_subscribe_handlers(self, mock_stream):
        """Test subscribing to different data types."""
        streamer = AlpacaDataStreamer(symbol="AAPL")

        async def mock_handler(data):
            pass

        # Subscribe to trades
        streamer.subscribe_trades(mock_handler)
        assert streamer._trade_handler == mock_handler

        # Subscribe to bars
        streamer.subscribe_bars(mock_handler)
        assert streamer._bar_handler == mock_handler

        # Subscribe to statuses
        streamer.subscribe_statuses(mock_handler)
        assert streamer._status_handler == mock_handler

    @patch('src.data_gatherer.alpaca_stream.StockDataStream')
    def test_unsubscribe_handlers(self, mock_stream):
        """Test unsubscribing from data types."""
        streamer = AlpacaDataStreamer(symbol="AAPL")

        async def mock_handler(data):
            pass

        # Subscribe then unsubscribe trades
        streamer.subscribe_trades(mock_handler)
        streamer.unsubscribe_trades()
        assert streamer._trade_handler is None

        # Subscribe then unsubscribe bars
        streamer.subscribe_bars(mock_handler)
        streamer.unsubscribe_bars()
        assert streamer._bar_handler is None

        # Subscribe then unsubscribe statuses
        streamer.subscribe_statuses(mock_handler)
        streamer.unsubscribe_statuses()
        assert streamer._status_handler is None
