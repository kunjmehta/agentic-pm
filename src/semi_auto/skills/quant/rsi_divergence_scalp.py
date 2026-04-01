"""RSIDivergenceScalpSkill — bullish RSI divergence from oversold."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.semi_auto.skills.quant._utils import _fetch_bars
from src.common.utils import get_logger

logger = get_logger(__name__)


class RSIDivergenceScalpSkill:
    """RSI Divergence Scalp — price makes new low but RSI does not (bullish divergence).

    Signal: in the last ``lookback`` bars, price makes a lower low while RSI makes
    a higher low AND RSI is in the oversold zone (< ``oversold``).
    Entry: market.
    Stop: price low.
    Target: 2:1 reward-to-risk from entry.

    Workflow A (backtesting): ``analyze_bars(df, ...)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(
        self,
        df: pd.DataFrame,
        lookback: int = 20,
        oversold: float = 35.0,
        rsi_period: int = 14,
    ) -> Dict:
        """Compute RSI divergence scalp signal.

        Args:
            df: OHLCV DataFrame sorted oldest-first.
            lookback: Bars to scan for divergence. Default 20.
            oversold: RSI oversold threshold. Default 35.
            rsi_period: RSI period. Default 14.

        Returns:
            Dict with action, confidence, current_rsi, reason, entry/stop/target.
        """
        min_len = rsi_period + lookback
        if len(df) < min_len:
            return {"action": "hold", "confidence": 0.0, "reason": "Insufficient data"}

        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / rsi_period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / rsi_period, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        window_price = df["close"].iloc[-lookback:]
        window_rsi = rsi.iloc[-lookback:]

        if window_price.empty or window_rsi.empty:
            return {"action": "hold", "confidence": 0.0, "reason": "Insufficient window data"}

        price_min_idx = window_price.idxmin()
        rsi_at_price_min = (
            float(window_rsi.loc[price_min_idx]) if price_min_idx in window_rsi.index else None
        )
        current_price = float(df["close"].iloc[-1])
        current_rsi = float(rsi.iloc[-1])

        if (
            rsi_at_price_min is not None
            and current_rsi < oversold
            and current_rsi > rsi_at_price_min
            and current_price <= float(window_price.min()) * 1.005
        ):
            price_low = float(window_price.min())
            risk = current_price - price_low
            target = current_price + 2 * risk if risk > 0 else current_price * 1.01
            confidence = round(min((oversold - current_rsi) / oversold, 1.0), 2)
            return {
                "action": "buy",
                "confidence": confidence,
                "current_rsi": round(current_rsi, 2),
                "rsi_at_prior_low": round(rsi_at_price_min, 2),
                "current_price": round(current_price, 2),
                "entry_price": round(current_price, 2),
                "stop_loss": round(price_low * 0.998, 2),
                "take_profit": round(target, 2),
                "reason": (
                    f"Bullish RSI divergence: price near low {price_low:.2f}, "
                    f"RSI {current_rsi:.1f} > prior low RSI {rsi_at_price_min:.1f}"
                ),
            }

        return {
            "action": "hold",
            "confidence": 0.0,
            "current_rsi": round(current_rsi, 2),
            "current_price": round(current_price, 2),
            "reason": "No RSI divergence detected",
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Min",
        lookback_days: int = 5,
        lookback: int = 20,
        oversold: float = 35.0,
    ) -> Dict:
        """Fetch bars and compute RSI divergence scalp signal.

        Args:
            symbol: Stock ticker.
            timeframe: Bar resolution. Defaults to ``"1Min"``.
            lookback_days: Calendar days to fetch. Default 5.
            lookback: Bars to scan for divergence.
            oversold: RSI oversold threshold.

        Returns:
            Signal dict or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, lookback=lookback, oversold=oversold)
        result.update({"symbol": symbol, "timeframe": timeframe, "timestamp": datetime.now().isoformat()})
        return result


# Singleton
rsi_divergence_scalp_skill = RSIDivergenceScalpSkill()


def make_rsi_divergence_signals(lookback: int = 20, oversold: float = 35.0) -> Callable:
    """Factory: RSI divergence scalp signal function for backtester.

    Args:
        lookback: Bars to scan for divergence. Default 20.
        oversold: RSI oversold threshold. Default 35.

    Returns:
        Signal function ``(symbol, bars_df) -> "buy" | "sell" | "hold"``.
    """
    _skill = RSIDivergenceScalpSkill()

    def signal_fn(symbol: str, bars_df: pd.DataFrame) -> str:
        if bars_df is None or bars_df.empty:
            return "hold"
        return _skill.analyze_bars(bars_df, lookback=lookback, oversold=oversold).get("action", "hold")

    return signal_fn


__all__ = [
    "RSIDivergenceScalpSkill",
    "rsi_divergence_scalp_skill",
    "make_rsi_divergence_signals",
]
