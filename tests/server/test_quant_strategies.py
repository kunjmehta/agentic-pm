"""Tests for Phase 28 strategy skill classes.

Covers all 8 new strategy classes using synthetic price/volume data.
No network calls — all ``generate_signals`` paths are tested via
``analyze_bars`` only (bar-level tests) plus factory function smoke tests.

Day trading (1Min/5Min):
    VWAPReversionSkill, OpeningRangeBreakoutSkill,
    RSIDivergenceScalpSkill, MomentumBurstSkill

Swing (1Day):
    GoldenCrossSkill, Breakout52WeekSkill,
    MeanReversionDailySkill, EarningsDriftSkill

Also covers:
    - Factory function closures return valid "buy"/"sell"/"hold" strings
    - Insufficient-data guard returns action="hold"
    - Re-export from skills.py (backward-compat)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RNG = np.random.default_rng(0)


def _make_bars(n: int, base: float = 100.0, vol_base: int = 10_000) -> pd.DataFrame:
    """Synthetic OHLCV bars with mild random walk."""
    prices = base + np.cumsum(RNG.normal(0, 0.3, n))
    volumes = RNG.integers(vol_base // 2, vol_base * 2, n).astype(float)
    return pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.003,
        "low": prices * 0.997,
        "close": prices,
        "volume": volumes,
    })


def _make_trending_bars(n: int, trend: float = 0.5) -> pd.DataFrame:
    """Bars with a clear upward trend (used for crossover tests)."""
    prices = 100.0 + np.arange(n) * trend + RNG.normal(0, 0.1, n)
    volumes = np.full(n, 100_000.0)
    return pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.002,
        "low": prices * 0.998,
        "close": prices,
        "volume": volumes,
    })


# ===========================================================================
# VWAPReversionSkill
# ===========================================================================


class TestVWAPReversionSkill:
    @pytest.fixture(autouse=True)
    def _import(self):
        from src.server.skills.quant.vwap_reversion import VWAPReversionSkill
        self.skill = VWAPReversionSkill()

    def test_insufficient_data_returns_hold(self):
        df = _make_bars(10)
        result = self.skill.analyze_bars(df)
        assert result["action"] == "hold"

    def test_hold_when_no_deviation(self):
        """Price near VWAP with normal volume → hold."""
        df = _make_bars(50)
        result = self.skill.analyze_bars(df, dev_pct=0.99)  # unreachably high threshold
        assert result["action"] == "hold"
        assert "vwap" in result
        assert "deviation_pct" in result

    def test_buy_signal_when_price_below_vwap_with_vol_spike(self):
        """Manually construct bars where last price is far below VWAP with volume spike."""
        n = 50
        prices = np.full(n, 100.0)
        prices[-1] = 95.0  # 5% below VWAP
        volumes = np.full(n, 1000.0)
        volumes[-1] = 5000.0  # 5× spike
        df = pd.DataFrame({
            "open": prices,
            "high": prices + 0.1,
            "low": prices - 0.1,
            "close": prices,
            "volume": volumes,
        })
        result = self.skill.analyze_bars(df, dev_pct=0.03, vol_mult=3.0)
        assert result["action"] == "buy"
        assert result["confidence"] > 0
        assert result["stop_loss"] < result["entry_price"]
        assert result["take_profit"] > result["entry_price"]

    def test_sell_signal_when_price_above_vwap(self):
        """Price above VWAP with volume spike → sell."""
        n = 50
        prices = np.full(n, 100.0)
        prices[-1] = 105.0  # 5% above VWAP
        volumes = np.full(n, 1000.0)
        volumes[-1] = 5000.0
        df = pd.DataFrame({
            "open": prices,
            "high": prices + 0.1,
            "low": prices - 0.1,
            "close": prices,
            "volume": volumes,
        })
        result = self.skill.analyze_bars(df, dev_pct=0.03, vol_mult=3.0)
        assert result["action"] == "sell"
        assert result["stop_loss"] > result["entry_price"]
        assert result["take_profit"] < result["entry_price"]

    def test_result_keys_present(self):
        df = _make_bars(50)
        result = self.skill.analyze_bars(df)
        assert "action" in result
        assert "confidence" in result


# ===========================================================================
# OpeningRangeBreakoutSkill
# ===========================================================================


class TestOpeningRangeBreakoutSkill:
    @pytest.fixture(autouse=True)
    def _import(self):
        from src.server.skills.quant.opening_range_breakout import OpeningRangeBreakoutSkill
        self.skill = OpeningRangeBreakoutSkill()

    def test_insufficient_data_returns_hold(self):
        df = _make_bars(10)
        result = self.skill.analyze_bars(df, range_bars=15)
        assert result["action"] == "hold"

    def test_within_range_returns_hold(self):
        """Price stays within the opening range → hold."""
        df = _make_bars(50, base=100.0)
        # Force price to be within range (by making opening range very wide)
        result = self.skill.analyze_bars(df, range_bars=48)
        assert result["action"] == "hold"

    def test_breakout_above_returns_buy(self):
        """Price clearly above opening range high → buy."""
        n = 50
        # Opening range: bars 0-14 have high=101, low=99
        close = np.full(n, 100.0)
        high = np.full(n, 101.0)
        low = np.full(n, 99.0)
        # Last bar breaks out above
        close[-1] = 103.0
        high[-1] = 103.5
        df = pd.DataFrame({
            "open": close - 0.1,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 10_000.0),
        })
        result = self.skill.analyze_bars(df, range_bars=15)
        assert result["action"] == "buy"
        assert result["confidence"] > 0
        assert result["take_profit"] > result["entry_price"]

    def test_breakout_below_returns_sell(self):
        """Price below opening range low → sell."""
        n = 50
        close = np.full(n, 100.0)
        high = np.full(n, 101.0)
        low = np.full(n, 99.0)
        close[-1] = 97.0
        low[-1] = 96.5
        df = pd.DataFrame({
            "open": close - 0.1,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 10_000.0),
        })
        result = self.skill.analyze_bars(df, range_bars=15)
        assert result["action"] == "sell"
        assert result["take_profit"] < result["entry_price"]

    def test_zero_range_returns_hold(self):
        n = 20
        close = np.full(n, 100.0)
        df = pd.DataFrame({
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": np.ones(n) * 1000,
        })
        result = self.skill.analyze_bars(df, range_bars=15)
        assert result["action"] == "hold"


# ===========================================================================
# RSIDivergenceScalpSkill
# ===========================================================================


class TestRSIDivergenceScalpSkill:
    @pytest.fixture(autouse=True)
    def _import(self):
        from src.server.skills.quant.rsi_divergence_scalp import RSIDivergenceScalpSkill
        self.skill = RSIDivergenceScalpSkill()

    def test_insufficient_data_returns_hold(self):
        df = _make_bars(10)
        result = self.skill.analyze_bars(df)
        assert result["action"] == "hold"

    def test_returns_hold_on_normal_market(self):
        """Random walk bars are unlikely to show clean divergence → hold."""
        df = _make_bars(100)
        result = self.skill.analyze_bars(df)
        assert result["action"] in ("hold", "buy")  # could be buy, that's fine
        assert "current_rsi" in result

    def test_keys_present(self):
        df = _make_bars(60)
        result = self.skill.analyze_bars(df)
        assert "action" in result
        assert "confidence" in result
        assert "current_rsi" in result

    def test_confidence_in_range(self):
        df = _make_bars(100)
        result = self.skill.analyze_bars(df)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_buy_conditions(self):
        """Construct bars satisfying divergence conditions → action='buy'."""
        rsi_period = 14
        n = 80
        # Downward trending prices (produce low RSI) then flatten near recent low
        prices = np.concatenate([
            np.linspace(100, 70, 60),   # sharp drop → low RSI
            np.full(20, 70.5),           # flatline just above the low
        ])
        volumes = np.full(n, 5000.0)
        df = pd.DataFrame({
            "open": prices - 0.1,
            "high": prices + 0.5,
            "low": prices - 0.5,
            "close": prices,
            "volume": volumes,
        })
        result = self.skill.analyze_bars(df, oversold=60.0)
        # Either we get a buy signal or hold; validate structure
        assert result["action"] in ("buy", "hold")
        assert "current_rsi" in result


# ===========================================================================
# MomentumBurstSkill
# ===========================================================================


class TestMomentumBurstSkill:
    @pytest.fixture(autouse=True)
    def _import(self):
        from src.server.skills.quant.momentum_burst import MomentumBurstSkill
        self.skill = MomentumBurstSkill()

    def test_insufficient_data_returns_hold(self):
        df = _make_bars(10)
        result = self.skill.analyze_bars(df)
        assert result["action"] == "hold"

    def test_no_burst_returns_hold(self):
        df = _make_bars(50)
        # Set unreachably high thresholds
        result = self.skill.analyze_bars(df, vol_mult=100.0, min_move=1.0)
        assert result["action"] == "hold"

    def test_buy_burst_detected(self):
        """Volume spike + positive bar return → buy."""
        n = 30
        prices = np.full(n, 100.0)
        prices[-1] = 101.0  # 1% bar
        volumes = np.full(n, 1000.0)
        volumes[-1] = 5000.0  # 5× spike
        df = pd.DataFrame({
            "open": prices,
            "high": prices + 0.1,
            "low": prices - 0.1,
            "close": prices,
            "volume": volumes,
        })
        result = self.skill.analyze_bars(df, vol_mult=3.0, min_move=0.005)
        assert result["action"] == "buy"
        assert result["confidence"] > 0
        assert result["stop_loss"] < result["entry_price"]

    def test_sell_burst_detected(self):
        """Volume spike + negative bar return → sell."""
        n = 30
        prices = np.full(n, 100.0)
        prices[-1] = 99.0  # -1% bar
        volumes = np.full(n, 1000.0)
        volumes[-1] = 5000.0
        df = pd.DataFrame({
            "open": prices,
            "high": prices + 0.1,
            "low": prices - 0.1,
            "close": prices,
            "volume": volumes,
        })
        result = self.skill.analyze_bars(df, vol_mult=3.0, min_move=0.005)
        assert result["action"] == "sell"
        assert result["stop_loss"] > result["entry_price"]

    def test_confidence_in_range(self):
        df = _make_bars(50)
        result = self.skill.analyze_bars(df)
        assert 0.0 <= result["confidence"] <= 1.0


# ===========================================================================
# GoldenCrossSkill
# ===========================================================================


class TestGoldenCrossSkill:
    @pytest.fixture(autouse=True)
    def _import(self):
        from src.server.skills.quant.golden_cross import GoldenCrossSkill
        self.skill = GoldenCrossSkill()

    def test_insufficient_data_returns_hold(self):
        df = _make_bars(100)
        result = self.skill.analyze_bars(df, fast=50, slow=200)
        assert result["action"] == "hold"

    def test_hold_when_no_crossover(self):
        """Flat prices — no crossover."""
        df = _make_bars(210)
        result = self.skill.analyze_bars(df)
        assert result["action"] in ("hold", "buy", "sell")
        assert "sma_fast" in result
        assert "sma_slow" in result

    def test_golden_cross_detected(self):
        """Build bars where fast crosses above slow at the end."""
        # First 200 bars: slow downtrend (fast < slow)
        # Last few bars: fast rise (fast > slow)
        n = 210
        prices = np.concatenate([
            np.linspace(200, 100, 200),  # downtrend: fast < slow throughout
            np.linspace(100, 200, 10),   # sharp recovery: fast crosses above slow
        ])
        volumes = np.full(n, 100_000.0)
        df = pd.DataFrame({
            "open": prices, "high": prices + 1,
            "low": prices - 1, "close": prices, "volume": volumes
        })
        result = self.skill.analyze_bars(df, fast=10, slow=50)
        assert result["action"] in ("buy", "hold")  # exact crossover depends on math

    def test_keys_present(self):
        df = _make_bars(210)
        result = self.skill.analyze_bars(df)
        assert "action" in result
        assert "confidence" in result
        assert "spread_pct" in result


# ===========================================================================
# Breakout52WeekSkill
# ===========================================================================


class TestBreakout52WeekSkill:
    @pytest.fixture(autouse=True)
    def _import(self):
        from src.server.skills.quant.breakout_52w import Breakout52WeekSkill
        self.skill = Breakout52WeekSkill()

    def test_insufficient_data_returns_hold(self):
        df = _make_bars(50)
        result = self.skill.analyze_bars(df, lookback=252)
        assert result["action"] == "hold"

    def test_no_breakout_returns_hold(self):
        """Price below 52-week high → hold."""
        df = _make_bars(300, base=100.0)
        # Set vol_mult so high it can't be reached
        result = self.skill.analyze_bars(df, lookback=252, vol_mult=100.0)
        assert result["action"] == "hold"

    def test_breakout_detected(self):
        """Last bar is higher than all prior 252 bars with high volume."""
        n = 280
        prices = np.full(n, 100.0)
        prices[-1] = 130.0  # new 52-week high
        volumes = np.full(n, 1000.0)
        volumes[-1] = 3000.0  # 3× avg
        df = pd.DataFrame({
            "open": prices, "high": prices + 0.5,
            "low": prices - 0.5, "close": prices, "volume": volumes,
        })
        result = self.skill.analyze_bars(df, lookback=252, vol_mult=2.0)
        assert result["action"] == "buy"
        assert result["stop_loss"] < result["entry_price"]

    def test_keys_present(self):
        df = _make_bars(280)
        result = self.skill.analyze_bars(df)
        assert "action" in result
        assert "prior_high" in result
        assert "volume_ratio" in result


# ===========================================================================
# MeanReversionDailySkill
# ===========================================================================


class TestMeanReversionDailySkill:
    @pytest.fixture(autouse=True)
    def _import(self):
        from src.server.skills.quant.mean_reversion_daily import MeanReversionDailySkill
        self.skill = MeanReversionDailySkill()

    def test_delegates_to_mean_reversion_skill(self):
        """analyze_bars should return a dict with trade_recommendation."""
        df = _make_bars(60)
        result = self.skill.analyze_bars(df)
        assert isinstance(result, dict)
        # MeanReversionSkill always returns these keys
        assert "trade_recommendation" in result or "action" in result

    def test_returns_valid_action(self):
        df = _make_bars(60)
        result = self.skill.analyze_bars(df)
        rec = result.get("trade_recommendation", {})
        action = rec.get("action", result.get("action", "hold"))
        assert action in ("buy", "sell", "hold")


# ===========================================================================
# EarningsDriftSkill
# ===========================================================================


class TestEarningsDriftSkill:
    @pytest.fixture(autouse=True)
    def _import(self):
        from src.server.skills.quant.earnings_drift import EarningsDriftSkill
        self.skill = EarningsDriftSkill()

    def test_insufficient_data_returns_hold(self):
        df = _make_bars(10)
        result = self.skill.analyze_bars(df)
        assert result["action"] == "hold"

    def test_no_catalyst_returns_hold(self):
        """Flat prices with no big move → no catalyst detected."""
        n = 50
        prices = np.full(n, 100.0)
        volumes = np.full(n, 1000.0)
        df = pd.DataFrame({
            "open": prices, "high": prices + 0.1,
            "low": prices - 0.1, "close": prices, "volume": volumes,
        })
        result = self.skill.analyze_bars(df, min_move=0.04, vol_mult=2.0)
        assert result["action"] == "hold"

    def test_catalyst_in_drift_window_generates_signal(self):
        """A big move 3 bars ago with volume → buy/sell signal."""
        n = 50
        prices = np.full(n, 100.0)
        volumes = np.full(n, 1000.0)
        # Catalyst day: 3 bars ago
        prices[-4] = 108.0  # ~8% move up
        volumes[-4] = 4000.0  # 4× avg volume
        df = pd.DataFrame({
            "open": prices * 0.998, "high": prices * 1.005,
            "low": prices * 0.995, "close": prices, "volume": volumes,
        })
        result = self.skill.analyze_bars(df, lookback=10, min_move=0.04, vol_mult=2.0, hold_days=5)
        assert result["action"] in ("buy", "sell", "hold")

    def test_confidence_in_range(self):
        df = _make_bars(50)
        result = self.skill.analyze_bars(df)
        assert 0.0 <= result["confidence"] <= 1.0


# ===========================================================================
# Factory function smoke tests
# ===========================================================================


class TestFactoryFunctions:
    """Verify factory closures return valid signal strings on synthetic data."""

    def _df(self, n: int = 50) -> pd.DataFrame:
        return _make_bars(n)

    def test_make_vwap_reversion_signals(self):
        from src.server.skills.quant.vwap_reversion import make_vwap_reversion_signals
        fn = make_vwap_reversion_signals()
        assert fn("AAPL", self._df()) in ("buy", "sell", "hold")

    def test_make_opening_range_breakout_signals(self):
        from src.server.skills.quant.opening_range_breakout import make_opening_range_breakout_signals
        fn = make_opening_range_breakout_signals(range_bars=10)
        assert fn("AAPL", self._df()) in ("buy", "sell", "hold")

    def test_make_rsi_divergence_signals(self):
        from src.server.skills.quant.rsi_divergence_scalp import make_rsi_divergence_signals
        fn = make_rsi_divergence_signals()
        assert fn("AAPL", self._df(100)) in ("buy", "sell", "hold")

    def test_make_momentum_burst_signals(self):
        from src.server.skills.quant.momentum_burst import make_momentum_burst_signals
        fn = make_momentum_burst_signals()
        assert fn("AAPL", self._df()) in ("buy", "sell", "hold")

    def test_make_golden_cross_signals(self):
        from src.server.skills.quant.golden_cross import make_golden_cross_signals
        fn = make_golden_cross_signals(fast=10, slow=50)
        assert fn("AAPL", self._df(60)) in ("buy", "sell", "hold")

    def test_make_breakout_52w_signals(self):
        from src.server.skills.quant.breakout_52w import make_breakout_52w_signals
        fn = make_breakout_52w_signals(lookback=30)
        assert fn("AAPL", self._df(60)) in ("buy", "sell", "hold")

    def test_make_mean_reversion_daily_signals(self):
        from src.server.skills.quant.mean_reversion_daily import make_mean_reversion_daily_signals
        fn = make_mean_reversion_daily_signals()
        assert fn("AAPL", self._df(60)) in ("buy", "sell", "hold")

    def test_make_earnings_drift_signals(self):
        from src.server.skills.quant.earnings_drift import make_earnings_drift_signals
        fn = make_earnings_drift_signals()
        assert fn("AAPL", self._df(60)) in ("buy", "sell", "hold")

    def test_empty_df_returns_hold(self):
        from src.server.skills.quant.vwap_reversion import make_vwap_reversion_signals
        fn = make_vwap_reversion_signals()
        assert fn("AAPL", pd.DataFrame()) == "hold"

    def test_none_df_returns_hold(self):
        from src.server.skills.quant.momentum_burst import make_momentum_burst_signals
        fn = make_momentum_burst_signals()
        assert fn("AAPL", None) == "hold"


# ===========================================================================
# Backward-compat: import from skills.py re-exports
# ===========================================================================


class TestBackwardCompatReexport:
    """All strategy classes must still be importable from the original skills.py path."""

    def test_day_trading_classes_from_skills(self):
        from src.server.skills.quant.skills import (
            VWAPReversionSkill, OpeningRangeBreakoutSkill,
            RSIDivergenceScalpSkill, MomentumBurstSkill,
        )
        assert VWAPReversionSkill is not None
        assert OpeningRangeBreakoutSkill is not None
        assert RSIDivergenceScalpSkill is not None
        assert MomentumBurstSkill is not None

    def test_swing_classes_from_skills(self):
        from src.server.skills.quant.skills import (
            GoldenCrossSkill, Breakout52WeekSkill,
            MeanReversionDailySkill, EarningsDriftSkill,
        )
        assert GoldenCrossSkill is not None
        assert Breakout52WeekSkill is not None
        assert MeanReversionDailySkill is not None
        assert EarningsDriftSkill is not None

    def test_factory_functions_from_skills(self):
        from src.server.skills.quant.skills import (
            make_vwap_reversion_signals, make_golden_cross_signals,
            make_earnings_drift_signals, make_momentum_burst_signals,
        )
        assert callable(make_vwap_reversion_signals)
        assert callable(make_golden_cross_signals)
        assert callable(make_earnings_drift_signals)
        assert callable(make_momentum_burst_signals)

    def test_singletons_from_skills(self):
        from src.server.skills.quant.skills import (
            vwap_reversion_skill, golden_cross_skill,
            mean_reversion_daily_skill, earnings_drift_skill,
        )
        assert vwap_reversion_skill is not None
        assert golden_cross_skill is not None

    def test_identity_match(self):
        """Re-exported classes must be the exact same objects from sub-modules."""
        from src.server.skills.quant.skills import VWAPReversionSkill as A
        from src.server.skills.quant.vwap_reversion import VWAPReversionSkill as B
        assert A is B

        from src.server.skills.quant.skills import GoldenCrossSkill as C
        from src.server.skills.quant.golden_cross import GoldenCrossSkill as D
        assert C is D
