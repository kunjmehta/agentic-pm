"""EarningsDriftSkill — 3-5 day post-earnings momentum continuation."""

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


class EarningsDriftSkill:
    """Earnings Drift — 3-day post-earnings momentum continuation.

    Assumes an external data source provides earnings dates.  Without that,
    the skill uses a heuristic: if the stock moved > ``min_move`` in a single
    day and volume was > ``vol_mult`` × average, it treats that as an
    earnings-like catalyst day and enters the drift on the next bar.

    Entry: open of day 2 after catalyst.
    Exit: close of day 5–7 after catalyst (or stop hit).
    Stop: 50% of the catalyst-day move below entry.

    Workflow A (backtesting): ``analyze_bars(df, ...)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(
        self,
        df: pd.DataFrame,
        lookback: int = 10,
        min_move: float = 0.04,
        vol_mult: float = 2.0,
        hold_days: int = 5,
    ) -> Dict:
        """Detect and signal an earnings drift setup.

        Args:
            df: Daily OHLCV DataFrame sorted oldest-first.
                Needs ≥ ``lookback + hold_days + 21`` bars.
            lookback: Bars to scan for a catalyst day. Default 10.
            min_move: Minimum single-day price move to qualify as catalyst. Default 4%.
            vol_mult: Volume multiplier for catalyst day. Default 2×.
            hold_days: Days to hold after catalyst. Default 5.

        Returns:
            Dict with action, confidence, catalyst_move_pct, days_since_catalyst,
            entry/stop/target, reason.
        """
        min_len = lookback + hold_days + 21
        if len(df) < min_len:
            return {
                "action": "hold",
                "confidence": 0.5,  # Neutral confidence for data issues
                "reason": "Insufficient data"
            }

        avg_vol = float(df["volume"].iloc[-21:-1].mean())
        # Require minimum average volume to avoid zero-volume edge cases
        MIN_AVG_VOLUME = 1000.0
        if avg_vol < MIN_AVG_VOLUME:
            return {
                "action": "hold",
                "confidence": 0.5,  # Neutral confidence for data quality issues
                "reason": "Insufficient volume data"
            }

        # Scan window: lookback bars, excluding the most recent hold_days
        # Example: if lookback=10, hold_days=5, scan df[-15:-5]
        window_start_idx = len(df) - lookback - hold_days
        window_end_idx = len(df) - hold_days
        window = df.iloc[window_start_idx:window_end_idx]

        catalyst_idx = None
        catalyst_move = 0.0
        # Scan backwards through window to find most recent catalyst
        for i in range(len(window) - 1, -1, -1):
            row = window.iloc[i]
            # Map window index to df index
            df_idx = window_start_idx + i
            if df_idx == 0:
                continue  # No previous close for first bar
            prev_close = float(df["close"].iloc[df_idx - 1])
            if prev_close <= 0:
                continue
            day_move = (float(row["close"]) - prev_close) / prev_close
            cur_vol = float(row["volume"])
            # Require both volume threshold AND absolute minimum volume
            vol_ok = cur_vol >= avg_vol * vol_mult and cur_vol >= MIN_AVG_VOLUME
            if abs(day_move) >= min_move and vol_ok:
                catalyst_idx = df_idx
                catalyst_move = day_move
                break

        if catalyst_idx is None:
            # Calculate hold confidence based on how close we are to detecting a catalyst
            # Scan for the strongest signal that didn't quite trigger
            max_move_pct = 0.0
            max_vol_ratio = 0.0
            for i in range(len(window) - 1, -1, -1):
                row = window.iloc[i]
                df_idx = window_start_idx + i
                if df_idx == 0:
                    continue
                prev_close = float(df["close"].iloc[df_idx - 1])
                if prev_close <= 0:
                    continue
                day_move = abs((float(row["close"]) - prev_close) / prev_close)
                cur_vol = float(row["volume"])
                vol_ratio_sample = cur_vol / avg_vol if avg_vol > 0 else 0.0
                max_move_pct = max(max_move_pct, day_move)
                max_vol_ratio = max(max_vol_ratio, vol_ratio_sample)

            # High confidence hold = no catalyst detected and conditions are quiet
            # Low confidence hold = almost triggered but not quite
            move_factor = 1.0 - min(max_move_pct / min_move, 1.0)  # 1.0 = calm, 0.0 = at threshold
            vol_factor = 1.0 - min(max_vol_ratio / vol_mult, 1.0)  # 1.0 = low vol, 0.0 = at threshold
            hold_confidence = round((move_factor * 0.6 + vol_factor * 0.4), 2)

            return {
                "action": "hold",
                "confidence": max(hold_confidence, 0.4),  # Minimum 0.4
                "reason": "No earnings catalyst detected"
            }

        days_since = len(df) - 1 - catalyst_idx
        current = float(df["close"].iloc[-1])
        catalyst_close = float(df["close"].iloc[catalyst_idx])

        if days_since < 1 or days_since > hold_days:
            # Catalyst detected but outside drift window
            # High confidence if far from window, lower if just outside
            if days_since < 1:
                # Too soon after catalyst
                time_factor = 0.6
            elif days_since > hold_days + 3:
                # Well past the drift window
                time_factor = 0.8
            else:
                # Just outside the window (hold_days < days_since <= hold_days+3)
                time_factor = 0.5

            return {
                "action": "hold",
                "confidence": time_factor,
                "days_since_catalyst": days_since,
                "reason": f"Outside drift window (days_since={days_since}, hold={hold_days})",
            }

        action = "buy" if catalyst_move > 0 else "sell"
        stop_distance = abs(catalyst_close * catalyst_move * 0.5)
        stop = round(current - stop_distance, 2) if action == "buy" else round(current + stop_distance, 2)
        target = round(current + stop_distance * 2, 2) if action == "buy" else round(current - stop_distance * 2, 2)
        confidence = round(min(abs(catalyst_move) / (min_move * 2), 1.0), 2)

        return {
            "action": action,
            "confidence": confidence,
            "catalyst_move_pct": round(catalyst_move * 100, 2),
            "days_since_catalyst": days_since,
            "hold_days_remaining": hold_days - days_since,
            "current_price": round(current, 2),
            "entry_price": round(current, 2),
            "stop_loss": stop,
            "take_profit": target,
            "reason": (
                f"Earnings drift day {days_since}/{hold_days}: catalyst {catalyst_move * 100:.1f}% move"
            ),
            # Structured data fields
            "indicators": {
                "catalyst_move_pct": round(catalyst_move * 100, 2),
                "days_since_catalyst": days_since,
                "catalyst_close": round(catalyst_close, 2),
            },
            "statistics": {
                "hold_days_remaining": hold_days - days_since,
                "drift_direction": "up" if catalyst_move > 0 else "down",
            },
            "parameters": {
                "lookback": lookback,
                "min_move": min_move,
                "vol_mult": vol_mult,
                "hold_days": hold_days,
            },
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 60,
        lookback: int = 10,
        min_move: float = 0.04,
        vol_mult: float = 2.0,
        hold_days: int = 5,
    ) -> Dict:
        """Fetch daily bars and compute earnings drift signal.

        Args:
            symbol: Stock ticker.
            timeframe: Bar resolution. Defaults to ``"1Day"``.
            lookback_days: Calendar days to fetch. Default 60.
            lookback: Catalyst scan window in bars.
            min_move: Minimum catalyst day move.
            vol_mult: Volume multiplier for catalyst day.
            hold_days: Drift hold window.

        Returns:
            Signal dict or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(
            df, lookback=lookback, min_move=min_move, vol_mult=vol_mult, hold_days=hold_days
        )
        result.update({"symbol": symbol, "timeframe": timeframe, "timestamp": datetime.now().isoformat()})
        return result


# Singleton
earnings_drift_skill = EarningsDriftSkill()


def make_earnings_drift_signals(lookback: int = 10, min_move: float = 0.04, vol_mult: float = 2.0, hold_days: int = 5) -> Callable:
    """Factory: Earnings drift signal function for backtester.

    Args:
        lookback: Catalyst scan window in bars. Default 10.
        min_move: Minimum catalyst-day move. Default 4%.
        vol_mult: Volume multiplier for catalyst day. Default 2×.
        hold_days: Drift hold window. Default 5.

    Returns:
        Signal function ``(symbol, bars_df) -> "buy" | "sell" | "hold"``.
    """
    _skill = EarningsDriftSkill()

    def signal_fn(symbol: str, bars_df: pd.DataFrame) -> str:
        if bars_df is None or bars_df.empty:
            return "hold"
        return _skill.analyze_bars(bars_df, lookback=lookback, min_move=min_move, vol_mult=vol_mult, hold_days=hold_days).get("action", "hold")

    return signal_fn


__all__ = ["EarningsDriftSkill", "earnings_drift_skill", "make_earnings_drift_signals"]


if __name__ == "__main__":
    import numpy as np

    print("--- EarningsDriftSkill smoke test ---")
    rng = np.random.default_rng(55)
    n = 100
    prices = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    volumes = rng.integers(100_000, 500_000, n).astype(float)
    # Inject a catalyst: big move + high volume near end
    prices[-7] = prices[-8] * 1.06
    volumes[-7] = 900_000.0
    df = pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": volumes,
    })
    r = EarningsDriftSkill().analyze_bars(df)
    print(f"action={r['action']}, confidence={r.get('confidence')}")
    fn = make_earnings_drift_signals()
    print(f"factory: {fn('TEST', df)}")
    print("OK")
