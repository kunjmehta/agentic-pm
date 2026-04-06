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
        # Session filter: keep only today's bars for intraday strategies
        if isinstance(df.index, pd.DatetimeIndex):
            if df.index.tzinfo is not None:
                today = pd.Timestamp.now(tz=df.index.tzinfo).normalize()
            else:
                today = pd.Timestamp.now().normalize()
            today_df = df[df.index >= today]
        else:
            # If no datetime index, use all data (assume already filtered to today)
            today_df = df

        # Min-bars check AFTER session filter (check today's bars only)
        if len(today_df) <= range_bars:
            return {"action": "hold", "confidence": 0.0, "reason": f"Insufficient data for opening range (need {range_bars + 1} bars today, got {len(today_df)})"}

        opening = today_df.iloc[:range_bars]
        range_high = float(opening["high"].max())
        range_low = float(opening["low"].min())
        range_size = range_high - range_low
        current = float(today_df["close"].iloc[-1])

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
            # Calculate hold confidence based on position within range
            # High confidence hold = price in middle of range
            # Low confidence hold = price near edges (almost breaking out)
            if range_size > 0:
                position_pct = (current - range_low) / range_size  # 0.0 = at low, 1.0 = at high, 0.5 = middle
                # Distance from center (0.5): 0.0 = at center, 0.5 = at edge
                distance_from_center = abs(position_pct - 0.5)
                # Convert to confidence: center = 0.8, edges = 0.2
                hold_confidence = round(0.8 - (distance_from_center * 1.2), 2)
            else:
                hold_confidence = 0.5  # Uncertain if zero range

            return {
                "action": "hold",
                "confidence": max(hold_confidence, 0.2),
                "current_price": round(current, 2),
                "reason": "Price within opening range",
                # Structured data fields
                "indicators": {
                    "range_high": round(range_high, 2),
                    "range_low": round(range_low, 2),
                    "range_size": round(range_size, 4),
                    "price_vs_high": round(current - range_high, 2),
                    "price_vs_low": round(current - range_low, 2),
                },
                "statistics": {
                    "position_in_range_pct": round(((current - range_low) / range_size * 100) if range_size > 0 else 50, 1),
                },
                "parameters": {
                    "range_bars": range_bars,
                },
            }

        return {
            "action": action,
            "confidence": confidence,
            "current_price": round(current, 2),
            "entry_price": round(entry, 2),
            "stop_loss": stop,
            "take_profit": target,
            "reason": reason,
            # Structured data fields
            "indicators": {
                "range_high": round(range_high, 2),
                "range_low": round(range_low, 2),
                "range_size": round(range_size, 4),
                "breakout_distance": round(abs(current - (range_high if action == "buy" else range_low)), 2),
            },
            "statistics": {
                "breakout_type": "bullish" if action == "buy" else "bearish",
                "breakout_strength_pct": round((abs(current - (range_high if action == "buy" else range_low)) / range_size * 100), 1),
            },
            "parameters": {
                "range_bars": range_bars,
            },
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
