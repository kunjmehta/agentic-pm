"""CandlestickSkill — candlestick pattern detection."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.server.skills.quant._utils import _fetch_bars
from src.common.utils import get_logger

logger = get_logger(__name__)


class CandlestickSkill:
    """Detect candlestick patterns in recent price data.

    Detects: bullish/bearish engulfing, doji, hammer, hanging man.

    Workflow A (backtesting): ``analyze_bars(df, lookback)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(self, df: pd.DataFrame, lookback: int = 5) -> Dict:
        """Detect candlestick patterns in the last *lookback* bars.

        Args:
            df: DataFrame with ``open``, ``high``, ``low``, ``close`` columns.
            lookback: Number of recent candles to analyse.

        Returns:
            Dict with patterns (list), last_candle_type, last_body_pct, pattern_count.
        """
        if len(df) < 2:
            return {
                "patterns": [],
                "last_candle_type": None,
                "last_body_pct": None,
                "pattern_count": 0,
            }

        patterns = []
        recent = df.tail(lookback) if len(df) >= lookback else df

        for i in range(1, len(recent)):
            cur = recent.iloc[i]
            prev = recent.iloc[i - 1]
            body = abs(cur["close"] - cur["open"])
            upper_shadow = cur["high"] - max(cur["open"], cur["close"])
            lower_shadow = min(cur["open"], cur["close"]) - cur["low"]
            total_range = cur["high"] - cur["low"]
            if total_range == 0:
                continue
            if (
                prev["close"] < prev["open"]
                and cur["close"] > cur["open"]
                and cur["open"] <= prev["close"]
                and cur["close"] >= prev["open"]
            ):
                patterns.append("bullish_engulfing")
            if (
                prev["close"] > prev["open"]
                and cur["close"] < cur["open"]
                and cur["open"] >= prev["close"]
                and cur["close"] <= prev["open"]
            ):
                patterns.append("bearish_engulfing")
            if body / total_range < 0.1:
                patterns.append("doji")
            if lower_shadow > 2 * body and upper_shadow < body:
                patterns.append("hammer")
                if i > len(recent) / 2:
                    patterns.append("hanging_man")

        last = recent.iloc[-1]
        last_body = abs(last["close"] - last["open"])
        last_range = last["high"] - last["low"]
        last_type = (
            "bullish" if last["close"] > last["open"]
            else "bearish" if last["close"] < last["open"]
            else "neutral"
        )
        last_body_pct = (last_body / last_range * 100) if last_range > 0 else 0

        return {
            "patterns": list(set(patterns)),
            "last_candle_type": last_type,
            "last_body_pct": round(float(last_body_pct), 1),
            "pattern_count": len(set(patterns)),
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 30,
        lookback: int = 5,
    ) -> Dict:
        """Fetch recent bars and detect candlestick patterns.

        Args:
            symbol: Stock ticker.
            timeframe: Bar timeframe.
            lookback_days: Calendar days of history to fetch.
            lookback: Number of recent candles to pattern-check.

        Returns:
            Same as ``analyze_bars`` or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe, lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, lookback=lookback)
        result["symbol"] = symbol
        result["timeframe"] = timeframe
        result["timestamp"] = datetime.now().isoformat()
        return result


# Singleton
candlestick_skill = CandlestickSkill()


def analyze_candle_structure(df: pd.DataFrame, lookback: int = 5) -> Dict:
    """Legacy alias: delegate to CandlestickSkill.analyze_bars."""
    return candlestick_skill.analyze_bars(df, lookback=lookback)


__all__ = ["CandlestickSkill", "candlestick_skill", "analyze_candle_structure"]


if __name__ == "__main__":
    import numpy as np

    rng = np.random.default_rng(3)
    n = 20
    prices = 100.0 + np.cumsum(rng.normal(0, 0.3, n))
    df = pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.003,
        "low": prices * 0.997,
        "close": prices,
    })
    result = CandlestickSkill().analyze_bars(df)
    print(f"Patterns: {result['patterns']}, type: {result['last_candle_type']}")
    print("CandlestickSkill smoke test passed.")
