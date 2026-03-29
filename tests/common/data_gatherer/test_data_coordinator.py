# """Tests for DataCoordinator."""

# import sys
# from pathlib import Path
# project_root = Path(__file__).parent.parent.parent.parent
# sys.path.insert(0, str(project_root))

# import pytest
# import asyncio
# from unittest.mock import patch, MagicMock, AsyncMock
# from src.common.data_gatherer.data_coordinator import DataCoordinator


# class TestDataCoordinatorInit:
#     """Test DataCoordinator initialization."""

#     def test_init_with_symbols(self):
#         """Test initialization with provided symbols."""
#         coordinator = DataCoordinator(symbols=["AAPL", "MSFT", "GOOGL"])

#         assert coordinator.symbols == ["AAPL", "MSFT", "GOOGL"]
#         assert len(coordinator.streamers) == 0
#         assert len(coordinator.stream_tasks) == 0

#     def test_init_with_lowercase_symbols(self):
#         """Test that symbols are converted to uppercase."""
#         coordinator = DataCoordinator(symbols=["aapl", "msft"])

#         assert coordinator.symbols == ["AAPL", "MSFT"]

#     @patch('src.data_gatherer.data_coordinator.config')
#     def test_init_from_config(self, mock_config):
#         """Test initialization from config watchlist."""
#         mock_config.get.return_value = ["IBM", "TSLA"]

#         coordinator = DataCoordinator()

#         mock_config.get.assert_called_once_with("watchlist", default=["AAPL"])
#         assert coordinator.symbols == ["IBM", "TSLA"]


# class TestDataCoordinatorMethods:
#     """Test DataCoordinator methods."""

#     @pytest.mark.asyncio
#     @patch('src.data_gatherer.data_coordinator.AlpacaDataStreamer')
#     @patch('src.data_gatherer.data_coordinator.default_trade_handler')
#     @patch('src.data_gatherer.data_coordinator.default_bar_handler')
#     async def test_start_streaming(self, mock_bar_handler, mock_trade_handler, mock_streamer_class):
#         """Test starting streaming for a symbol."""
#         # Setup mock
#         mock_streamer = MagicMock()
#         mock_streamer_class.return_value = mock_streamer

#         coordinator = DataCoordinator(symbols=["TEST"])

#         # Start streaming
#         await coordinator.start_streaming("TEST")

#         # Verify streamer was created and configured
#         mock_streamer_class.assert_called_once_with(symbol="TEST")
#         mock_streamer.subscribe_trades.assert_called_once()
#         mock_streamer.subscribe_bars.assert_called_once()

#         # Verify streamer was stored
#         assert "TEST" in coordinator.streamers
#         assert coordinator.streamers["TEST"] == mock_streamer

#         # Verify task was created and stored
#         assert len(coordinator.stream_tasks) == 1

#     def test_stop_all_streaming(self):
#         """Test stopping all active streams."""
#         coordinator = DataCoordinator(symbols=["TEST"])

#         # Add mock streamer
#         mock_streamer = MagicMock()
#         coordinator.streamers["TEST"] = mock_streamer

#         # Stop all streaming
#         coordinator.stop_all_streaming()

#         # Verify stop was called
#         mock_streamer.stop.assert_called_once()

#     @pytest.mark.asyncio
#     async def test_run_streaming_loop_exits_on_shutdown(self):
#         """Test that streaming loop exits when shutdown is requested."""
#         coordinator = DataCoordinator(symbols=["TEST"])

#         # Create shutdown flag
#         shutdown_flag = [False]

#         # Start streaming loop in background
#         loop_task = asyncio.create_task(coordinator.run_streaming_loop(shutdown_flag))

#         # Let it run briefly
#         await asyncio.sleep(0.1)

#         # Request shutdown
#         shutdown_flag[0] = True

#         # Wait for loop to exit
#         await asyncio.wait_for(loop_task, timeout=2.0)

#         # Loop should have exited cleanly
#         assert loop_task.done()
#         assert not loop_task.cancelled()

#     @pytest.mark.asyncio
#     async def test_run_streaming_loop_detects_failed_tasks(self):
#         """Test that streaming loop detects and logs failed tasks."""
#         coordinator = DataCoordinator(symbols=["TEST"])

#         # Create a failed task
#         async def failing_task():
#             raise ValueError("Test error")

#         failed_task = asyncio.create_task(failing_task())
#         coordinator.stream_tasks.append(failed_task)

#         # Wait for task to fail
#         await asyncio.sleep(0.1)

#         # Create shutdown flag
#         shutdown_flag = [False]

#         # Run loop briefly
#         loop_task = asyncio.create_task(coordinator.run_streaming_loop(shutdown_flag))
#         await asyncio.sleep(0.2)

#         # Stop loop
#         shutdown_flag[0] = True
#         await loop_task

#         # Failed task should be detected (logged in run_streaming_loop)
#         assert failed_task.done()
#         assert failed_task.exception() is not None


# class TestDataCoordinatorIntegration:
#     """Integration tests for DataCoordinator."""

#     @pytest.mark.asyncio
#     @patch('src.data_gatherer.data_coordinator.fetch_historical_bars')
#     @patch('src.data_gatherer.data_coordinator.fetch_historical_trades')
#     async def test_fetch_historical_market_data(self, mock_trades, mock_bars):
#         """Test fetching historical market data."""
#         # Setup mocks to return empty DataFrames
#         import pandas as pd
#         mock_bars.return_value = pd.DataFrame()
#         mock_trades.return_value = pd.DataFrame()

#         coordinator = DataCoordinator(symbols=["TEST"])

#         # Should not raise exception
#         coordinator.fetch_historical_market_data("TEST", days_back=1)

#         # Verify all data types were fetched
#         assert mock_bars.call_count == 2  # Daily and 1-minute (hourly was removed)
#         assert mock_trades.call_count == 1

#     @pytest.mark.asyncio
#     @patch('src.data_gatherer.data_coordinator.fetch_company_overview')
#     @patch('src.data_gatherer.data_coordinator.fetch_dividend_history')
#     @patch('src.data_gatherer.data_coordinator.fetch_earnings_history')
#     @patch('src.data_gatherer.data_coordinator.fetch_income_statement')
#     @patch('src.data_gatherer.data_coordinator.fetch_balance_sheet')
#     @patch('src.data_gatherer.data_coordinator.fetch_cash_flow')
#     async def test_fetch_all_fundamentals(
#         self, mock_cash, mock_balance, mock_income,
#         mock_earnings, mock_div, mock_overview
#     ):
#         """Test fetching all fundamental data."""
#         # Setup mocks
#         import pandas as pd
#         mock_overview.return_value = {"Name": "Test Corp"}
#         mock_div.return_value = pd.DataFrame()
#         mock_earnings.return_value = pd.DataFrame()
#         mock_income.return_value = pd.DataFrame()
#         mock_balance.return_value = pd.DataFrame()
#         mock_cash.return_value = pd.DataFrame()

#         coordinator = DataCoordinator(symbols=["TEST"])

#         # Should not raise exception
#         coordinator.fetch_all_fundamentals("TEST")

#         # Verify all fundamental data was fetched
#         mock_overview.assert_called_once()
#         mock_div.assert_called_once()
#         # Earnings called once for annual (quarterly removed)
#         assert mock_earnings.call_count == 1
#         # Income, balance, cash called once each for annual
#         assert mock_income.call_count == 1
#         assert mock_balance.call_count == 1
#         assert mock_cash.call_count == 1
