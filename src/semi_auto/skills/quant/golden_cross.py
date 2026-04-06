"""GoldenCrossSkill — 50 SMA / 200 SMA crossover on daily bars."""

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


class GoldenCrossSkill:
    """Golden / Death Cross — 50 SMA vs 200 SMA crossover on daily bars.

    Signal: 50 SMA crosses above 200 SMA (golden cross → buy) or below (death cross → sell).
    Confidence: proportional to the spread between SMAs.

    Workflow A (backtesting): ``analyze_bars(df, ...)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(self, df: pd.DataFrame, fast: int = 50, slow: int = 200) -> Dict:
        """Compute golden/death cross signal.

        Args:
            df: Daily OHLCV DataFrame sorted oldest-first. Needs at least ``slow + 1`` bars.
            fast: Fast SMA period. Default 50.
            slow: Slow SMA period. Default 200.

        Returns:
            Dict with action, confidence, sma_fast, sma_slow, spread_pct, reason,
            current_price.
        """
        if len(df) < slow + 1:
            return {"action": "hold", "confidence": 0.0, "reason": f"Need ≥ {slow + 1} bars"}

        closes = df["close"]
        sma_fast = closes.rolling(fast).mean()
        sma_slow = closes.rolling(slow).mean()

        cur_fast = float(sma_fast.iloc[-1])
        cur_slow = float(sma_slow.iloc[-1])
        prev_fast = float(sma_fast.iloc[-2])
        prev_slow = float(sma_slow.iloc[-2])
        current_price = float(closes.iloc[-1])
        spread_pct = (cur_fast - cur_slow) / cur_slow * 100 if cur_slow > 0 else 0.0

        if prev_fast <= prev_slow and cur_fast > cur_slow:
            # Confidence: at exact crossover spread_pct ≈ 0, so use minimum base confidence
            # then add spread for stronger signals
            base_confidence = 0.6  # Base confidence for crossover signal itself
            spread_bonus = min(abs(spread_pct) / 3.0, 0.4)  # Up to 0.4 extra for wider spread
            confidence = round(base_confidence + spread_bonus, 2)

            # Stop and target based on current price
            stop = round(cur_slow * 0.98, 2)  # 2% below slow SMA
            target = round(current_price * 1.05, 2)  # 5% profit target

            return {
                "action": "buy",
                "confidence": confidence,
                "sma_fast": round(cur_fast, 2),
                "sma_slow": round(cur_slow, 2),
                "spread_pct": round(spread_pct, 3),
                "current_price": round(current_price, 2),
                "entry_price": round(current_price, 2),
                "stop_loss": stop,
                "take_profit": target,
                "reason": f"Golden cross: {fast}SMA ({cur_fast:.2f}) crossed above {slow}SMA ({cur_slow:.2f})",
                # Structured data fields
                "indicators": {
                    "sma_fast": round(cur_fast, 2),
                    "sma_slow": round(cur_slow, 2),
                    "spread_pct": round(spread_pct, 3),
                },
                "statistics": {
                    "crossover_type": "golden",
                    "sma_spread": round(cur_fast - cur_slow, 2),
                },
                "parameters": {
                    "fast": fast,
                    "slow": slow,
                },
            }

        if prev_fast >= prev_slow and cur_fast < cur_slow:
            # Confidence: same logic as golden cross
            base_confidence = 0.6  # Base confidence for crossover signal itself
            spread_bonus = min(abs(spread_pct) / 3.0, 0.4)  # Up to 0.4 extra for wider spread
            confidence = round(base_confidence + spread_bonus, 2)

            # Stop and target based on current price
            stop = round(cur_slow * 1.02, 2)  # 2% above slow SMA
            target = round(current_price * 0.95, 2)  # 5% profit target (for short)

            return {
                "action": "sell",
                "confidence": confidence,
                "sma_fast": round(cur_fast, 2),
                "sma_slow": round(cur_slow, 2),
                "spread_pct": round(spread_pct, 3),
                "current_price": round(current_price, 2),
                "entry_price": round(current_price, 2),
                "stop_loss": stop,
                "take_profit": target,
                "reason": f"Death cross: {fast}SMA ({cur_fast:.2f}) crossed below {slow}SMA ({cur_slow:.2f})",
                # Structured data fields
                "indicators": {
                    "sma_fast": round(cur_fast, 2),
                    "sma_slow": round(cur_slow, 2),
                    "spread_pct": round(spread_pct, 3),
                },
                "statistics": {
                    "crossover_type": "death",
                    "sma_spread": round(cur_fast - cur_slow, 2),
                },
                "parameters": {
                    "fast": fast,
                    "slow": slow,
                },
            }

        # Calculate hold confidence based on SMA spread
        # High confidence hold = SMAs are well separated (strong trend established)
        # Low confidence hold = SMAs are close together (potential crossover imminent)
        # Use 3% as the reference spread (same threshold used for buy/sell confidence)
        spread_magnitude = abs(spread_pct)
        if spread_magnitude >= 3.0:
            # Strong trend, high confidence to stay out
            hold_confidence = 0.8
        elif spread_magnitude >= 1.5:
            # Moderate trend
            hold_confidence = round(0.5 + (spread_magnitude - 1.5) / 1.5 * 0.3, 2)
        else:
            # Weak trend or consolidation, lower confidence
            hold_confidence = round(0.3 + spread_magnitude / 1.5 * 0.2, 2)

        return {
            "action": "hold",
            "confidence": max(hold_confidence, 0.3),  # Minimum 0.3 for valid decision
            "sma_fast": round(cur_fast, 2),
            "sma_slow": round(cur_slow, 2),
            "spread_pct": round(spread_pct, 3),
            "current_price": round(current_price, 2),
            "reason": "No SMA crossover" + (
                f" (spread={spread_pct:.2f}% - strong {'bullish' if spread_pct > 0 else 'bearish'} trend)"
                if spread_magnitude >= 2.0
                else f" (spread={spread_pct:.2f}% - consolidating)"
            ),
            # Structured data fields
            "indicators": {
                "sma_fast": round(cur_fast, 2),
                "sma_slow": round(cur_slow, 2),
                "spread_pct": round(spread_pct, 3),
            },
            "statistics": {
                "crossover_type": "none",
                "sma_spread": round(cur_fast - cur_slow, 2),
            },
            "parameters": {
                "fast": fast,
                "slow": slow,
            },
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 400,
        fast: int = 50,
        slow: int = 200,
    ) -> Dict:
        """Fetch daily bars and compute golden/death cross signal.

        Args:
            symbol: Stock ticker.
            timeframe: Bar resolution. Defaults to ``"1Day"``.
            lookback_days: Calendar days to fetch. Default 400.
            fast: Fast SMA period.
            slow: Slow SMA period.

        Returns:
            Signal dict or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, fast=fast, slow=slow)
        result.update({"symbol": symbol, "timeframe": timeframe, "timestamp": datetime.now().isoformat()})
        return result


# Singleton
golden_cross_skill = GoldenCrossSkill()


def make_golden_cross_signals(fast: int = 50, slow: int = 200) -> Callable:
    """Factory: Golden/death cross signal function for backtester.

    Args:
        fast: Fast SMA period. Default 50.
        slow: Slow SMA period. Default 200.

    Returns:
        Signal function ``(symbol, bars_df) -> "buy" | "sell" | "hold"``.
    """
    _skill = GoldenCrossSkill()

    def signal_fn(symbol: str, bars_df: pd.DataFrame) -> str:
        if bars_df is None or bars_df.empty:
            return "hold"
        return _skill.analyze_bars(bars_df, fast=fast, slow=slow).get("action", "hold")

    return signal_fn


__all__ = ["GoldenCrossSkill", "golden_cross_skill", "make_golden_cross_signals"]
