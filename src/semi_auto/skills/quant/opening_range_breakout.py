"""OpeningRangeBreakoutSkill — first N-minute high/low channel break."""

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


class OpeningRangeBreakoutSkill:
    """Opening Range Breakout — first N-minute high/low channel break.

    Signal: bar close breaks above the opening range high (buy) or below low (sell).
    Target: 2× the range distance from breakout.
    Stop: opposite side of the range.

    Workflow A (backtesting): ``analyze_bars(df, ...)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(self, df: pd.DataFrame, range_bars: int = 15) -> Dict:
        """Compute opening range breakout signal.

        Args:
            df: Intraday OHLCV DataFrame, sorted oldest-first.
            range_bars: Number of bars that define the opening range. Default 15.

        Returns:
            Dict with action, confidence, range_high, range_low, current_price,
            entry_price, stop_loss, take_profit, reason.
        """
        if len(df) <= range_bars:
            return {"action": "hold", "confidence": 0.0, "reason": "Insufficient data for opening range"}

        opening = df.iloc[:range_bars]
        range_high = float(opening["high"].max())
        range_low = float(opening["low"].min())
        range_size = range_high - range_low
        current = float(df["close"].iloc[-1])

        if range_size <= 0:
            return {"action": "hold", "confidence": 0.0, "reason": "Zero opening range"}

        if current > range_high:
            action = "buy"
            entry = current
            stop = round(range_low, 2)
            target = round(range_high + 2 * range_size, 2)
            confidence = round(min((current - range_high) / range_size * 2, 1.0), 2)
            reason = f"Price broke above opening range high {range_high:.2f}"
        elif current < range_low:
            action = "sell"
            entry = current
            stop = round(range_high, 2)
            target = round(range_low - 2 * range_size, 2)
            confidence = round(min((range_low - current) / range_size * 2, 1.0), 2)
            reason = f"Price broke below opening range low {range_low:.2f}"
        else:
            return {
                "action": "hold",
                "confidence": 0.0,
                "range_high": round(range_high, 2),
                "range_low": round(range_low, 2),
                "current_price": round(current, 2),
                "reason": "Price within opening range",
            }

        return {
            "action": action,
            "confidence": confidence,
            "range_high": round(range_high, 2),
            "range_low": round(range_low, 2),
            "current_price": round(current, 2),
            "range_size": round(range_size, 4),
            "entry_price": round(entry, 2),
            "stop_loss": stop,
            "take_profit": target,
            "reason": reason,
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Min",
        lookback_days: int = 2,
        range_bars: int = 15,
    ) -> Dict:
        """Fetch intraday bars and compute opening range breakout signal.

        Args:
            symbol: Stock ticker.
            timeframe: Bar resolution. Defaults to ``"1Min"``.
            lookback_days: Calendar days to fetch. Default 2.
            range_bars: Opening range bar count.

        Returns:
            Signal dict or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, range_bars=range_bars)
        result.update({"symbol": symbol, "timeframe": timeframe, "timestamp": datetime.now().isoformat()})
        return result


# Singleton
opening_range_breakout_skill = OpeningRangeBreakoutSkill()


def make_opening_range_breakout_signals(range_bars: int = 15) -> Callable:
    """Factory: Opening range breakout signal function for backtester.

    Args:
        range_bars: Number of bars defining the opening range. Default 15.

    Returns:
        Signal function ``(symbol, bars_df) -> "buy" | "sell" | "hold"``.
    """
    _skill = OpeningRangeBreakoutSkill()

    def signal_fn(symbol: str, bars_df: pd.DataFrame) -> str:
        if bars_df is None or bars_df.empty:
            return "hold"
        return _skill.analyze_bars(bars_df, range_bars=range_bars).get("action", "hold")

    return signal_fn


__all__ = [
    "OpeningRangeBreakoutSkill",
    "opening_range_breakout_skill",
    "make_opening_range_breakout_signals",
]
