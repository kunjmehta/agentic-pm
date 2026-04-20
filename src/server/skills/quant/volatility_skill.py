"""VolatilitySkill — Bollinger Bands volatility indicators."""

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


class VolatilitySkill:
    """Compute Bollinger Band volatility indicators.

    Workflow A (backtesting): ``analyze_bars(df, period, num_std)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(
        self,
        df: pd.DataFrame,
        period: int = 20,
        num_std: float = 2.0,
    ) -> Dict:
        """Calculate Bollinger Bands from a pre-fetched DataFrame.

        Args:
            df: DataFrame with a ``close`` column.
            period: SMA period. Defaults to 20.
            num_std: Number of standard deviations for the bands. Defaults to 2.

        Returns:
            Dict with upper, middle, lower (float or None) and bandwidth (%).
        """
        if len(df) < period:
            return {"upper": None, "middle": None, "lower": None, "bandwidth": None}

        middle = df["close"].rolling(window=period).mean()
        std = df["close"].rolling(window=period).std(ddof=0)
        upper = middle + std * num_std
        lower = middle - std * num_std
        bandwidth = (upper - lower) / middle * 100

        def _f(s):
            v = s.iloc[-1]
            return float(v) if not pd.isna(v) else None

        return {
            "upper": _f(upper),
            "middle": _f(middle),
            "lower": _f(lower),
            "bandwidth": _f(bandwidth),
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 90,
        period: int = 20,
        num_std: float = 2.0,
    ) -> Dict:
        """Fetch recent bars and compute Bollinger Band signals.

        Args:
            symbol: Stock ticker.
            timeframe: Bar timeframe.
            lookback_days: Calendar days of history to fetch.
            period: SMA period passed to ``analyze_bars``.
            num_std: Standard deviation multiplier passed to ``analyze_bars``.

        Returns:
            Same as ``analyze_bars`` or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe, lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, period=period, num_std=num_std)
        result["symbol"] = symbol
        result["timeframe"] = timeframe
        result["timestamp"] = datetime.now().isoformat()
        return result


# Singleton
volatility_skill = VolatilitySkill()

__all__ = ["VolatilitySkill", "volatility_skill"]


if __name__ == "__main__":
    import numpy as np

    rng = np.random.default_rng(1)
    prices = 100.0 + np.cumsum(rng.normal(0, 0.5, 40))
    df = pd.DataFrame({"close": prices})
    result = VolatilitySkill().analyze_bars(df)
    print(f"Bollinger: upper={result['upper']}, lower={result['lower']}")
    print("VolatilitySkill smoke test passed.")
