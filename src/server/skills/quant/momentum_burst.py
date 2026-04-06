"""MomentumBurstSkill — volume spike AND large single-bar price move."""

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


class MomentumBurstSkill:
    """Momentum Burst — volume spike AND large single-bar price move.

    Signal: current bar volume > ``vol_mult`` × 20-bar avg AND abs(bar return) > ``min_move``.
    Entry: direction of the burst bar.
    Stop: fixed ``initial_stop_pct`` from entry (not trailing).
    Target: open-ended (manage exit with your own trailing logic).

    Workflow A (backtesting): ``analyze_bars(df, ...)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(
        self,
        df: pd.DataFrame,
        vol_mult: float = 3.0,
        min_move: float = 0.005,
        initial_stop_pct: float = 0.002,
    ) -> Dict:
        """Compute momentum burst signal.

        Args:
            df: OHLCV DataFrame sorted oldest-first. Needs at least 21 bars.
            vol_mult: Volume multiplier vs 20-bar average. Default 3×.
            min_move: Minimum bar return (abs) to qualify. Default 0.5%.
            initial_stop_pct: Initial stop distance from entry (fixed, not trailing). Default 0.2%.

        Returns:
            Dict with action, confidence, bar_return, volume_ratio, entry/stop/reason.
        """
        if len(df) < 21:
            return {"action": "hold", "confidence": 0.0, "reason": "Insufficient data"}

        cur_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].iloc[-21:-1].mean())
        vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0.0

        cur_close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
        bar_return = (cur_close - prev_close) / prev_close if prev_close > 0 else 0.0

        if vol_ratio >= vol_mult and abs(bar_return) >= min_move:
            action = "buy" if bar_return > 0 else "sell"
            stop = (
                round(cur_close * (1 - initial_stop_pct), 2)
                if action == "buy"
                else round(cur_close * (1 + initial_stop_pct), 2)
            )
            confidence = round(
                min((vol_ratio / (vol_mult * 2)) + (abs(bar_return) / (min_move * 4)), 1.0), 2
            )
            return {
                "action": action,
                "confidence": confidence,
                "current_price": round(cur_close, 2),
                "entry_price": round(cur_close, 2),
                "stop_loss": stop,
                "take_profit": None,
                "reason": (
                    f"Momentum burst: {bar_return * 100:.2f}% bar move, "
                    f"{vol_ratio:.1f}× avg volume"
                ),
                # Structured data fields
                "indicators": {
                    "bar_return_pct": round(bar_return * 100, 3),
                    "volume_ratio": round(vol_ratio, 2),
                    "avg_volume_20": round(avg_vol, 0),
                    "current_volume": round(cur_vol, 0),
                },
                "statistics": {
                    "price_change": round(cur_close - prev_close, 2),
                    "volume_spike_multiplier": round(vol_ratio, 2),
                },
                "parameters": {
                    "vol_mult": vol_mult,
                    "min_move": min_move,
                    "initial_stop_pct": initial_stop_pct,
                },
            }

        # Calculate hold confidence based on how "normal" conditions are
        # High confidence hold = small price move + normal volume
        # Low confidence hold = almost triggering but not quite
        move_normalcy = 1.0 - min(abs(bar_return) / min_move, 1.0)  # 1.0 = no move, 0.0 = at threshold
        volume_normalcy = 1.0 - min(vol_ratio / vol_mult, 1.0)  # 1.0 = low volume, 0.0 = spike
        hold_confidence = round((move_normalcy * 0.5 + volume_normalcy * 0.5), 2)

        return {
            "action": "hold",
            "confidence": max(hold_confidence, 0.1),  # Minimum 0.1
            "current_price": round(cur_close, 2),
            "reason": "No momentum burst",
            # Structured data fields
            "indicators": {
                "bar_return_pct": round(bar_return * 100, 3),
                "volume_ratio": round(vol_ratio, 2),
                "avg_volume_20": round(avg_vol, 0),
                "current_volume": round(cur_vol, 0),
            },
            "statistics": {
                "price_change": round(cur_close - prev_close, 2),
                "volume_spike_multiplier": round(vol_ratio, 2),
            },
            "parameters": {
                "vol_mult": vol_mult,
                "min_move": min_move,
                "initial_stop_pct": initial_stop_pct,
            },
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Min",
        lookback_days: int = 3,
        vol_mult: float = 3.0,
        min_move: float = 0.005,
        initial_stop_pct: float = 0.002,
    ) -> Dict:
        """Fetch intraday bars and compute momentum burst signal.

        Args:
            symbol: Stock ticker.
            timeframe: Bar resolution. Defaults to ``"1Min"``.
            lookback_days: Calendar days to fetch. Default 3.
            vol_mult: Volume spike multiplier.
            min_move: Minimum bar price move.
            initial_stop_pct: Trailing stop distance.

        Returns:
            Signal dict or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, vol_mult=vol_mult, min_move=min_move, initial_stop_pct=initial_stop_pct)
        result.update({"symbol": symbol, "timeframe": timeframe, "timestamp": datetime.now().isoformat()})
        return result


# Singleton
momentum_burst_skill = MomentumBurstSkill()


def make_momentum_burst_signals(vol_mult: float = 3.0, min_move: float = 0.005, initial_stop_pct: float = 0.002) -> Callable:
    """Factory: Momentum burst signal function for backtester.

    Args:
        vol_mult: Volume spike multiplier. Default 3×.
        min_move: Minimum bar price move. Default 0.5%.
        initial_stop_pct: Trailing stop distance from entry. Default 0.2%.

    Returns:
        Signal function ``(symbol, bars_df) -> "buy" | "sell" | "hold"``.
    """
    _skill = MomentumBurstSkill()

    def signal_fn(symbol: str, bars_df: pd.DataFrame) -> str:
        if bars_df is None or bars_df.empty:
            return "hold"
        return _skill.analyze_bars(bars_df, vol_mult=vol_mult, min_move=min_move, initial_stop_pct=initial_stop_pct).get("action", "hold")

    return signal_fn


__all__ = ["MomentumBurstSkill", "momentum_burst_skill", "make_momentum_burst_signals"]
