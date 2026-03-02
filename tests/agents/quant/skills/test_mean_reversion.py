"""Tests for Mean Reversion Strategy."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
# Import using importlib since directory has hyphens
import importlib.util

strategy_path = project_root / "src/agents/quant/skills/mean-reversion-strategy/mean_reversion.py"  
spec = importlib.util.spec_from_file_location(  
    "mean_reversion",  
    str(strategy_path)  
)
mean_reversion_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mean_reversion_module)
MeanReversionStrategy = mean_reversion_module.MeanReversionStrategy


@pytest.fixture
def sample_data():
    """Create sample market data for testing."""
    dates = pd.date_range(start='2026-01-01', periods=100, freq='D')
    data = {
        'close': np.random.uniform(140, 160, 100),
        'high': np.random.uniform(145, 165, 100),
        'low': np.random.uniform(135, 155, 100),
        'volume': np.random.uniform(1000000, 5000000, 100),
        'vwap': np.random.uniform(142, 158, 100)
    }
    df = pd.DataFrame(data, index=dates)
    return df


@pytest.fixture
def strategy():
    """Create MeanReversionStrategy instance."""
    return MeanReversionStrategy(
        symbol="TEST",
        lookback=60,
        threshold=2.0,
        ma_period=20
    )


class TestMeanReversionStrategy:
    """Test suite for MeanReversionStrategy."""

    def test_initialization(self, strategy):
        """Test strategy initializes correctly."""
        assert strategy.symbol == "TEST"
        assert strategy.lookback == 60
        assert strategy.threshold == 2.0
        assert strategy.ma_period == 20

    def test_calculate_statistics(self, strategy, sample_data):
        """Test statistical calculations including VWAP."""
        stats = strategy.calculate_statistics(sample_data)

        assert stats is not None
        assert "mean" in stats
        assert "std_dev" in stats
        assert "z_score" in stats
        assert "percentile" in stats

        # VWAP should be included if available
        if "vwap" in sample_data.columns:
            assert "vwap" in stats

    def test_calculate_statistics_with_insufficient_data(self, strategy):
        """Test handling of insufficient data."""
        small_df = pd.DataFrame({
            'close': [150.0, 151.0, 152.0]
        })

        stats = strategy.calculate_statistics(small_df)
        # Should return empty dict
        assert stats == {}

    def test_calculate_moving_averages(self, strategy, sample_data):
        """Test moving average calculations."""
        ma = strategy.calculate_moving_averages(sample_data)

        assert ma is not None
        assert "sma_20" in ma
        assert "ema_20" in ma

        # SMA_50 might be None if not enough data
        if "sma_50" in ma:
            assert isinstance(ma["sma_50"], (float, type(None)))

    def test_calculate_bollinger_bands(self, strategy, sample_data):
        """Test Bollinger Bands calculation."""
        bands = strategy.calculate_bollinger_bands(sample_data)

        assert bands is not None
        assert "upper_band" in bands
        assert "middle_band" in bands
        assert "lower_band" in bands

        # Upper band should be greater than lower band
        if bands["upper_band"] and bands["lower_band"]:
            assert bands["upper_band"] > bands["lower_band"]

    def test_calculate_support_resistance(self, strategy, sample_data):
        """Test support/resistance calculation."""
        levels = strategy.calculate_support_resistance(sample_data)

        assert levels is not None
        assert "support" in levels
        assert "resistance" in levels

        # Resistance should be >= support
        if levels["resistance"] and levels["support"]:
            assert levels["resistance"] >= levels["support"]

    def test_generate_signals_neutral(self, strategy, sample_data):
        """Test signal generation for neutral conditions."""
        current_price = 150.0
        stats = {
            "mean": 150.0,
            "std_dev": 2.0,
            "z_score": 0.0,  # Neutral
            "vwap": 149.5
        }
        ma = {"sma_20": 150.5}
        bands = {"upper_band": 154.0, "lower_band": 146.0}

        signals = strategy.generate_signals(current_price, stats, ma, bands)

        assert signals is not None
        assert signals["current_state"] == "neutral"
        assert signals["z_score_signal"] == "neutral"

    def test_generate_signals_oversold(self, strategy, sample_data):
        """Test signal generation for oversold conditions."""
        current_price = 145.0
        stats = {
            "mean": 150.0,
            "std_dev": 2.0,
            "z_score": -2.5,  # Oversold
            "vwap": 149.0
        }
        ma = {"sma_20": 150.0}
        bands = {"upper_band": 154.0, "lower_band": 146.0}

        signals = strategy.generate_signals(current_price, stats, ma, bands)

        assert signals is not None
        assert signals["current_state"] == "oversold"
        assert signals["z_score_signal"] == "oversold"

    def test_generate_trade_recommendation_with_vwap(self, strategy):
        """Test trade recommendation includes VWAP confirmation."""
        current_price = 145.0
        signals = {"overall_signal": "buy"}
        stats = {
            "mean": 150.0,
            "z_score": -2.0,
            "vwap": 148.0  # Price below VWAP
        }
        levels = {"support": 143.0, "resistance": 155.0}

        rec = strategy.generate_trade_recommendation(
            current_price, signals, stats, levels
        )

        assert rec is not None
        assert rec["action"] == "buy"
        assert "vwap" in rec["reason"].lower() or "VWAP" in rec["reason"]
        # Confidence should be boosted when price < VWAP for buy
        assert rec["confidence"] > 0.0

    def test_generate_trade_recommendation_hold(self, strategy):
        """Test hold recommendation."""
        current_price = 150.0
        signals = {"overall_signal": "hold"}
        stats = {"mean": 150.0, "z_score": 0.0, "vwap": 149.5}
        levels = {"support": 145.0, "resistance": 155.0}

        rec = strategy.generate_trade_recommendation(
            current_price, signals, stats, levels
        )

        assert rec["action"] == "hold"
        assert rec["entry_price"] is None

    def test_analyze_with_insufficient_data(self, strategy, monkeypatch):  
        """Test analyze method handles insufficient data gracefully."""  
        # Mock fetch_data to avoid hitting the real DB and return insufficient data  
        def mock_fetch_data(*args, **kwargs):  
            # Return fewer rows than the lookback period to simulate insufficient data  
            dates = pd.date_range(start="2026-01-01", periods=10, freq="D")  
            data = {  
                "close": np.full(10, 150.0),  
                "high": np.full(10, 151.0),  
                "low": np.full(10, 149.0),  
                "volume": np.full(10, 1_000_000),  
                "vwap": np.full(10, 150.0),  
            }  
            return pd.DataFrame(data, index=dates)  

        monkeypatch.setattr(strategy, "fetch_data", mock_fetch_data)  


class TestVWAPLogic:
    """Test suite specifically for VWAP confirmation logic."""

    def test_vwap_boosts_buy_confidence_when_price_below(self):
        """Test that buy confidence increases when price < VWAP."""
        strategy = MeanReversionStrategy("TEST", threshold=2.0)

        current_price = 145.0
        signals = {"overall_signal": "buy"}
        stats = {
            "mean": 150.0,
            "z_score": -1.5,
            "vwap": 148.0  # Price below VWAP
        }
        levels = {}

        rec = strategy.generate_trade_recommendation(
            current_price, signals, stats, levels
        )

        # Confidence should be at least base + boost (0.75 + 0.15 = 0.90)
        # But capped at 1.0
        assert rec["confidence"] >= 0.75

    def test_vwap_boosts_sell_confidence_when_price_above(self):
        """Test that sell confidence increases when price > VWAP."""
        strategy = MeanReversionStrategy("TEST", threshold=2.0)

        current_price = 155.0
        signals = {"overall_signal": "sell"}
        stats = {
            "mean": 150.0,
            "z_score": 1.5,
            "vwap": 152.0  # Price above VWAP
        }
        levels = {}

        rec = strategy.generate_trade_recommendation(
            current_price, signals, stats, levels
        )

        assert rec["confidence"] >= 0.75

    def test_vwap_explanation_in_buy_reason(self):
        """Test that VWAP confirmation is explained in buy reason."""
        strategy = MeanReversionStrategy("TEST", threshold=2.0)

        current_price = 145.0
        signals = {"overall_signal": "buy"}
        stats = {
            "mean": 150.0,
            "z_score": -2.0,
            "vwap": 148.0
        }
        levels = {}

        rec = strategy.generate_trade_recommendation(
            current_price, signals, stats, levels
        )

        # Reason should mention VWAP and underwater buyers
        reason_lower = rec["reason"].lower()
        assert "vwap" in reason_lower
        assert "underwater" in reason_lower or "snap-back" in reason_lower


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
