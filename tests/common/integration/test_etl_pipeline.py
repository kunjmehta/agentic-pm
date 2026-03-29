"""Integration tests for ETL pipeline.

Tests end-to-end flow: fetch data → compute indicators → save to database.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import tempfile
import shutil
from datetime import datetime, timedelta
import pandas as pd

from src.common.dao.alpaca_dao import AlpacaDAO
from src.common.etl.indicators_engine import IndicatorsEngine
from src.common.etl.pipeline import IndicatorsETL


class TestETLPipeline:
    """Integration tests for ETL pipeline."""

    @pytest.fixture(scope="function")
    def temp_db(self):
        """Create temporary database for testing."""
        temp_dir = tempfile.mkdtemp()
        db_path = f"{temp_dir}/test_market.duckdb"

        # Create DAO and initialize schema
        dao = AlpacaDAO(db_path=db_path)
        dao.close()

        yield db_path

        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def sample_bars_data(self):
        """Create sample market bars data."""
        # Use recent dates so ETL can find them (ETL queries last N days from today)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=99)  # 100 days total
        dates = pd.date_range(start=start_date, periods=100, freq='D')

        import numpy as np
        base_price = 150.0
        trend = np.linspace(0, 10, 100)
        noise = np.random.normal(0, 2, 100)
        close_prices = base_price + trend + noise

        df = pd.DataFrame({
            'symbol': 'TEST',
            'timestamp': dates,
            'open': close_prices - np.random.uniform(0, 1, 100),
            'high': close_prices + np.random.uniform(0, 2, 100),
            'low': close_prices - np.random.uniform(0, 2, 100),
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 100),
            'trade_count': np.random.randint(100, 1000, 100),
            'vwap': close_prices + np.random.uniform(-0.5, 0.5, 100),
            'timeframe': '1Day'
        })

        return df

    # ========================================================================
    # End-to-End Pipeline Tests
    # ========================================================================

    def test_end_to_end_single_symbol(self, temp_db, sample_bars_data):
        """Test complete ETL flow for a single symbol."""
        # Setup: Save sample bars to database
        dao = AlpacaDAO(db_path=temp_db)
        dao.save_bars(sample_bars_data, timeframe='1Day')

        # Run ETL
        etl = IndicatorsETL(timeframes=['1Day'], lookback_days=100)
        etl.dao = dao  # Use test DAO

        result = etl.run_for_symbol('TEST')

        # Verify results
        assert result['symbol'] == 'TEST'
        assert result['total_rows'] > 0
        assert len(result['errors']) == 0
        assert '1Day' in result['timeframes']
        assert result['timeframes']['1Day'] > 0

        # Verify data was saved to database
        indicators = dao.get_computed_indicators(
            'TEST',
            sample_bars_data['timestamp'].min(),
            sample_bars_data['timestamp'].max(),
            '1Day'
        )

        assert not indicators.empty
        assert 'macd_value' in indicators.columns
        assert 'rsi' in indicators.columns
        assert 'bb_upper' in indicators.columns

        dao.close()
        etl.close()

    def test_etl_with_multiple_timeframes(self, temp_db, sample_bars_data):
        """Test ETL with multiple timeframes."""
        dao = AlpacaDAO(db_path=temp_db)

        # Save data for multiple timeframes
        for timeframe in ['1Min', '1Hour', '1Day']:
            df = sample_bars_data.copy()
            df['timeframe'] = timeframe
            dao.save_bars(df, timeframe=timeframe)

        # Run ETL
        etl = IndicatorsETL(timeframes=['1Min', '1Hour', '1Day'], lookback_days=100)
        etl.dao = dao

        result = etl.run_for_symbol('TEST')

        # All timeframes should be processed
        assert '1Min' in result['timeframes']
        assert '1Hour' in result['timeframes']
        assert '1Day' in result['timeframes']

        # All should have computed indicators
        assert result['timeframes']['1Min'] > 0
        assert result['timeframes']['1Hour'] > 0
        assert result['timeframes']['1Day'] > 0

        dao.close()
        etl.close()

    def test_etl_handles_insufficient_data(self, temp_db):
        """Test ETL handles symbols with insufficient data gracefully."""
        dao = AlpacaDAO(db_path=temp_db)

        # Create minimal data (only 10 bars)
        dates = pd.date_range(start='2024-01-01', periods=10, freq='D')
        df = pd.DataFrame({
            'symbol': 'MINIMAL',
            'timestamp': dates,
            'open': [100] * 10,
            'high': [101] * 10,
            'low': [99] * 10,
            'close': [100.5] * 10,
            'volume': [1000000] * 10,
            'timeframe': '1Day'
        })

        dao.save_bars(df, timeframe='1Day')

        # Run ETL
        etl = IndicatorsETL(timeframes=['1Day'], lookback_days=100)
        etl.dao = dao

        result = etl.run_for_symbol('MINIMAL')

        # Should complete without errors, but may have 0 rows if insufficient data
        # (requires 60 bars minimum for mean reversion)
        assert result['symbol'] == 'MINIMAL'
        assert len(result['errors']) == 0

        dao.close()
        etl.close()

    # ========================================================================
    # Indicator Accuracy Tests
    # ========================================================================

    def test_computed_indicators_match_engine(self, temp_db, sample_bars_data):
        """Test that ETL computed indicators match IndicatorsEngine results."""
        dao = AlpacaDAO(db_path=temp_db)
        dao.save_bars(sample_bars_data, timeframe='1Day')

        # Compute indicators using engine directly
        engine = IndicatorsEngine()
        engine_result = engine.calc_all(sample_bars_data)

        # Run ETL
        etl = IndicatorsETL(timeframes=['1Day'], lookback_days=100)
        etl.dao = dao
        etl.run_for_symbol('TEST')

        # Retrieve stored indicators
        indicators = dao.get_computed_indicators(
            'TEST',
            sample_bars_data['timestamp'].min(),
            sample_bars_data['timestamp'].max(),
            '1Day'
        )

        # Last row should match engine result
        last_row = indicators.iloc[-1]

        # Compare MACD
        assert abs(last_row['macd_value'] - engine_result['momentum']['macd']['value']) < 0.01

        # Compare RSI
        assert abs(last_row['rsi'] - engine_result['momentum']['rsi']) < 0.01

        # Compare Bollinger Bands
        assert abs(last_row['bb_upper'] - engine_result['volatility']['upper']) < 0.01

        dao.close()
        etl.close()

    # ========================================================================
    # Rolling Window Tests
    # ========================================================================

    def test_rolling_window_calculation(self, temp_db):
        """Test that indicators are calculated for each timestamp using rolling window."""
        dao = AlpacaDAO(db_path=temp_db)

        # Create data with known values that varies enough for indicators
        # Use recent dates so ETL can find them
        end_date = datetime.now()
        start_date = end_date - timedelta(days=99)
        dates = pd.date_range(start=start_date, periods=100, freq='D')

        # Create varying prices (not just linear) for realistic indicators
        import numpy as np
        base_prices = list(range(100, 200))
        # Add some variation to make RSI calculable
        close_prices = [p + np.random.uniform(-2, 2) for p in base_prices]

        df = pd.DataFrame({
            'symbol': 'ROLLING',
            'timestamp': dates,
            'open': [p - 1 for p in close_prices],
            'high': [p + 2 for p in close_prices],
            'low': [p - 2 for p in close_prices],
            'close': close_prices,
            'volume': [1000000] * 100,
            'timeframe': '1Day'
        })

        dao.save_bars(df, timeframe='1Day')

        # Run ETL
        etl = IndicatorsETL(timeframes=['1Day'], lookback_days=100)
        etl.dao = dao
        etl.run_for_symbol('ROLLING')

        # Retrieve indicators
        indicators = dao.get_computed_indicators(
            'ROLLING',
            dates.min(),
            dates.max(),
            '1Day'
        )

        # Should have indicators for multiple timestamps (after minimum 60 bars)
        assert len(indicators) >= 40  # At least 40 rows (100 - 60)

        # Each row should have computed indicators
        assert not indicators['macd_value'].isna().all()
        assert not indicators['rsi'].isna().all()

        dao.close()
        etl.close()

    # ========================================================================
    # Error Handling Tests
    # ========================================================================

    def test_etl_handles_missing_symbol(self, temp_db):
        """Test ETL handles missing symbol gracefully."""
        dao = AlpacaDAO(db_path=temp_db)

        etl = IndicatorsETL(timeframes=['1Day'], lookback_days=100)
        etl.dao = dao

        result = etl.run_for_symbol('NONEXISTENT')

        # Should complete without errors
        assert result['symbol'] == 'NONEXISTENT'
        assert result['total_rows'] == 0

        dao.close()
        etl.close()

    def test_etl_continues_on_timeframe_error(self, temp_db, sample_bars_data):
        """Test that ETL continues processing other timeframes if one fails."""
        dao = AlpacaDAO(db_path=temp_db)

        # Only save 1Day data
        dao.save_bars(sample_bars_data, timeframe='1Day')

        # Try to process multiple timeframes (some will have no data)
        etl = IndicatorsETL(timeframes=['1Min', '1Hour', '1Day'], lookback_days=100)
        etl.dao = dao

        result = etl.run_for_symbol('TEST')

        # Should have processed 1Day successfully
        assert result['timeframes']['1Day'] > 0

        # Others should have 0 rows (no data)
        assert result['timeframes']['1Min'] == 0
        assert result['timeframes']['1Hour'] == 0

        dao.close()
        etl.close()

    # ========================================================================
    # Watchlist Processing Tests
    # ========================================================================

    def test_run_for_watchlist(self, temp_db, sample_bars_data):
        """Test processing entire watchlist."""
        dao = AlpacaDAO(db_path=temp_db)

        # Add symbols to watchlist and save data
        symbols = ['AAPL', 'MSFT', 'GOOGL']
        for symbol in symbols:
            dao.add_to_watchlist(symbol)

            # Save bars for each symbol
            df = sample_bars_data.copy()
            df['symbol'] = symbol
            dao.save_bars(df, timeframe='1Day')

        # Run ETL for watchlist
        etl = IndicatorsETL(timeframes=['1Day'], lookback_days=100)
        etl.dao = dao

        result = etl.run_for_watchlist()

        # Should have processed all symbols
        assert len(result['symbols']) == 3
        assert 'AAPL' in result['symbols']
        assert 'MSFT' in result['symbols']
        assert 'GOOGL' in result['symbols']

        # Total rows should be sum of all symbols
        assert result['total_rows'] > 0

        dao.close()
        etl.close()

    def test_run_for_empty_watchlist(self, temp_db):
        """Test ETL with empty watchlist."""
        dao = AlpacaDAO(db_path=temp_db)

        etl = IndicatorsETL(timeframes=['1Day'], lookback_days=100)
        etl.dao = dao

        result = etl.run_for_watchlist()

        # Should handle empty watchlist gracefully
        assert len(result['symbols']) == 0
        assert result['total_rows'] == 0

        dao.close()
        etl.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
