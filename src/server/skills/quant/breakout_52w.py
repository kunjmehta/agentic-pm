"""Breakout52WeekSkill — 52-week high breakout with volume confirmation."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.server.skills.quant._utils import _fetch_bars
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
                "current_price": round(current, 2),
                "entry_price": round(current, 2),
                "stop_loss": stop,
                "take_profit": None,
                "reason": (
                    f"52-week breakout: close {current:.2f} > prior high {prior_high:.2f} "
                    f"({vol_ratio:.1f}× avg volume)"
                ),
                # Structured data fields
                "indicators": {
                    "prior_high_52w": round(prior_high, 2),
                    "volume_ratio": round(vol_ratio, 2),
                    "breakout_pct": round(((current - prior_high) / prior_high * 100), 2),
                },
                "statistics": {
                    "breakout_type": "52_week_high",
                    "volume_confirmation": vol_ratio >= vol_mult,
                },
                "parameters": {
                    "lookback": lookback,
                    "vol_mult": vol_mult,
                    "trail_pct": trail_pct,
                },
            }

        # Calculate hold confidence based on distance from 52-week high and volume conditions
        # High confidence hold = price far from high OR low volume (not close to breaking out)
        # Low confidence hold = price near high + elevated volume (almost breaking out)
        distance_to_high_pct = abs((prior_high - current) / current * 100)

        # Distance component: farther from high = higher confidence
        # At 10%+ from high: 1.0, at 0%: 0.0
        distance_factor = min(distance_to_high_pct / 10.0, 1.0)

        # Volume component: lower volume = higher confidence
        # At avg volume (ratio=1.0): 1.0, at threshold (vol_mult): 0.0
        if vol_ratio < 1.0:
            volume_factor = 1.0
        else:
            volume_factor = max(1.0 - (vol_ratio - 1.0) / (vol_mult - 1.0), 0.0)

        # Combine: weight distance more heavily (70/30)
        hold_confidence = round(distance_factor * 0.7 + volume_factor * 0.3, 2)

        return {
            "action": "hold",
            "confidence": max(hold_confidence, 0.2),  # Minimum 0.2
            "current_price": round(current, 2),
            "reason": "No 52-week breakout" + (
                f" (price {distance_to_high_pct:.1f}% below high)" if distance_to_high_pct > 1.0
                else " (price near 52-week high)" if current <= prior_high
                else f" (price {((current - prior_high) / prior_high * 100):.1f}% above high, low volume)"
            ),
            # Structured data fields
            "indicators": {
                "prior_high_52w": round(prior_high, 2),
                "volume_ratio": round(vol_ratio, 2),
                "distance_to_high_pct": round(distance_to_high_pct, 2),
            },
            "statistics": {
                "above_prior_high": current > prior_high,
                "volume_confirmed": vol_ratio >= vol_mult,
            },
            "parameters": {
                "lookback": lookback,
                "vol_mult": vol_mult,
                "trail_pct": trail_pct,
            },
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


def make_breakout_52w_signals(lookback: int = 252, vol_mult: float = 1.5, trail_pct: float = 0.10) -> Callable:
    """Factory: 52-week breakout signal function for backtester.

    Args:
        lookback: Prior-high scan window. Default 252.
        vol_mult: Volume multiplier. Default 1.5×.
        trail_pct: Trailing stop distance. Default 10%.

    Returns:
        Signal function ``(symbol, bars_df) -> "buy" | "sell" | "hold"``.
    """
    _skill = Breakout52WeekSkill()

    def signal_fn(symbol: str, bars_df: pd.DataFrame) -> str:
        if bars_df is None or bars_df.empty:
            return "hold"
        return _skill.analyze_bars(bars_df, lookback=lookback, vol_mult=vol_mult, trail_pct=trail_pct).get("action", "hold")

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
