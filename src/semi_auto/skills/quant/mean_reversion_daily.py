"""MeanReversionDailySkill — MeanReversionSkill configured for daily bars."""

import sys
from pathlib import Path
from typing import Callable, Dict

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)


class MeanReversionDailySkill:
    """Daily mean reversion — ``MeanReversionSkill`` logic configured for 1Day bars.

    Uses daily-appropriate defaults: shorter lookback (20 bars ≈ 1 month),
    higher threshold (2.5σ), and ``timeframe="1Day"``.

    Delegates to a lazily-imported ``MeanReversionSkill`` instance to avoid a
    circular import between this module and ``skills.py``.

    Workflow A (backtesting): ``analyze_bars(df, ...)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def __init__(self) -> None:
        self._delegate = None  # lazy init

    def _get_delegate(self):
        if self._delegate is None:
            from src.semi_auto.skills.quant.mean_reversion import MeanReversionSkill
            self._delegate = MeanReversionSkill()
        return self._delegate

    def analyze_bars(
        self,
        df: pd.DataFrame,
        lookback: int = 20,
        threshold: float = 2.5,
        ma_period: int = 20,
    ) -> Dict:
        """Run MeanReversionSkill analysis with daily defaults.

        Args:
            df: Daily OHLCV DataFrame sorted oldest-first.
            lookback: Number of bars for statistics. Default 20.
            threshold: Z-score entry threshold. Default 2.5.
            ma_period: Moving average period. Default 20.

        Returns:
            Full MeanReversionSkill analysis dict.
        """
        return self._get_delegate().analyze_bars(
            df, lookback=lookback, threshold=threshold, ma_period=ma_period
        )

    def generate_signals(
        self,
        symbol: str,
        lookback: int = 20,
        threshold: float = 2.5,
        ma_period: int = 20,
        timeframe: str = "1Day",
        sr_lookback: int = 60,
    ) -> Dict:
        """Fetch daily bars and run mean-reversion analysis.

        Args:
            symbol: Stock ticker.
            lookback: Number of daily bars for statistics. Default 20.
            threshold: Z-score entry threshold. Default 2.5.
            ma_period: Moving average period. Default 20.
            timeframe: Bar resolution. Defaults to ``"1Day"``.
            sr_lookback: Bars to scan for support/resistance. Default 60.

        Returns:
            Full analysis dict or ``{"error": "..."}`` on failure.
        """
        return self._get_delegate().generate_signals(
            symbol=symbol,
            lookback=lookback,
            threshold=threshold,
            ma_period=ma_period,
            timeframe=timeframe,
            sr_lookback=sr_lookback,
        )


# Singleton
mean_reversion_daily_skill = MeanReversionDailySkill()


def make_mean_reversion_daily_signals(lookback: int = 20, threshold: float = 2.5) -> Callable:
    """Factory: Daily mean reversion signal function for backtester.

    Args:
        lookback: Daily bar window. Default 20.
        threshold: Z-score threshold. Default 2.5.

    Returns:
        Signal function ``(symbol, bars_df) -> "buy" | "sell" | "hold"``.
    """
    _skill = MeanReversionDailySkill()

    def signal_fn(symbol: str, bars_df: pd.DataFrame) -> str:
        if bars_df is None or bars_df.empty:
            return "hold"
        result = _skill.analyze_bars(bars_df, lookback=lookback, threshold=threshold)
        return result.get("trade_recommendation", {}).get("action", "hold")

    return signal_fn


__all__ = ["MeanReversionDailySkill", "mean_reversion_daily_skill", "make_mean_reversion_daily_signals"]


if __name__ == "__main__":
    import numpy as np

    print("--- MeanReversionDailySkill smoke test ---")
    rng = np.random.default_rng(99)
    n = 60
    prices = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    volumes = rng.integers(100_000, 500_000, n).astype(float)
    df = pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": volumes,
    })
    skill = MeanReversionDailySkill()
    r = skill.analyze_bars(df)
    rec = r.get("trade_recommendation", {})
    print(f"action={rec.get('action')}, confidence={rec.get('confidence')}")
    fn = make_mean_reversion_daily_signals()
    print(f"factory: {fn('TEST', df)}")
    print("OK")
