"""Breakout52WeekSkill — 52-week high breakout with volume confirmation."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.semi_auto.skills.quant._utils import _fetch_bars
from src.common.utils import get_logger

logger = get_logger(__name__)


class Breakout52WeekSkill:
    """52-Week High Breakout — close above the 52-week high with volume confirmation.

    Signal: today's close > max close of preceding ``lookback`` trading days AND
    volume > ``vol_mult`` × 20-day average.
    Stop: trailing ``trail_pct`` from entry.

    Workflow A (backtesting): ``analyze_bars(df, ...)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(
        self,
        df: pd.DataFrame,
        lookback: int = 252,
        vol_mult: float = 1.5,
        trail_pct: float = 0.10,
    ) -> Dict:
        """Compute 52-week breakout signal.

        Args:
            df: Daily OHLCV DataFrame sorted oldest-first.
            lookback: Bar window for the prior high (252 = ~1 year). Default 252.
            vol_mult: Minimum volume vs 20-day average. Default 1.5×.
            trail_pct: Trailing stop distance from entry. Default 10%.

        Returns:
            Dict with action, confidence, prior_high, current_price, entry/stop/reason.
        """
        min_len = max(lookback + 1, 21)
        if len(df) < min_len:
            return {"action": "hold", "confidence": 0.0, "reason": f"Need ≥ {min_len} bars"}

        current = float(df["close"].iloc[-1])
        prior_high = float(df["close"].iloc[-(lookback + 1):-1].max())
        cur_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].iloc[-21:-1].mean())
        vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0.0

        if current > prior_high and vol_ratio >= vol_mult:
            confidence = round(
                min(((current - prior_high) / prior_high * 100) + (vol_ratio / (vol_mult * 4)), 1.0), 2
            )
            stop = round(current * (1 - trail_pct), 2)
            return {
                "action": "buy",
                "confidence": confidence,
                "prior_high": round(prior_high, 2),
                "current_price": round(current, 2),
                "volume_ratio": round(vol_ratio, 2),
                "entry_price": round(current, 2),
                "stop_loss": stop,
                "take_profit": None,
                "reason": (
                    f"52-week breakout: close {current:.2f} > prior high {prior_high:.2f} "
                    f"({vol_ratio:.1f}× avg volume)"
                ),
            }

        return {
            "action": "hold",
            "confidence": 0.0,
            "prior_high": round(prior_high, 2),
            "current_price": round(current, 2),
            "volume_ratio": round(vol_ratio, 2),
            "reason": "No 52-week breakout",
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 400,
        lookback: int = 252,
        vol_mult: float = 1.5,
        trail_pct: float = 0.10,
    ) -> Dict:
        """Fetch daily bars and compute 52-week breakout signal.

        Args:
            symbol: Stock ticker.
            timeframe: Bar resolution. Defaults to ``"1Day"``.
            lookback_days: Calendar days to fetch. Default 400.
            lookback: Prior-high scan window.
            vol_mult: Volume multiplier.
            trail_pct: Trailing stop.

        Returns:
            Signal dict or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, lookback=lookback, vol_mult=vol_mult, trail_pct=trail_pct)
        result.update({"symbol": symbol, "timeframe": timeframe, "timestamp": datetime.now().isoformat()})
        return result


# Singleton
breakout_52w_skill = Breakout52WeekSkill()


def make_breakout_52w_signals(lookback: int = 252, vol_mult: float = 1.5) -> Callable:
    """Factory: 52-week breakout signal function for backtester.

    Args:
        lookback: Prior-high scan window. Default 252.
        vol_mult: Volume multiplier. Default 1.5×.

    Returns:
        Signal function ``(symbol, bars_df) -> "buy" | "sell" | "hold"``.
    """
    _skill = Breakout52WeekSkill()

    def signal_fn(symbol: str, bars_df: pd.DataFrame) -> str:
        if bars_df is None or bars_df.empty:
            return "hold"
        return _skill.analyze_bars(bars_df, lookback=lookback, vol_mult=vol_mult).get("action", "hold")

    return signal_fn


__all__ = ["Breakout52WeekSkill", "breakout_52w_skill", "make_breakout_52w_signals"]


if __name__ == "__main__":
    import numpy as np

    print("--- Breakout52WeekSkill smoke test ---")
    rng = np.random.default_rng(42)
    n = 300
    prices = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    volumes = rng.integers(100_000, 500_000, n).astype(float)
    df = pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": volumes,
    })
    r = Breakout52WeekSkill().analyze_bars(df)
    print(f"action={r['action']}, confidence={r.get('confidence')}")
    fn = make_breakout_52w_signals()
    print(f"factory: {fn('TEST', df)}")
    print("OK")
