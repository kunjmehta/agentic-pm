"""MomentumSkill — MACD + RSI momentum indicators."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.server.skills.quant._utils import _fetch_bars
from src.common.utils import get_logger

logger = get_logger(__name__)


class MomentumSkill:
    """Compute MACD and RSI momentum indicators.

    Workflow A (backtesting): call ``analyze_bars(df)`` with a pre-fetched DataFrame.
    Workflow B (signal generation): call ``generate_signals(symbol, ...)`` which fetches
    bars automatically.
    """

    def analyze_bars(self, df: pd.DataFrame) -> Dict:
        """Calculate MACD and RSI from a pre-fetched DataFrame.

        Requires at least 26 rows for MACD and 14 rows for RSI.

        Args:
            df: DataFrame with a ``close`` column.

        Returns:
            Dict with keys: macd (value/signal/histogram or None), rsi (float or None).
        """
        if len(df) < 26:
            return {"macd": None, "rsi": None}

        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line

        rsi = None
        if len(df) >= 14:
            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / 14, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / 14, adjust=False).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi_series = 100 - (100 / (1 + rs))
            rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None

        def _f(series):
            v = series.iloc[-1]
            return float(v) if not pd.isna(v) else None

        return {
            "macd": {
                "value": _f(macd_line),
                "signal": _f(signal_line),
                "histogram": _f(histogram),
            },
            "rsi": rsi,
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 90,
    ) -> Dict:
        """Fetch recent bars and compute MACD + RSI signals.

        Args:
            symbol: Stock ticker.
            timeframe: Bar timeframe (AlpacaDAO canonical string).
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
momentum_skill = MomentumSkill()

__all__ = ["MomentumSkill", "momentum_skill"]


if __name__ == "__main__":
    import numpy as np

    rng = np.random.default_rng(0)
    n = 50
    prices = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({"close": prices})
    result = MomentumSkill().analyze_bars(df)
    print(f"MACD: {result['macd']}, RSI: {result['rsi']}")
    print("MomentumSkill smoke test passed.")
