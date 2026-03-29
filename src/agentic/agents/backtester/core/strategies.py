"""Trading strategy signal factories for backtesting.

Each factory returns a stateful callable that accumulates daily bar history
internally and emits a trading signal for the current day.

Signal protocol:
    signal_fn(symbol: str, current_day_bars: pd.DataFrame) -> str
    Returns: "buy" | "sell" | "hold"
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Callable

import pandas as pd

from src.common.utils import get_logger

logger = get_logger(__name__)


def make_mean_reversion_signals(
    z_score_entry: float = 2.0,
    z_score_exit: float = 0.5,
    lookback: int = 20,
) -> Callable:
    """Factory for a mean-reversion signal function.

    Entry rule:  z-score < -z_score_entry  -> "buy"
                 (price is more than z_score_entry std devs below rolling mean)
    Exit rule:   z-score > z_score_exit    -> "sell"
                 (price has reverted above the mean)
    Otherwise:   "hold"

    The function accumulates one daily close per call and uses the rolling
    window to compute the z-score. Stateful per backtest run.

    Args:
        z_score_entry: Z-score magnitude threshold for entry (default 2.0).
        z_score_exit:  Z-score threshold for exit (default 0.5).
        lookback:      Rolling window length in trading days (default 20).

    Returns:
        Callable(symbol, current_day_bars) -> "buy" | "sell" | "hold"
    """
    daily_closes: list = []

    def signal_fn(symbol: str, current_day_bars: pd.DataFrame) -> str:
        """Compute mean-reversion signal for the current trading day.

        Args:
            symbol: Stock ticker (used for logging only).
            current_day_bars: Intraday bars for the current trading day.

        Returns:
            "buy", "sell", or "hold".
        """
        if current_day_bars.empty:
            return "hold"

        close = float(current_day_bars.iloc[-1]["close"])
        daily_closes.append(close)

        if len(daily_closes) < lookback:
            logger.debug(
                "[mean_rev] %s insufficient history (%d/%d)",
                symbol, len(daily_closes), lookback,
            )
            return "hold"

        window = daily_closes[-lookback:]
        mean = sum(window) / len(window)
        variance = sum((x - mean) ** 2 for x in window) / len(window)
        std = variance ** 0.5

        if std < 1e-6:
            return "hold"  # no price variation

        z_score = (close - mean) / std

        logger.debug(
            "[mean_rev] %s close=%.2f mean=%.2f std=%.2f z=%.2f",
            symbol, close, mean, std, z_score,
        )

        if z_score <= -z_score_entry:
            return "buy"
        elif z_score >= z_score_exit:
            return "sell"
        else:
            return "hold"

    return signal_fn


def make_buy_and_hold_signals() -> Callable:
    """Factory for a buy-and-hold signal function.

    Emits a single "buy" on day 1, then "hold" forever.

    Returns:
        Callable(symbol, current_day_bars) -> "buy" | "hold"
    """
    bought = [False]

    def signal_fn(symbol: str, current_day_bars: pd.DataFrame) -> str:
        """Buy once on the first day, hold thereafter.

        Args:
            symbol: Stock ticker (unused).
            current_day_bars: Intraday bars for the current trading day.

        Returns:
            "buy" on first call, "hold" on subsequent calls.
        """
        if not bought[0]:
            bought[0] = True
            return "buy"
        return "hold"

    return signal_fn


# =============================================================================
# Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Test strategy signal factories with synthetic price data."""
    print("=" * 60)
    print("Strategies Functional Tests")
    print("=" * 60)

    # --- Test 1: mean-reversion ---
    # Use z_score_entry=1.5 so the dip clearly triggers buy.
    # (With lookback=5 and a single outlier, z approaches -2.0 from above;
    # a threshold of 1.5 reliably catches realistic dips.)
    print("\n[1/2] mean-reversion signals (lookback=5, entry=1.5)")
    signal_fn = make_mean_reversion_signals(z_score_entry=1.5, z_score_exit=0.5, lookback=5)

    # Stable warmup, then a sharp dip (triggers buy), then recovery (triggers sell)
    prices = [100, 101, 99, 100, 101,   # warmup: builds history
              70,                        # dip: z ~ -2.0 <= -1.5 -> buy
              95, 100, 103, 105, 110]    # recovery: z >= 0.5 -> sell

    signals_seen = []
    for i, p in enumerate(prices):
        day_bars = pd.DataFrame([{
            "close": p, "open": p, "high": p + 1, "low": p - 1, "volume": 1000
        }])
        sig = signal_fn("TEST", day_bars)
        signals_seen.append(sig)
        print(f"   day {i+1:02d}  price={p:6.1f}  signal={sig}")

    assert "buy" in signals_seen, "Expected at least one buy signal"
    print("[OK] buy signal generated on sharp dip")

    # --- Test 2: buy-and-hold ---
    print("\n[2/2] buy-and-hold signals")
    bah = make_buy_and_hold_signals()
    for i, p in enumerate([100, 101, 102, 103]):
        day_bars = pd.DataFrame([{
            "close": p, "open": p, "high": p + 1, "low": p - 1, "volume": 1000
        }])
        sig = bah("TEST", day_bars)
        print(f"   day {i+1}  price={p}  signal={sig}")
        expected = "buy" if i == 0 else "hold"
        assert sig == expected, f"day {i+1}: expected {expected}, got {sig}"
    print("[OK] buy once on day 1, hold thereafter")

    print("\n" + "=" * 60)
    print("Strategies tests complete!")
