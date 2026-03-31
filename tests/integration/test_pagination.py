"""Integration tests for API pagination.

Tests that pagination correctly fetches all data across multiple pages.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
from datetime import datetime, timedelta

# Note: These tests use mocking since they depend on external Alpaca API


class TestPagination:
    """Integration tests for pagination functionality."""

    # ========================================================================
    # fetch_historical_bars Pagination Tests
    # ========================================================================

    @patch('src.skills.alpaca_skills.historical_client')
    def test_fetch_bars_single_chunk(self, mock_client):
        """Test fetching bars within one chunk (no pagination needed)."""
        from src.skills.alpaca_skills import fetch_historical_bars

        # Mock response
        mock_bars = Mock()
        mock_df = pd.DataFrame({
            'symbol': ['AAPL'] * 10,
            'timestamp': pd.date_range('2024-01-01', periods=10, freq='D'),
            'open': [150.0] * 10,
            'high': [152.0] * 10,
            'low': [149.0] * 10,
            'close': [151.0] * 10,
            'volume': [1000000] * 10
        })
        mock_bars.df = mock_df.set_index(['symbol', 'timestamp'])
        mock_client.get_stock_bars.return_value = mock_bars

        # Fetch bars (5 days should be single chunk)
        result = fetch_historical_bars(
            'AAPL',
            '2024-01-01',
            '2024-01-05',
            timeframe='1Day',
            chunk_days=7
        )

        # Should return data
        assert not result.empty
        assert len(result) == 10

        # Should call API once
        assert mock_client.get_stock_bars.call_count == 1

    @patch('src.skills.alpaca_skills.historical_client')
    @patch('src.skills.alpaca_skills.AlpacaDAO')
    def test_fetch_bars_multiple_chunks(self, mock_dao_class, mock_client):
        """Test fetching bars across multiple chunks."""
        from src.skills.alpaca_skills import fetch_historical_bars

        # Mock DAO
        mock_dao = Mock()
        mock_dao.save_bars.return_value = 10
        mock_dao_class.return_value = mock_dao

        # Mock API to return data for each chunk
        def get_bars_side_effect(*args, **kwargs):
            mock_bars = Mock()
            mock_df = pd.DataFrame({
                'symbol': ['AAPL'] * 5,
                'timestamp': pd.date_range('2024-01-01', periods=5, freq='D'),
                'open': [150.0] * 5,
                'high': [152.0] * 5,
                'low': [149.0] * 5,
                'close': [151.0] * 5,
                'volume': [1000000] * 5
            })
            mock_bars.df = mock_df.set_index(['symbol', 'timestamp'])
            return mock_bars

        mock_client.get_stock_bars.side_effect = get_bars_side_effect

        # Fetch 20 days with 7-day chunks (should need 3 chunks)
        result = fetch_historical_bars(
            'AAPL',
            '2024-01-01',
            '2024-01-20',
            timeframe='1Day',
            chunk_days=7
        )

        # Should call API multiple times (3 chunks)
        assert mock_client.get_stock_bars.call_count == 3

    @patch('src.skills.alpaca_skills.historical_client')
    @patch('src.skills.alpaca_skills.AlpacaDAO')
    def test_fetch_bars_batch_insert(self, mock_dao_class, mock_client):
        """Test that large datasets are inserted in batches."""
        from src.skills.alpaca_skills import fetch_historical_bars

        # Mock DAO
        mock_dao = Mock()
        mock_dao.save_bars.return_value = 50
        mock_dao_class.return_value = mock_dao

        # Mock API to return large dataset
        mock_bars = Mock()
        large_df = pd.DataFrame({
            'symbol': ['AAPL'] * 60000,
            'timestamp': pd.date_range('2024-01-01', periods=60000, freq='min'),
            'open': [150.0] * 60000,
            'high': [152.0] * 60000,
            'low': [149.0] * 60000,
            'close': [151.0] * 60000,
            'volume': [1000000] * 60000
        })
        mock_bars.df = large_df.set_index(['symbol', 'timestamp'])
        mock_client.get_stock_bars.return_value = mock_bars

        result = fetch_historical_bars(
            'AAPL',
            '2024-01-01',
            '2024-01-10',
            timeframe='1Min',
            batch_size=50000
        )

        # Should have called save_bars multiple times (batch inserts)
        assert mock_dao.save_bars.call_count >= 2

    # ========================================================================
    # fetch_historical_trades Pagination Tests
    # ========================================================================

    @patch('src.skills.alpaca_skills.historical_client')
    @patch('src.skills.alpaca_skills.AlpacaDAO')
    def test_fetch_trades_single_page(self, mock_dao_class, mock_client):
        """Test fetching trades within one page (no pagination)."""
        from src.skills.alpaca_skills import fetch_historical_trades

        # Mock DAO
        mock_dao = Mock()
        mock_dao.save_trades.return_value = 100
        mock_dao_class.return_value = mock_dao

        # Mock trades response (less than limit)
        mock_trades = Mock()
        trades_df = pd.DataFrame({
            'symbol': ['AAPL'] * 100,
            'timestamp': pd.date_range('2024-01-01', periods=100, freq='S'),
            'trade_id': range(100),
            'price': [150.0] * 100,
            'size': [100] * 100
        })
        mock_trades.df = trades_df.set_index(['symbol', 'timestamp'])
        mock_client.get_stock_trades.return_value = mock_trades

        result = fetch_historical_trades(
            'AAPL',
            '2024-01-01',
            '2024-01-02',
            limit=10000
        )

        # Should return data
        assert not result.empty

        # Should call API once (got less than limit)
        assert mock_client.get_stock_trades.call_count == 1

    @patch('src.skills.alpaca_skills.historical_client')
    @patch('src.skills.alpaca_skills.AlpacaDAO')
    @patch('src.skills.alpaca_skills.time.sleep')  # Mock sleep to speed up test
    def test_fetch_trades_multiple_pages(self, mock_sleep, mock_dao_class, mock_client):
        """Test fetching trades across multiple pages."""
        from src.skills.alpaca_skills import fetch_historical_trades

        # Mock DAO
        mock_dao = Mock()
        mock_dao.save_trades.return_value = 100
        mock_dao_class.return_value = mock_dao

        # Mock API to return full pages (indicating more data available)
        call_count = 0

        def get_trades_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_trades = Mock()

            # Return full page for first 2 calls, partial page for 3rd (end of data)
            page_size = 10000 if call_count < 3 else 5000

            trades_df = pd.DataFrame({
                'symbol': ['AAPL'] * page_size,
                'timestamp': pd.date_range('2024-01-01', periods=page_size, freq='S'),
                'trade_id': range(call_count * 10000, call_count * 10000 + page_size),
                'price': [150.0] * page_size,
                'size': [100] * page_size
            })
            mock_trades.df = trades_df.set_index(['symbol', 'timestamp'])
            return mock_trades

        mock_client.get_stock_trades.side_effect = get_trades_side_effect

        result = fetch_historical_trades(
            'AAPL',
            '2024-01-01',
            '2024-01-02',
            limit=10000
        )

        # Should call API 3 times (2 full pages + 1 partial)
        assert mock_client.get_stock_trades.call_count == 3

        # Should have combined all pages
        assert len(result) == 25000  # 10000 + 10000 + 5000

    @patch('src.skills.alpaca_skills.historical_client')
    @patch('src.skills.alpaca_skills.AlpacaDAO')
    def test_fetch_trades_max_total_limit(self, mock_dao_class, mock_client):
        """Test that max_total parameter limits total trades fetched."""
        from src.skills.alpaca_skills import fetch_historical_trades

        # Mock DAO
        mock_dao = Mock()
        mock_dao.save_trades.return_value = 100
        mock_dao_class.return_value = mock_dao

        # Mock API to return large dataset
        mock_trades = Mock()
        trades_df = pd.DataFrame({
            'symbol': ['AAPL'] * 15000,
            'timestamp': pd.date_range('2024-01-01', periods=15000, freq='S'),
            'trade_id': range(15000),
            'price': [150.0] * 15000,
            'size': [100] * 15000
        })
        mock_trades.df = trades_df.set_index(['symbol', 'timestamp'])
        mock_client.get_stock_trades.return_value = mock_trades

        result = fetch_historical_trades(
            'AAPL',
            '2024-01-01',
            '2024-01-02',
            limit=10000,
            max_total=12000  # Limit to 12K trades
        )

        # Should be trimmed to max_total
        assert len(result) == 12000

    @patch('src.skills.alpaca_skills.historical_client')
    @patch('src.skills.alpaca_skills.AlpacaDAO')
    @patch('src.skills.alpaca_skills.time.sleep')
    def test_fetch_trades_rate_limiting(self, mock_sleep, mock_dao_class, mock_client):
        """Test that rate limiting (sleep) is applied between pages."""
        from src.skills.alpaca_skills import fetch_historical_trades

        # Mock DAO
        mock_dao = Mock()
        mock_dao.save_trades.return_value = 100
        mock_dao_class.return_value = mock_dao

        # Mock API to return 2 full pages
        call_count = 0

        def get_trades_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_trades = Mock()
            page_size = 10000 if call_count < 2 else 5000

            trades_df = pd.DataFrame({
                'symbol': ['AAPL'] * page_size,
                'timestamp': pd.date_range('2024-01-01', periods=page_size, freq='S'),
                'trade_id': range(page_size),
                'price': [150.0] * page_size,
                'size': [100] * page_size
            })
            mock_trades.df = trades_df.set_index(['symbol', 'timestamp'])
            return mock_trades

        mock_client.get_stock_trades.side_effect = get_trades_side_effect

        result = fetch_historical_trades(
            'AAPL',
            '2024-01-01',
            '2024-01-02',
            limit=10000,
            page_delay=0.3
        )

        # Should have called sleep between pages (at least once)
        assert mock_sleep.call_count >= 1

    # ========================================================================
    # Edge Cases
    # ========================================================================

    @patch('src.skills.alpaca_skills.historical_client')
    @patch('src.skills.alpaca_skills.AlpacaDAO')
    def test_fetch_bars_empty_response(self, mock_dao_class, mock_client):
        """Test handling of empty API response."""
        from src.skills.alpaca_skills import fetch_historical_bars

        # Mock DAO
        mock_dao = Mock()
        mock_dao_class.return_value = mock_dao

        # Mock empty response
        mock_bars = Mock()
        mock_bars.df = pd.DataFrame()
        mock_client.get_stock_bars.return_value = mock_bars

        result = fetch_historical_bars(
            'INVALID',
            '2024-01-01',
            '2024-01-05',
            timeframe='1Day'
        )

        # Should return empty DataFrame
        assert result.empty

    @patch('src.skills.alpaca_skills.historical_client')
    def test_fetch_trades_empty_response(self, mock_client):
        """Test handling of empty trades response."""
        from src.skills.alpaca_skills import fetch_historical_trades

        # Mock empty response
        mock_trades = Mock()
        mock_trades.df = pd.DataFrame()
        mock_client.get_stock_trades.return_value = mock_trades

        result = fetch_historical_trades(
            'INVALID',
            '2024-01-01',
            '2024-01-02'
        )

        # Should return empty DataFrame
        assert result.empty


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
