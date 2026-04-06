"""VWAPReversionSkill — intraday VWAP snap-back strategy."""

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


class VWAPReversionSkill:
    """VWAP Reversion — intraday price snap-back to VWAP after deviation.

    Signal: price deviates > ``dev_pct`` from VWAP AND volume spike (> ``vol_mult`` × avg).
    Entry: direction of reversion toward VWAP.
    Stop: ``stop_pct`` beyond entry away from VWAP.
    Target: VWAP itself.

    Workflow A (backtesting): ``analyze_bars(df, ...)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(
        self,
        df: pd.DataFrame,
        dev_pct: float = 0.005,
        vol_mult: float = 2.0,
        stop_pct: float = 0.003,
    ) -> Dict:
        """Compute VWAP reversion signal from a pre-fetched DataFrame.

        Args:
            df: DataFrame with ``open``, ``high``, ``low``, ``close``, ``volume`` columns.
            dev_pct: Minimum fractional deviation from VWAP to trigger signal. Default 0.5%.
            vol_mult: Minimum volume multiplier vs rolling 20-bar average. Default 2×.
            stop_pct: Stop-loss distance from entry as fraction of price. Default 0.3%.

        Returns:
            Dict with action, confidence, vwap, current_price, reason, entry_price,
            stop_loss, take_profit, deviation_pct.
        """
        # Filter to today's session for intraday VWAP (resets daily)
        if hasattr(df.index, 'date'):
            today = df.index[-1].date()
            df = df[df.index.date == today]

        if len(df) < 20:
            return {"action": "hold", "confidence": 0.0, "reason": "Insufficient data for today's session"}

        cum_vol = df["volume"].cumsum()
        if cum_vol.iloc[-1] == 0:
            return {"action": "hold", "confidence": 0.0, "reason": "Zero volume, cannot calculate VWAP"}
        cum_vwap = (df["close"] * df["volume"]).cumsum() / cum_vol
        vwap = float(cum_vwap.iloc[-1])
        current = float(df["close"].iloc[-1])
        avg_vol = float(df["volume"].rolling(20, min_periods=1).mean().iloc[-1])
        cur_vol = float(df["volume"].iloc[-1])

        # Data quality check: VWAP must be above minimum threshold
        MIN_VWAP = 0.01  # Penny stocks below 1 cent are suspicious
        if vwap < MIN_VWAP:
            return {"action": "hold", "confidence": 0.0, "reason": f"VWAP too low ({vwap:.4f}), data quality issue"}

        deviation = (current - vwap) / vwap
        vol_ok = cur_vol >= avg_vol * vol_mult

        if abs(deviation) >= dev_pct and vol_ok:
            if deviation > 0:
                action = "sell"
                entry = current
                stop = round(entry * (1 + stop_pct), 2)
                target = round(vwap, 2)
            else:
                action = "buy"
                entry = current
                stop = round(entry * (1 - stop_pct), 2)
                target = round(vwap, 2)
            confidence = round(min(abs(deviation) / (dev_pct * 2), 1.0), 2)
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0.0
            reason = (
                f"Price {deviation * 100:.2f}% {'above' if deviation > 0 else 'below'} VWAP "
                f"with {vol_ratio:.1f}× volume spike"
            )
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
                    "vwap": round(vwap, 2),
                    "deviation_pct": round(deviation * 100, 3),
                    "deviation_abs": round(current - vwap, 2),
                    "volume_ratio": round(vol_ratio, 2),
                    "avg_volume_20": round(avg_vol, 0),
                },
                "statistics": {
                    "price_vs_vwap": "above" if deviation > 0 else "below",
                    "volume_spike_multiplier": round(vol_ratio, 2),
                },
                "parameters": {
                    "dev_pct": dev_pct,
                    "vol_mult": vol_mult,
                    "stop_pct": stop_pct,
                },
            }

        vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0.0

        # Calculate hold confidence based on how "neutral" conditions are
        # High confidence hold = price near VWAP + normal volume
        # Low confidence hold = almost triggering but not quite
        proximity_to_vwap = 1.0 - min(abs(deviation) / dev_pct, 1.0)  # 1.0 at VWAP, 0.0 at threshold
        volume_normalcy = 1.0 - min(abs(vol_ratio - 1.0) / vol_mult, 1.0)  # 1.0 at avg, 0.0 at spike
        hold_confidence = round((proximity_to_vwap * 0.6 + volume_normalcy * 0.4), 2)

        return {
            "action": "hold",
            "confidence": max(hold_confidence, 0.1),  # Minimum 0.1 to indicate "valid decision"
            "current_price": round(current, 2),
            "reason": "No VWAP deviation signal" + (
                f" (dev={abs(deviation)*100:.2f}% < {dev_pct*100:.1f}%)" if abs(deviation) < dev_pct
                else f" (vol={vol_ratio:.1f}× < {vol_mult}×)"
            ),
            # Structured data fields
            "indicators": {
                "vwap": round(vwap, 2),
                "deviation_pct": round(deviation * 100, 3),
                "deviation_abs": round(current - vwap, 2),
                "volume_ratio": round(vol_ratio, 2),
                "avg_volume_20": round(avg_vol, 0),
            },
            "statistics": {
                "price_vs_vwap": "above" if deviation > 0 else "below",
                "volume_spike_multiplier": round(vol_ratio, 2),
            },
            "parameters": {
                "dev_pct": dev_pct,
                "vol_mult": vol_mult,
                "stop_pct": stop_pct,
            },
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Min",
        lookback_days: int = 5,
        dev_pct: float = 0.005,
        vol_mult: float = 2.0,
        stop_pct: float = 0.003,
    ) -> Dict:
        """Fetch intraday bars and compute VWAP reversion signal.

        Args:
            symbol: Stock ticker.
            timeframe: Bar resolution. Defaults to ``"1Min"``.
            lookback_days: Calendar days of bars to fetch. Default 5.
            dev_pct: VWAP deviation threshold.
            vol_mult: Volume spike multiplier.
            stop_pct: Stop-loss distance from entry.

        Returns:
            Signal dict or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, dev_pct=dev_pct, vol_mult=vol_mult, stop_pct=stop_pct)
        result.update({"symbol": symbol, "timeframe": timeframe, "timestamp": datetime.now().isoformat()})
        return result


# Singleton
vwap_reversion_skill = VWAPReversionSkill()


def make_vwap_reversion_signals(dev_pct: float = 0.005, vol_mult: float = 2.0, stop_pct: float = 0.003) -> Callable:
    """Factory: VWAP reversion signal function for backtester.

    Args:
        dev_pct: Minimum VWAP deviation to trigger. Default 0.5%.
        vol_mult: Volume spike multiplier. Default 2×.
        stop_pct: Stop-loss distance from entry. Default 0.3%.

    Returns:
        Signal function ``(symbol, bars_df) -> "buy" | "sell" | "hold"``.
    """
    _skill = VWAPReversionSkill()

    def signal_fn(symbol: str, bars_df: pd.DataFrame) -> str:
        if bars_df is None or bars_df.empty:
            return "hold"
        return _skill.analyze_bars(bars_df, dev_pct=dev_pct, vol_mult=vol_mult, stop_pct=stop_pct).get("action", "hold")

    return signal_fn


__all__ = ["VWAPReversionSkill", "vwap_reversion_skill", "make_vwap_reversion_signals"]
