"""RSIDivergenceScalpSkill — bullish RSI divergence from oversold."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.server.skills.quant._utils import _fetch_bars
from src.common.utils import get_logger

logger = get_logger(__name__)


class RSIDivergenceScalpSkill:
    """RSI Divergence Scalp — bullish and bearish RSI divergences.

    Bullish divergence: price makes new low but RSI makes higher low (RSI < ``oversold``).
    Bearish divergence: price makes new high but RSI makes lower high (RSI > ``overbought``).
    Entry: market.
    Stop: price extreme (low for buy, high for sell).
    Target: 2:1 reward-to-risk from entry.

    Workflow A (backtesting): ``analyze_bars(df, ...)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(
        self,
        df: pd.DataFrame,
        lookback: int = 20,
        oversold: float = 35.0,
        overbought: float = 65.0,
        rsi_period: int = 14,
    ) -> Dict:
        """Compute RSI divergence scalp signal (bullish and bearish).

        Args:
            df: OHLCV DataFrame sorted oldest-first.
            lookback: Bars to scan for divergence. Default 20.
            oversold: RSI oversold threshold for bullish divergence. Default 35.
            overbought: RSI overbought threshold for bearish divergence. Default 65.
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
        rs = gain / loss.where(loss != 0, np.nan)
        rsi = (100 - (100 / (1 + rs))).fillna(100)

        window_price = df["close"].iloc[-lookback:]
        window_rsi = rsi.iloc[-lookback:]

        if window_price.empty or window_rsi.empty:
            return {"action": "hold", "confidence": 0.0, "reason": "Insufficient window data"}

        current_price = float(df["close"].iloc[-1])
        current_rsi = float(rsi.iloc[-1])

        # Check for bullish divergence (price lower low + RSI higher low in oversold)
        price_min_idx = window_price.idxmin()
        rsi_at_price_min = (
            float(window_rsi.loc[price_min_idx]) if price_min_idx in window_rsi.index else None
        )

        if (
            rsi_at_price_min is not None
            and current_rsi < oversold
            and current_rsi > rsi_at_price_min
            and current_price <= float(window_price.min()) * 1.005
        ):
            price_low = float(window_price.min())
            risk = current_price - price_low
            target = current_price + 2 * risk if risk > 0 else current_price * 1.01
            confidence = round(min((oversold - current_rsi) / (oversold * 0.5), 1.0), 2)
            return {
                "action": "buy",
                "confidence": confidence,
                "current_price": round(current_price, 2),
                "entry_price": round(current_price, 2),
                "stop_loss": round(price_low * 0.998, 2),
                "take_profit": round(target, 2),
                "reason": (
                    f"Bullish RSI divergence: price near low {price_low:.2f}, "
                    f"RSI {current_rsi:.1f} > prior low RSI {rsi_at_price_min:.1f}"
                ),
                "indicators": {
                    "current_rsi": round(current_rsi, 2),
                    "rsi_at_prior_extreme": round(rsi_at_price_min, 2),
                    "rsi_divergence": round(current_rsi - rsi_at_price_min, 2),
                    "price_extreme": round(price_low, 2),
                },
                "statistics": {
                    "divergence_type": "bullish",
                    "rsi_improvement": round(current_rsi - rsi_at_price_min, 2),
                    "price_vs_extreme_pct": round(((current_price / price_low) - 1) * 100, 3),
                },
                "parameters": {
                    "lookback": lookback,
                    "oversold": oversold,
                    "overbought": overbought,
                    "rsi_period": rsi_period,
                },
            }

        # Check for bearish divergence (price higher high + RSI lower high in overbought)
        price_max_idx = window_price.idxmax()
        rsi_at_price_max = (
            float(window_rsi.loc[price_max_idx]) if price_max_idx in window_rsi.index else None
        )

        if (
            rsi_at_price_max is not None
            and current_rsi > overbought
            and current_rsi < rsi_at_price_max
            and current_price >= float(window_price.max()) * 0.995
        ):
            price_high = float(window_price.max())
            risk = price_high - current_price
            target = current_price - 2 * risk if risk > 0 else current_price * 0.99
            # Confidence scaling: saturates at distance above overbought
            # At RSI=65 (overbought): 0.0, at RSI=82.5: 1.0
            confidence = round(min((current_rsi - overbought) / ((100 - overbought) * 0.5), 1.0), 2)
            return {
                "action": "sell",
                "confidence": confidence,
                "current_price": round(current_price, 2),
                "entry_price": round(current_price, 2),
                "stop_loss": round(price_high * 1.002, 2),
                "take_profit": round(target, 2),
                "reason": (
                    f"Bearish RSI divergence: price near high {price_high:.2f}, "
                    f"RSI {current_rsi:.1f} < prior high RSI {rsi_at_price_max:.1f}"
                ),
                "indicators": {
                    "current_rsi": round(current_rsi, 2),
                    "rsi_at_prior_extreme": round(rsi_at_price_max, 2),
                    "rsi_divergence": round(rsi_at_price_max - current_rsi, 2),
                    "price_extreme": round(price_high, 2),
                },
                "statistics": {
                    "divergence_type": "bearish",
                    "rsi_deterioration": round(rsi_at_price_max - current_rsi, 2),
                    "price_vs_extreme_pct": round(((current_price / price_high) - 1) * 100, 3),
                },
                "parameters": {
                    "lookback": lookback,
                    "oversold": oversold,
                    "overbought": overbought,
                    "rsi_period": rsi_period,
                },
            }

        # Calculate hold confidence based on RSI position
        # High confidence hold = RSI in neutral zone (40-60)
        # Low confidence hold = RSI near extreme zones but no divergence
        if current_rsi >= 40 and current_rsi <= 60:
            # Neutral zone - high confidence hold
            hold_confidence = 0.8
        elif current_rsi > oversold and current_rsi < overbought:
            # Between neutral and extreme zones - medium confidence
            distance_from_neutral = min(abs(current_rsi - 40), abs(current_rsi - 60))
            hold_confidence = round(0.5 + min(distance_from_neutral / 15, 0.3), 2)
        else:
            # At/below oversold or at/above overbought but no divergence
            hold_confidence = 0.3

        return {
            "action": "hold",
            "confidence": hold_confidence,
            "current_price": round(current_price, 2),
            "reason": "No RSI divergence detected",
            # Structured data fields
            "indicators": {
                "current_rsi": round(current_rsi, 2),
            },
            "statistics": {},
            "parameters": {
                "lookback": lookback,
                "oversold": oversold,
                "overbought": overbought,
                "rsi_period": rsi_period,
            },
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Min",
        lookback_days: int = 5,
        lookback: int = 20,
        oversold: float = 35.0,
        overbought: float = 65.0,
        rsi_period: int = 14,
    ) -> Dict:
        """Fetch bars and compute RSI divergence scalp signal.

        Args:
            symbol: Stock ticker.
            timeframe: Bar resolution. Defaults to ``"1Min"``.
            lookback_days: Calendar days to fetch. Default 5.
            lookback: Bars to scan for divergence.
            oversold: RSI oversold threshold for bullish divergence.
            overbought: RSI overbought threshold for bearish divergence.
            rsi_period: RSI period. Default 14.

        Returns:
            Signal dict or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, lookback=lookback, oversold=oversold, overbought=overbought, rsi_period=rsi_period)
        result.update({"symbol": symbol, "timeframe": timeframe, "timestamp": datetime.now().isoformat()})
        return result


# Singleton
rsi_divergence_scalp_skill = RSIDivergenceScalpSkill()


def make_rsi_divergence_signals(lookback: int = 20, oversold: float = 35.0, overbought: float = 65.0, rsi_period: int = 14) -> Callable:
    """Factory: RSI divergence scalp signal function for backtester.

    Args:
        lookback: Bars to scan for divergence. Default 20.
        oversold: RSI oversold threshold for bullish divergence. Default 35.
        overbought: RSI overbought threshold for bearish divergence. Default 65.
        rsi_period: RSI period. Default 14.

    Returns:
        Signal function ``(symbol, bars_df) -> "buy" | "sell" | "hold"``.
    """
    _skill = RSIDivergenceScalpSkill()

    def signal_fn(symbol: str, bars_df: pd.DataFrame) -> str:
        if bars_df is None or bars_df.empty:
            return "hold"
        return _skill.analyze_bars(bars_df, lookback=lookback, oversold=oversold, overbought=overbought, rsi_period=rsi_period).get("action", "hold")

    return signal_fn


__all__ = [
    "RSIDivergenceScalpSkill",
    "rsi_divergence_scalp_skill",
    "make_rsi_divergence_signals",
]
