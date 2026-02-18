"""Unit tests for Alpaca API skills.

These tests use mocking to avoid hitting the actual Alpaca API.
For integration testing with real API, see test_alpaca_integration.py
"""

import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path
import json
import sys


# Mock secrets before importing the module
mock_secrets_data = {
    "alpaca": {
        "api_key": "test_api_key",
        "secret_key": "test_secret_key",
        "base_url": "https://paper-api.alpaca.markets"
    },
    "alpha_vantage": {
        "api_key": "test_alpha_key"
    }
}


@pytest.fixture(scope="session", autouse=True)
def mock_secret_file():
    """Mock secret.json file for all tests."""
    with patch("pathlib.Path.exists") as mock_exists:
        mock_exists.return_value = True
        with patch("builtins.open", create=True) as mock_open:
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = json.dumps(mock_secrets_data)
            mock_open.return_value = mock_file

            # Now import the module after mocking
            import src.skills.alpaca_skills
            yield


class TestFetchHistoricalBars:
    """Test fetch_historical_bars function."""

    @patch("src.skills.alpaca_skills.historical_client")
    def test_fetch_bars_success(self, mock_client):
        """Test successful bar data fetch."""
        from src.skills.alpaca_skills import fetch_historical_bars

        # Mock response
        mock_bars = Mock()
        mock_bars.df = pd.DataFrame({
            "symbol": ["AAPL", "AAPL"],
            "timestamp": [datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 11, 0)],
            "open": [150.0, 151.0],
            "high": [152.0, 153.0],
            "low": [149.0, 150.0],
            "close": [151.0, 152.0],
            "volume": [1000, 1500],
        }).set_index(["symbol", "timestamp"])

        mock_client.get_stock_bars.return_value = mock_bars

        # Execute
        result = fetch_historical_bars(
            symbol="AAPL",
            start="2024-01-01",
            end="2024-01-02",
            timeframe="1Hour"
        )

        # Assert
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert "open" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns
        mock_client.get_stock_bars.assert_called_once()

    @patch("src.skills.alpaca_skills.historical_client")
    def test_fetch_bars_invalid_timeframe(self, mock_client):
        """Test error handling for invalid timeframe."""
        from src.skills.alpaca_skills import fetch_historical_bars

        with pytest.raises(ValueError, match="Invalid timeframe"):
            fetch_historical_bars(
                symbol="AAPL",
                start="2024-01-01",
                end="2024-01-02",
                timeframe="InvalidTimeframe"
            )

    @patch("src.skills.alpaca_skills.historical_client")
    def test_fetch_bars_api_error(self, mock_client):
        """Test error handling when API fails."""
        from src.skills.alpaca_skills import fetch_historical_bars

        mock_client.get_stock_bars.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="Failed to fetch historical bars"):
            fetch_historical_bars(
                symbol="AAPL",
                start="2024-01-01",
                end="2024-01-02",
                timeframe="1Min"
            )


class TestFetchHistoricalTrades:
    """Test fetch_historical_trades function."""

    @patch("src.skills.alpaca_skills.historical_client")
    def test_fetch_trades_success(self, mock_client):
        """Test successful trade data fetch."""
        from src.skills.alpaca_skills import fetch_historical_trades

        # Mock response
        mock_trades = Mock()
        mock_trades.df = pd.DataFrame({
            "symbol": ["AAPL", "AAPL", "AAPL"],
            "timestamp": [
                datetime(2024, 1, 1, 10, 0, 0),
                datetime(2024, 1, 1, 10, 0, 5),
                datetime(2024, 1, 1, 10, 0, 10),
            ],
            "price": [150.0, 150.5, 151.0],
            "size": [100, 200, 150],
            "exchange": ["NYSE", "NYSE", "NASDAQ"],
        }).set_index(["symbol", "timestamp"])

        mock_client.get_stock_trades.return_value = mock_trades

        # Execute
        result = fetch_historical_trades(
            symbol="AAPL",
            start="2024-01-01",
            end="2024-01-02",
            limit=100
        )

        # Assert
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert "price" in result.columns
        assert "size" in result.columns
        mock_client.get_stock_trades.assert_called_once()

    @patch("src.skills.alpaca_skills.historical_client")
    def test_fetch_trades_api_error(self, mock_client):
        """Test error handling when API fails."""
        from src.skills.alpaca_skills import fetch_historical_trades

        mock_client.get_stock_trades.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="Failed to fetch historical trades"):
            fetch_historical_trades(
                symbol="AAPL",
                start="2024-01-01",
                end="2024-01-02"
            )


class TestSubscribeToBars:
    """Test subscribe_to_bars WebSocket function."""

    @pytest.mark.asyncio
    @patch("src.skills.alpaca_skills.StockDataStream")
    async def test_subscribe_success(self, mock_stream_class):
        """Test successful WebSocket subscription."""
        from src.skills.alpaca_skills import subscribe_to_bars

        # Mock stream instance
        mock_stream = AsyncMock()
        mock_stream_class.return_value = mock_stream
        mock_stream.run = AsyncMock()

        # Callback function
        received_data = []

        def callback(data):
            received_data.append(data)

        # Execute (cancel after a short delay to avoid hanging)
        import asyncio
        task = asyncio.create_task(
            subscribe_to_bars("AAPL", callback)
        )
        await asyncio.sleep(0.1)  # Let it start
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass  # Expected

        # Assert
        mock_stream.subscribe_bars.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.skills.alpaca_skills.StockDataStream")
    async def test_subscribe_error(self, mock_stream_class):
        """Test error handling in WebSocket subscription."""
        from src.skills.alpaca_skills import subscribe_to_bars

        mock_stream_class.side_effect = Exception("Connection failed")

        def callback(data):
            pass

        with pytest.raises(Exception, match="Failed to subscribe to bars"):
            await subscribe_to_bars("AAPL", callback)


if __name__ == "__main__":
    """Run tests with pytest."""
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
