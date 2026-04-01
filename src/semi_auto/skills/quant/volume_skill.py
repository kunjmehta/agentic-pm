"""VolumeSkill — On-Balance Volume (OBV) and volume flow indicators."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.semi_auto.skills.quant._utils import _fetch_bars
from src.common.utils import get_logger

logger = get_logger(__name__)


class VolumeSkill:
    """Compute On-Balance Volume (OBV) and volume flow indicators.

    Workflow A (backtesting): ``analyze_bars(df)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(self, df: pd.DataFrame) -> Dict:
        """Calculate OBV and volume trends from a pre-fetched DataFrame.

        Args:
            df: DataFrame with ``close`` and ``volume`` columns.

        Returns:
            Dict with obv, volume_trend, avg_volume_10d, current_vs_avg.
        """
        if len(df) < 2:
            return {
                "obv": None,
                "volume_trend": None,
                "avg_volume_10d": None,
                "current_vs_avg": None,
            }

        obv = [0]
        for i in range(1, len(df)):
            if df["close"].iloc[i] > df["close"].iloc[i - 1]:
                obv.append(obv[-1] + df["volume"].iloc[i])
            elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
                obv.append(obv[-1] - df["volume"].iloc[i])
            else:
                obv.append(obv[-1])

        trend = "unknown"
        if len(df) >= 10:
            recent = df["volume"].iloc[-5:].mean()
            previous = df["volume"].iloc[-10:-5].mean()
            trend = "increasing" if recent > previous else "decreasing"

        avg_vol = df["volume"].tail(10).mean() if len(df) >= 10 else None
        current_vs_avg = None
        if avg_vol and avg_vol > 0:
            current_vs_avg = float(round(df["volume"].iloc[-1] / avg_vol, 2))

        return {
            "obv": int(obv[-1]) if obv else None,
            "volume_trend": trend,
            "avg_volume_10d": int(avg_vol) if avg_vol else None,
            "current_vs_avg": current_vs_avg,
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 90,
    ) -> Dict:
        """Fetch recent bars and compute OBV / volume flow signals.

        Args:
            symbol: Stock ticker.
            timeframe: Bar timeframe.
            lookback_days: Calendar days of history to fetch.

        Returns:
            Same as ``analyze_bars`` or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe, lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df)
        result["symbol"] = symbol
        result["timeframe"] = timeframe
        result["timestamp"] = datetime.now().isoformat()
        return result


# Singleton
volume_skill = VolumeSkill()


def calc_volume_flow(df: pd.DataFrame) -> Dict:
    """Legacy alias: delegate to VolumeSkill.analyze_bars."""
    return volume_skill.analyze_bars(df)


__all__ = ["VolumeSkill", "volume_skill", "calc_volume_flow"]


if __name__ == "__main__":
    import numpy as np

    rng = np.random.default_rng(2)
    prices = 100.0 + np.cumsum(rng.normal(0, 0.3, 30))
    vols = rng.integers(1000, 5000, 30).astype(float)
    df = pd.DataFrame({"close": prices, "volume": vols})
    result = VolumeSkill().analyze_bars(df)
    print(f"OBV: {result['obv']}, trend: {result['volume_trend']}")
    print("VolumeSkill smoke test passed.")
