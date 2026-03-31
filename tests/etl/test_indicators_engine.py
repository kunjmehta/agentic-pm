"""Unit tests for IndicatorsEngine.

Tests that all formula calculations match the quant agent implementations
and handle edge cases correctly.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.etl.indicators_engine import IndicatorsEngine


class TestIndicatorsEngine:
    """Test suite for IndicatorsEngine calculations."""

    @pytest.fixture
    def sample_data(self):
        """Create sample OHLCV data for testing."""
        dates = pd.date_range(start='2024-01-01', periods=100, freq='D')

        # Generate realistic price data with trend and volatility
        base_price = 150.0
        trend = np.linspace(0, 10, 100)
        noise = np.random.normal(0, 2, 100)
        close_prices = base_price + trend + noise

        df = pd.DataFrame({
            'timestamp': dates,
            'open': close_prices - np.random.uniform(0, 1, 100),
            'high': close_prices + np.random.uniform(0, 2, 100),
            'low': close_prices - np.random.uniform(0, 2, 100),
            'close': close_prices,
            'volume': np.random.randint(1000000, 10000000, 100),
            'vwap': close_prices + np.random.uniform(-0.5, 0.5, 100)
        })

        return df

    @pytest.fixture
    def minimal_data(self):
        """Create minimal data for edge case testing."""
        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2024-01-01', periods=5, freq='D'),
            'open': [100, 101, 102, 103, 104],
            'high': [101, 102, 103, 104, 105],
            'low': [99, 100, 101, 102, 103],
            'close': [100.5, 101.5, 102.5, 103.5, 104.5],
            'volume': [1000000] * 5,
        })
        return df

    # ========================================================================
    # Momentum Indicators Tests
    # ========================================================================

    def test_calc_momentum_valid_data(self, sample_data):
        """Test momentum calculation with valid data."""
        result = IndicatorsEngine.calc_momentum(sample_data)

        assert result is not None
        assert 'macd' in result
        assert 'rsi' in result

        # MACD should have value, signal, histogram
        assert result['macd'] is not None
        assert 'value' in result['macd']
        assert 'signal' in result['macd']
        assert 'histogram' in result['macd']

        # RSI should be between 0 and 100
        assert result['rsi'] is not None
        assert 0 <= result['rsi'] <= 100

    def test_calc_momentum_insufficient_data(self, minimal_data):
        """Test momentum with insufficient data (< 26 bars)."""
        result = IndicatorsEngine.calc_momentum(minimal_data)

        assert result['macd'] is None
        assert result['rsi'] is None

    def test_calc_momentum_exact_minimum(self):
        """Test momentum with exactly 26 bars (minimum for MACD)."""
        df = pd.DataFrame({
            'close': np.random.uniform(100, 110, 26)
        })

        result = IndicatorsEngine.calc_momentum(df)

        # Should have MACD but may not have RSI
        assert result['macd'] is not None

    # ========================================================================
    # Volatility Indicators Tests
    # ========================================================================

    def test_calc_volatility_valid_data(self, sample_data):
        """Test Bollinger Bands calculation."""
        result = IndicatorsEngine.calc_volatility(sample_data)

        assert result is not None
        assert 'upper' in result
        assert 'middle' in result
        assert 'lower' in result
        assert 'bandwidth' in result

        # All values should be present
        assert result['upper'] is not None
        assert result['middle'] is not None
        assert result['lower'] is not None
        assert result['bandwidth'] is not None

        # Upper > Middle > Lower
        assert result['upper'] > result['middle']
        assert result['middle'] > result['lower']

    def test_calc_volatility_custom_params(self, sample_data):
        """Test Bollinger Bands with custom parameters."""
        result_default = IndicatorsEngine.calc_volatility(sample_data)
        result_custom = IndicatorsEngine.calc_volatility(sample_data, period=10, num_std=1.5)

        # Results should differ
        assert result_default['bandwidth'] != result_custom['bandwidth']

    def test_calc_volatility_insufficient_data(self):
        """Test volatility with insufficient data."""
        df = pd.DataFrame({'close': [100, 101, 102]})

        result = IndicatorsEngine.calc_volatility(df, period=20)

        assert result['upper'] is None
        assert result['middle'] is None
        assert result['lower'] is None

    # ========================================================================
    # Volume Indicators Tests
    # ========================================================================

    def test_calc_volume_valid_data(self, sample_data):
        """Test volume indicators calculation."""
        result = IndicatorsEngine.calc_volume(sample_data)

        assert result is not None
        assert 'obv' in result
        assert 'volume_trend' in result
        assert 'avg_volume_10d' in result
        assert 'current_vs_avg' in result

        # OBV should be present
        assert result['obv'] is not None
        assert isinstance(result['obv'], int)

        # Volume trend should be 'increasing' or 'decreasing'
        assert result['volume_trend'] in ['increasing', 'decreasing', 'unknown']

    def test_calc_volume_obv_logic(self):
        """Test OBV calculation logic."""
        df = pd.DataFrame({
            'close': [100, 102, 101, 103, 102],  # Up, Down, Up, Down
            'volume': [1000, 2000, 1500, 2500, 1800]
        })

        result = IndicatorsEngine.calc_volume(df)

        # OBV should accumulate: 0 + 2000 - 1500 + 2500 - 1800 = 1200
        assert result['obv'] == 1200

    def test_calc_volume_insufficient_data(self):
        """Test volume with insufficient data."""
        df = pd.DataFrame({
            'close': [100],
            'volume': [1000]
        })

        result = IndicatorsEngine.calc_volume(df)

        assert result['obv'] is None

    # ========================================================================
    # Candlestick Pattern Tests
    # ========================================================================

    def test_calc_candlestick_valid_data(self, sample_data):
        """Test candlestick pattern detection."""
        result = IndicatorsEngine.calc_candlestick(sample_data)

        assert result is not None
        assert 'patterns' in result
        assert 'last_candle_type' in result
        assert 'last_body_pct' in result
        assert 'pattern_count' in result

        # Last candle type should be valid
        assert result['last_candle_type'] in ['bullish', 'bearish', 'neutral']

        # Body percentage should be between 0 and 100
        assert 0 <= result['last_body_pct'] <= 100

    def test_calc_candlestick_bullish_engulfing(self):
        """Test bullish engulfing pattern detection."""
        df = pd.DataFrame({
            'open': [100, 99, 98],
            'high': [101, 100, 102],
            'low': [99, 98, 97],
            'close': [99.5, 98.5, 101],  # Bearish, Bearish, Bullish engulfing
        })

        result = IndicatorsEngine.calc_candlestick(df)

        # Should detect bullish engulfing (last candle engulfs previous)
        assert 'bullish_engulfing' in result['patterns']

    def test_calc_candlestick_doji(self):
        """Test doji pattern detection."""
        df = pd.DataFrame({
            'open': [100, 100],
            'high': [105, 105],
            'low': [95, 95],
            'close': [100.5, 100.5],  # Small body, doji
        })

        result = IndicatorsEngine.calc_candlestick(df, lookback=2)

        # Should detect doji (small body relative to range)
        assert 'doji' in result['patterns']

    def test_calc_candlestick_insufficient_data(self):
        """Test candlestick with insufficient data."""
        df = pd.DataFrame({
            'open': [100],
            'high': [101],
            'low': [99],
            'close': [100.5]
        })

        result = IndicatorsEngine.calc_candlestick(df)

        assert result['patterns'] == []
        assert result['pattern_count'] == 0

    # ========================================================================
    # Mean Reversion Tests
    # ========================================================================

    def test_calc_mean_reversion_valid_data(self, sample_data):
        """Test mean reversion calculation."""
        result = IndicatorsEngine.calc_mean_reversion(sample_data)

        assert result is not None
        assert 'mean' in result
        assert 'std_dev' in result
        assert 'z_score' in result
        assert 'percentile' in result

        # Percentile should be between 0 and 100
        assert 0 <= result['percentile'] <= 100

    def test_calc_mean_reversion_z_score(self):
        """Test Z-score calculation logic."""
        # Create data with known mean and std
        prices = [100] * 50 + [110]  # Mean ~100, last value is outlier
        df = pd.DataFrame({
            'close': prices,
            'volume': [1000000] * 51
        })

        result = IndicatorsEngine.calc_mean_reversion(df, lookback=51)

        # Z-score should be positive (current price above mean)
        assert result['z_score'] > 0

    def test_calc_mean_reversion_vwap(self, sample_data):
        """Test VWAP calculation."""
        result = IndicatorsEngine.calc_mean_reversion(sample_data)

        # VWAP should be present
        assert 'vwap' in result
        assert result['vwap'] is not None

    def test_calc_mean_reversion_insufficient_data(self):
        """Test mean reversion with insufficient data."""
        df = pd.DataFrame({
            'close': [100, 101, 102],
            'volume': [1000, 1000, 1000]
        })

        result = IndicatorsEngine.calc_mean_reversion(df, lookback=60)

        # Should return empty dict
        assert result == {}

    # ========================================================================
    # calc_all() Integration Tests
    # ========================================================================

    def test_calc_all_valid_data(self, sample_data):
        """Test calc_all() with valid data."""
        result = IndicatorsEngine.calc_all(sample_data)

        assert result is not None
        assert 'momentum' in result
        assert 'volatility' in result
        assert 'volume' in result
        assert 'candlestick' in result
        assert 'mean_reversion' in result

        # All categories should have data
        assert result['momentum'] is not None
        assert result['volatility'] is not None
        assert result['volume'] is not None
        assert result['candlestick'] is not None
        assert result['mean_reversion'] is not None

    def test_calc_all_minimal_data(self, minimal_data):
        """Test calc_all() with minimal data."""
        result = IndicatorsEngine.calc_all(minimal_data)

        # Should return structure even with limited data
        assert 'momentum' in result
        assert 'volatility' in result
        assert 'volume' in result

        # Some indicators may be None due to insufficient data
        assert result['momentum']['macd'] is None  # Need 26 bars

    # ========================================================================
    # Edge Cases and Error Handling
    # ========================================================================

    def test_empty_dataframe(self):
        """Test all functions with empty DataFrame."""
        df = pd.DataFrame()

        # All functions should handle empty DataFrame gracefully
        assert IndicatorsEngine.calc_momentum(df) == {'macd': None, 'rsi': None}
        assert IndicatorsEngine.calc_volatility(df) == {
            'upper': None, 'middle': None, 'lower': None, 'bandwidth': None
        }

        volume_result = IndicatorsEngine.calc_volume(df)
        assert volume_result['obv'] is None

    def test_nan_values(self):
        """Test handling of NaN values in data."""
        df = pd.DataFrame({
            'close': [100, 101, np.nan, 103, 104],
            'volume': [1000, 1000, 1000, np.nan, 1000]
        })

        # Functions should handle NaN gracefully (pandas will propagate NaN)
        result = IndicatorsEngine.calc_momentum(df)
        # Result may have None or NaN values, which is acceptable

    def test_constant_prices(self):
        """Test with constant prices (no volatility)."""
        df = pd.DataFrame({
            'close': [100] * 100,
            'volume': [1000000] * 100
        })

        result = IndicatorsEngine.calc_volatility(df)

        # Standard deviation should be 0, bands should collapse
        assert result['bandwidth'] == 0 or result['bandwidth'] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
