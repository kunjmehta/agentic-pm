"""Integration tests for DAO persistence in skills and stream handlers."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import asyncio
import os
from datetime import datetime, timedelta
import pandas as pd
from unittest.mock import patch, MagicMock
from src.common.dao import AlpacaDAO, AlphaVantageDAO


@pytest.fixture(scope="function")
def test_db_path(tmp_path):
    """Provide test database path for integration tests."""
    return str(tmp_path / "test_integration.duckdb")


@pytest.fixture(scope="function")
def alpaca_dao(test_db_path):
    """Create AlpacaDAO with test database and cleanup after."""
    dao = AlpacaDAO(db_path=test_db_path)
    yield dao
    # Clean up test data
    try:
        dao.execute("DELETE FROM market_bars WHERE symbol = 'TEST'")
        dao.execute("DELETE FROM historical_trades WHERE symbol = 'TEST'")
        dao.execute("DELETE FROM watchlist WHERE symbol LIKE 'TEST%'")
    except Exception:
        pass
    dao.close()


@pytest.fixture(scope="function")
def av_dao(test_db_path):
    """Create AlphaVantageDAO with test database and cleanup after."""
    dao = AlphaVantageDAO(db_path=test_db_path)
    yield dao
    # Clean up test data
    try:
        dao.execute("DELETE FROM fundamentals WHERE symbol = 'TEST'")
        dao.execute("DELETE FROM dividends WHERE symbol = 'TEST'")
        dao.execute("DELETE FROM earnings WHERE symbol = 'TEST'")
    except Exception:
        pass
    dao.close()


@pytest.fixture(scope="function", autouse=True)
def cleanup_test_db(test_db_path):
    """Clean up test database after each test."""
    yield
    # Cleanup handled by tmp_path fixture automatically


class TestAlpacaSkillsIntegration:
    """Integration tests for Alpaca skills with database persistence."""

    @patch('src.common.skills.alpaca_skills.historical_client')
    def test_fetch_historical_bars_saves_to_db(self, mock_client, alpaca_dao):
        """Test that fetch_historical_bars automatically saves to database."""
        from src.common.skills.alpaca_skills import fetch_historical_bars

        # Create mock response
        mock_bars_df = pd.DataFrame({
            'symbol': ['TEST'] * 3,
            'timestamp': pd.date_range('2024-01-01', periods=3, freq='1min'),
            'open': [100.0, 101.0, 102.0],
            'high': [100.5, 101.5, 102.5],
            'low': [99.5, 100.5, 101.5],
            'close': [100.3, 101.3, 102.3],
            'volume': [1000, 1100, 1200],
            'trade_count': [50, 55, 60],
            'vwap': [100.2, 101.2, 102.2]
        })

        mock_bars = MagicMock()
        mock_bars.df = mock_bars_df.set_index(['symbol', 'timestamp'])
        mock_client.get_stock_bars.return_value = mock_bars

        # Patch AlpacaDAO to use our test DAO
        with patch('src.common.skills.alpaca_skills.AlpacaDAO', return_value=alpaca_dao):
            # Fetch bars
            result = fetch_historical_bars(
                symbol="TEST",
                start="2024-01-01T00:00:00",
                end="2024-01-01T23:59:59",
                timeframe="1Min"
            )

            # Verify data was returned
            assert len(result) == 3

            # Verify data was saved to database
            start = datetime(2024, 1, 1, 0, 0, 0)
            end = datetime(2024, 1, 1, 23, 59, 59)
            saved_bars = alpaca_dao.get_bars("TEST", start, end, timeframe="1Min")

            assert len(saved_bars) == 3
            assert saved_bars.iloc[0]['open'] == 100.0

    @patch('src.common.skills.alpaca_skills.historical_client')
    def test_fetch_historical_trades_saves_to_db(self, mock_client, alpaca_dao):
        """Test that fetch_historical_trades automatically saves to database."""
        from src.common.skills.alpaca_skills import fetch_historical_trades

        # Create mock response
        mock_trades_df = pd.DataFrame({
            'symbol': ['TEST'] * 2,
            'timestamp': pd.date_range('2024-01-01', periods=2, freq='1s'),
            'id': [123, 124],
            'price': [100.5, 100.6],
            'size': [100, 150],
            'exchange': ['Q', 'Q'],
            'conditions': [['@'], ['@']],
            'tape': ['C', 'C']
        })

        mock_trades = MagicMock()
        mock_trades.df = mock_trades_df.set_index(['symbol', 'timestamp'])
        mock_client.get_stock_trades.return_value = mock_trades

        # Patch AlpacaDAO to use our test DAO
        with patch('src.common.skills.alpaca_skills.AlpacaDAO', return_value=alpaca_dao):
            # Fetch trades
            result = fetch_historical_trades(
                symbol="TEST",
                start="2024-01-01T00:00:00",
                end="2024-01-01T23:59:59",
                limit=10000
            )

            # Verify data was returned
            assert len(result) == 2

            # Verify data was saved to database
            start = datetime(2024, 1, 1, 0, 0, 0)
            end = datetime(2024, 1, 1, 23, 59, 59)
            saved_trades = alpaca_dao.get_trades("TEST", start, end)

            assert len(saved_trades) == 2
            assert saved_trades.iloc[0]['price'] == 100.5


class TestAlphaVantageSkillsIntegration:
    """Integration tests for Alpha Vantage skills with database persistence."""

    @patch('src.common.skills.alpha_vantage_skills._make_request')
    def test_fetch_company_overview_saves_to_db(self, mock_request, av_dao):
        """Test that fetch_company_overview automatically saves to database."""
        from src.common.skills.alpha_vantage_skills import fetch_company_overview

        # Mock API response
        mock_request.return_value = {
            'Symbol': 'TEST',
            'Name': 'Test Company',
            'Sector': 'Technology',
            'Industry': 'Software',
            'MarketCapitalization': '1000000000',
            'PERatio': '25.5'
        }

        # Patch AlphaVantageDAO to use our test DAO
        with patch('src.common.skills.alpha_vantage_skills.AlphaVantageDAO', return_value=av_dao):
            # Fetch overview
            result = fetch_company_overview("TEST")

            # Verify data was returned
            assert result['Name'] == 'Test Company'

            # Verify data was saved to database
            saved_overview = av_dao.get_company_overview("TEST")
            assert saved_overview is not None
            assert saved_overview['name'] == 'Test Company'

    @patch('src.common.skills.alpha_vantage_skills._make_request')
    def test_fetch_dividends_saves_to_db(self, mock_request, av_dao):
        """Test that fetch_dividend_history automatically saves to database."""
        from src.common.skills.alpha_vantage_skills import fetch_dividend_history

        # Mock API response
        mock_request.return_value = {
            'symbol': 'TEST',
            'data': [
                {
                    'ex_dividend_date': '2024-01-15',
                    'declaration_date': '2024-01-01',
                    'record_date': '2024-01-10',
                    'payment_date': '2024-01-20',
                    'amount': '0.50'
                }
            ]
        }

        # Patch AlphaVantageDAO to use our test DAO
        with patch('src.common.skills.alpha_vantage_skills.AlphaVantageDAO', return_value=av_dao):
            # Fetch dividends
            result = fetch_dividend_history("TEST")

            # Verify data was returned
            assert len(result) == 1
            assert result.iloc[0]['amount'] == 0.50

            # Verify data was saved to database
            saved_divs = av_dao.get_dividends("TEST")
            assert len(saved_divs) == 1
            assert saved_divs.iloc[0]['amount'] == 0.50


class TestStreamHandlersIntegration:
    """Integration tests for stream handlers with database persistence."""

    @pytest.mark.asyncio
    async def test_stream_handler_saves_to_db(self, alpaca_dao):
        """Test that stream handlers save data to database."""
        from src.common.data_gatherer.db_stream_handlers import save_trade_to_db, save_bar_to_db

        # Mock trade
        class MockTrade:
            symbol = "TEST"
            timestamp = datetime.now()
            id = 999
            price = 150.0
            size = 100
            exchange = "Q"
            conditions = ["@"]
            tape = "C"

        # Mock bar
        class MockBar:
            symbol = "TEST"
            timestamp = datetime.now()
            open = 150.0
            high = 151.0
            low = 149.0
            close = 150.5
            volume = 10000
            trade_count = 50
            vwap = 150.3

        # Patch the DAO
        import src.common.data_gatherer.db_stream_handlers as handlers
        handlers._dao = alpaca_dao

        # Save trade
        await save_trade_to_db(MockTrade())

        # Save bar
        await save_bar_to_db(MockBar(), timeframe='1Min')

        # Verify data was saved
        start = datetime.now().replace(hour=0, minute=0, second=0)
        end = datetime.now().replace(hour=23, minute=59, second=59)

        trades = alpaca_dao.get_trades("TEST", start, end)
        bars = alpaca_dao.get_bars("TEST", start, end, timeframe='1Min')

        assert trades is not None, "get_trades returned None"
        assert bars is not None, "get_bars returned None"
        assert len(trades) >= 1
        assert len(bars) >= 1


class TestDataIntegrity:
    """Test data integrity across the system."""

    def test_upsert_prevents_duplicates(self, alpaca_dao):
        """Test that upserting data prevents duplicates."""
        # Create test data with fixed timestamp (no microseconds)
        fixed_timestamp = datetime(2024, 1, 1, 10, 30, 0)
        test_data = pd.DataFrame({
            'symbol': ['TEST'],
            'timestamp': [fixed_timestamp],
            'open': [100.0],
            'high': [101.0],
            'low': [99.0],
            'close': [100.5],
            'volume': [1000]
        })

        # Insert twice with same data
        alpaca_dao.save_bars(test_data.copy(), timeframe='1Min')
        alpaca_dao.save_bars(test_data.copy(), timeframe='1Min')

        # Verify only one record exists (upsert should prevent duplicates)
        start = fixed_timestamp.replace(hour=0, minute=0, second=0)
        end = fixed_timestamp.replace(hour=23, minute=59, second=59)
        bars = alpaca_dao.get_bars("TEST", start, end, timeframe='1Min')

        assert len(bars) == 1, f"Expected 1 record but got {len(bars)}"

    def test_watchlist_integration(self, alpaca_dao):
        """Test watchlist operations."""
        # Add symbols
        alpaca_dao.add_to_watchlist("TEST1", notes="Test symbol 1")
        alpaca_dao.add_to_watchlist("TEST2", notes="Test symbol 2")

        # Get watchlist
        watchlist = alpaca_dao.get_watchlist()

        assert "TEST1" in watchlist
        assert "TEST2" in watchlist

        # Check if in watchlist
        assert alpaca_dao.is_in_watchlist("TEST1")

        # Remove from watchlist
        alpaca_dao.remove_from_watchlist("TEST1")
        watchlist = alpaca_dao.get_watchlist()

        assert "TEST1" not in watchlist
        assert "TEST2" in watchlist
