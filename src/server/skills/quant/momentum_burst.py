"""MomentumBurstSkill — volume spike AND large single-bar price move."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Union, Dict

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.server.skills.quant._utils import _fetch_bars
from src.server.skills.quant.base_strategy import QuantStrategy
from src.server.skills.backtester.core.bt_types import StrategySignal, StrategyError
from src.common.utils import get_logger

logger = get_logger(__name__)


class MomentumBurstSkill(QuantStrategy):
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
    ) -> Union[StrategySignal, StrategyError]:
        """Compute momentum burst signal.

        Args:
            df: OHLCV DataFrame sorted oldest-first. Needs at least 21 bars.
            vol_mult: Volume multiplier vs 20-bar average. Default 3×.
            min_move: Minimum bar return (abs) to qualify. Default 0.5%.
            initial_stop_pct: Initial stop distance from entry (fixed, not trailing). Default 0.2%.

        Returns:
            StrategySignal with action, confidence, bar return, and volume data.
            StrategyError if data is insufficient.
        """
        if len(df) < 21:
            return StrategyError(error="Insufficient data (need at least 21 bars)")

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
            return StrategySignal(
                action=action,
                confidence=confidence,
                current_price=round(cur_close, 2),
                entry_price=round(cur_close, 2),
                stop_loss=stop,
                take_profit=None,
                reason=(
                    f"Momentum burst: {bar_return * 100:.2f}% bar move, "
                    f"{vol_ratio:.1f}× avg volume"
                ),
                indicators={
                    "bar_return_pct": round(bar_return * 100, 3),
                    "volume_ratio": round(vol_ratio, 2),
                    "avg_volume_20": round(avg_vol, 0),
                    "current_volume": round(cur_vol, 0),
                },
                statistics={
                    "price_change": round(cur_close - prev_close, 2),
                    "volume_spike_multiplier": round(vol_ratio, 2),
                },
                parameters={
                    "vol_mult": vol_mult,
                    "min_move": min_move,
                    "initial_stop_pct": initial_stop_pct,
                },
            )

        # Calculate hold confidence based on how "normal" conditions are
        # High confidence hold = small price move + normal volume
        # Low confidence hold = almost triggering but not quite
        move_normalcy = 1.0 - min(abs(bar_return) / min_move, 1.0)  # 1.0 = no move, 0.0 = at threshold
        volume_normalcy = 1.0 - min(vol_ratio / vol_mult, 1.0)  # 1.0 = low volume, 0.0 = spike
        hold_confidence = round((move_normalcy * 0.5 + volume_normalcy * 0.5), 2)

        return StrategySignal(
            action="hold",
            confidence=max(hold_confidence, 0.1),  # Minimum 0.1
            current_price=round(cur_close, 2),
            reason="No momentum burst",
            indicators={
                "bar_return_pct": round(bar_return * 100, 3),
                "volume_ratio": round(vol_ratio, 2),
                "avg_volume_20": round(avg_vol, 0),
                "current_volume": round(cur_vol, 0),
            },
            statistics={
                "price_change": round(cur_close - prev_close, 2),
                "volume_spike_multiplier": round(vol_ratio, 2),
            },
            parameters={
                "vol_mult": vol_mult,
                "min_move": min_move,
                "initial_stop_pct": initial_stop_pct,
            },
        )

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Min",
        lookback_days: int = 3,
        vol_mult: float = 3.0,
        min_move: float = 0.005,
        initial_stop_pct: float = 0.002,
    ) -> Union[StrategySignal, StrategyError]:
        """Fetch intraday bars and compute momentum burst signal.

        Args:
            symbol: Stock ticker.
            timeframe: Bar resolution. Defaults to ``"1Min"``.
            lookback_days: Calendar days to fetch. Default 3.
            vol_mult: Volume spike multiplier.
            min_move: Minimum bar price move.
            initial_stop_pct: Trailing stop distance.

        Returns:
            StrategySignal with action and metadata, or StrategyError on failure.
        """
        df = _fetch_bars(symbol, timeframe=timeframe, lookback_days=lookback_days)
        if df is None:
            return StrategyError(error=f"No data for {symbol}/{timeframe}", symbol=symbol)

        result = self.analyze_bars(df, vol_mult=vol_mult, min_move=min_move, initial_stop_pct=initial_stop_pct)

        # Inject metadata for live trading
        if isinstance(result, StrategySignal):
            result.symbol = symbol
            result.timeframe = timeframe
            result.timestamp = datetime.now()
        elif isinstance(result, StrategyError):
            result.symbol = symbol

        return result


# Singleton
momentum_burst_skill = MomentumBurstSkill()


__all__ = ["MomentumBurstSkill", "momentum_burst_skill"]
