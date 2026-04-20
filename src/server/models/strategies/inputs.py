"""Input models for all quant, backtester, and portfolio skill functions.

All models extend StrategyBaseInput (from .shared) which provides symbol
normalisation, timeframe alias resolution, date-pair validation, and the
``is_historical`` property.  Extra fields the LLM may emit (task_id, note,
workflow_type, etc.) are silently discarded via ``ConfigDict(extra="ignore")``.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.server.models.strategies.shared import (
    StrategyBaseInput,
    _FUZZY_MAP,
    _VALID_STRATEGIES,
    _normalise_timeframe,
)

_log = logging.getLogger(__name__)

# ===========================================================================
# Quant Indicator Inputs (4 indicator functions)
# ===========================================================================


class QuantIndicatorInput(StrategyBaseInput):
    """Base input for the four indicator functions (momentum, volatility, volume, candle).

    Provides concrete defaults suited to intraday indicator scans.  Sub-classes
    may tighten or relax constraints (e.g. CandleInput uses 30-day window).

    Attributes:
        timeframe: Defaults to ``"1Min"`` for intraday indicator scans.
        lookback_days: Defaults to 90 calendar days.
    """

    timeframe: str = Field(default="1Min", description="AlpacaDAO canonical timeframe")
    lookback_days: int = Field(
        default=90, ge=1, le=730,
        description="Calendar days to look back (live mode only)",
    )


class MomentumInput(QuantIndicatorInput):
    """Input for ``calc_momentum`` — MACD + RSI analysis."""


class VolatilityInput(QuantIndicatorInput):
    """Input for ``calc_volatility_bands`` — Bollinger Bands analysis."""


class VolumeInput(QuantIndicatorInput):
    """Input for ``calc_volume_flow`` — OBV + volume trend analysis."""


class CandleInput(QuantIndicatorInput):
    """Input for ``analyze_candle_structure`` — candlestick pattern detection.

    Defaults ``lookback_days`` to 30 (shorter window suits candle pattern scanning).
    """

    lookback_days: int = Field(default=30, ge=1, le=365)


# ===========================================================================
# Mean Reversion Input (intraday)
# ===========================================================================


class MeanReversionInput(StrategyBaseInput):
    """Input for ``mean_reversion_analyze`` — Z-score / mean-reversion signals.

    Extends StrategyBaseInput with a statistical lookback window (``lookback``),
    a Z-score threshold (``threshold``), and a support/resistance scan window
    (``sr_lookback``) unique to this intraday strategy.

    Attributes:
        timeframe: Defaults to ``"1Min"``.
        lookback_days: Calendar days to fetch bars for. Default 90.
        lookback: Statistical lookback in trading bars.
        threshold: Z-score entry threshold.
        sr_lookback: Bars to scan for support/resistance high/low levels.
    """

    timeframe: str = Field(default="1Min", description="Bar timeframe")
    lookback_days: int = Field(
        default=90, ge=1, le=730,
        description="Calendar days to fetch (live mode only)",
    )
    lookback: int = Field(
        default=60, ge=5, le=500,
        description="Trading bars for statistical lookback window",
    )
    threshold: float = Field(
        default=2.0, ge=0.5, le=5.0,
        description="Z-score threshold for entry signal",
    )
    sr_lookback: int = Field(
        default=60, ge=10, le=500,
        description="Bars to scan for support/resistance high/low levels (60 = 1 hr of 1Min data)",
    )


# ===========================================================================
# Backtester Inputs
# ===========================================================================


class BacktestInput(StrategyBaseInput):
    """Input for ``backtest_strategy``.

    Attributes:
        ticker: Stock ticker (alias for symbol — kept for registry compatibility).
        start_date: YYYY-MM-DD backtest start.
        end_date: YYYY-MM-DD backtest end.
        strategy: Strategy name (fuzzy-matched to canonical form).
        initial_capital: Starting capital in USD.
        strategy_params: Optional strategy-specific parameter overrides.
    """

    # BacktestInput uses 'ticker' instead of the inherited 'symbol' field.
    # Override model_config to allow both (functions.py passes 'ticker').
    model_config = ConfigDict(extra="ignore")

    # Provide required field overrides for BacktestInput's context
    timeframe: str = Field(default="1Day", description="Bar timeframe for backtest")
    lookback_days: int = Field(default=365, ge=1, description="Days of data to fetch")

    ticker: str = Field(description="Stock ticker symbol")
    start_date: str = Field(description="YYYY-MM-DD backtest start date")  # type: ignore[assignment]
    end_date: str = Field(description="YYYY-MM-DD backtest end date")      # type: ignore[assignment]
    strategy: str = Field(
        default="mean-reversion",
        description="Strategy name",
    )
    initial_capital: float = Field(
        default=100_000.0, gt=0,
        description="Starting capital in USD",
    )
    strategy_params: Optional[Dict[str, Any]] = Field(default=None)

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        """Normalise ticker to upper-case."""
        return v.strip().upper()

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        """Normalise and validate strategy name.

        Performs exact match first, then fuzzy keyword match so that LLM
        variants like 'momentum_SMA_50_200' or 'mean_reversion_zscore' are
        silently coerced to the canonical name instead of failing.
        """
        v_norm = v.lower().strip().replace("_", "-")
        if v_norm in _VALID_STRATEGIES:
            return v_norm
        for canonical, keywords in _FUZZY_MAP:
            if all(kw in v_norm for kw in keywords):
                _log.warning("[BacktestInput] strategy %r fuzzy-matched → %r", v, canonical)
                return canonical
        raise ValueError(
            f"strategy must be one of {sorted(_VALID_STRATEGIES)}, got {v!r}"
        )

    @model_validator(mode="after")
    def check_dates(self) -> "BacktestInput":
        """Ensure start_date < end_date."""
        if self.start_date >= self.end_date:
            raise ValueError(
                f"start_date {self.start_date!r} must be before end_date {self.end_date!r}"
            )
        return self


class DataAvailabilityInput(StrategyBaseInput):
    """Input for ``check_data_availability``.

    Attributes:
        symbol: Stock ticker.
        start_date: YYYY-MM-DD range start (required for this model).
        end_date: YYYY-MM-DD range end (required for this model).
        timeframe: Bar timeframe to check.
    """

    timeframe: str = Field(default="1Min", description="Bar timeframe to check")
    lookback_days: int = Field(default=30, ge=1, description="Unused; present for base compat")
    start_date: str = Field(description="YYYY-MM-DD")  # type: ignore[assignment]
    end_date: str = Field(description="YYYY-MM-DD")    # type: ignore[assignment]

    @model_validator(mode="after")
    def check_date_pair(self) -> "DataAvailabilityInput":  # type: ignore[override]
        """Override parent — start/end are always required here."""
        if self.start_date >= self.end_date:
            raise ValueError(
                f"start_date {self.start_date!r} must be before end_date {self.end_date!r}"
            )
        return self


class HistoricalDataInput(DataAvailabilityInput):
    """Input for ``fetch_historical_data`` (same shape as DataAvailabilityInput)."""


# ===========================================================================
# New Quant Strategy Inputs (8 strategies: 4 day-trading + 4 swing)
# ===========================================================================

# -- Day-trading strategies (default timeframe: 1Min) ----------------------


class VWAPReversionInput(StrategyBaseInput):
    """Input for ``vwap_reversion_analyze`` — intraday VWAP mean-reversion.

    Attributes:
        timeframe: Default ``"1Min"``.
        lookback_days: Calendar days of intraday bars to fetch. Default 5.
        dev_pct: VWAP deviation threshold (fraction). Default 0.5%.
        vol_mult: Volume spike multiplier for confirmation. Default 2.0×.
        stop_pct: Stop-loss distance from entry (fraction). Default 0.3%.
    """

    timeframe: str = Field(default="1Min")
    lookback_days: int = Field(default=5, ge=1, le=30)
    dev_pct: float = Field(
        default=0.005, ge=0.001, le=0.05,
        description="VWAP deviation threshold (fraction). Default 0.5%.",
    )
    vol_mult: float = Field(
        default=2.0, ge=0.5, le=10.0,
        description="Volume spike multiplier for confirmation.",
    )
    stop_pct: float = Field(
        default=0.003, ge=0.001, le=0.05,
        description="Stop-loss distance from entry (fraction). Default 0.3%.",
    )


class OpeningRangeBreakoutInput(StrategyBaseInput):
    """Input for ``opening_range_breakout_analyze`` — first-N-bar range breakout.

    Attributes:
        timeframe: Default ``"1Min"``.
        lookback_days: Calendar days to fetch. Default 2.
        range_bars: Bars defining the opening range (default 15 = first 15 minutes).
    """

    timeframe: str = Field(default="1Min")
    lookback_days: int = Field(default=2, ge=1, le=10)
    range_bars: int = Field(
        default=15, ge=5, le=60,
        description="Number of bars defining the opening range.",
    )


class RSIDivergenceInput(StrategyBaseInput):
    """Input for ``rsi_divergence_analyze`` — bullish/bearish RSI divergence scalp.

    Attributes:
        timeframe: Default ``"1Min"``.
        lookback_days: Calendar days to fetch. Default 5.
        lookback: Bars to scan for divergence. Default 20.
        oversold: RSI oversold threshold (overbought mirror = 100 - oversold). Default 35.
    """

    timeframe: str = Field(default="1Min")
    lookback_days: int = Field(default=5, ge=1, le=30)
    lookback: int = Field(
        default=20, ge=5, le=100,
        description="Number of bars to scan for divergence.",
    )
    oversold: float = Field(
        default=35.0, ge=10.0, le=50.0,
        description="RSI oversold threshold.",
    )


class MomentumBurstInput(StrategyBaseInput):
    """Input for ``momentum_burst_analyze`` — explosive volume+price momentum.

    Attributes:
        timeframe: Default ``"1Min"``.
        lookback_days: Calendar days to fetch. Default 3.
        vol_mult: Volume spike multiplier. Default 3.0×.
        min_move: Minimum bar price move (fraction). Default 0.5%.
        trail_pct: Trailing stop distance (fraction). Default 0.2%.
    """

    timeframe: str = Field(default="1Min")
    lookback_days: int = Field(default=3, ge=1, le=14)
    vol_mult: float = Field(
        default=3.0, ge=1.0, le=10.0,
        description="Volume spike multiplier.",
    )
    min_move: float = Field(
        default=0.005, ge=0.001, le=0.05,
        description="Minimum bar price move (fraction).",
    )
    trail_pct: float = Field(
        default=0.002, ge=0.001, le=0.02,
        description="Trailing stop distance (fraction).",
    )


# -- Swing / multi-day strategies (default timeframe: 1Day) ----------------


class GoldenCrossInput(StrategyBaseInput):
    """Input for ``golden_cross_analyze`` — SMA-50/200 crossover on daily bars.

    Attributes:
        timeframe: Default ``"1Day"``.
        lookback_days: Calendar days to fetch. Default 365.
        fast: Fast SMA period. Default 50.
        slow: Slow SMA period. Default 200.
    """

    timeframe: str = Field(default="1Day")
    lookback_days: int = Field(default=365, ge=200, le=730)
    fast: int = Field(default=50, ge=5, le=100, description="Fast SMA period.")
    slow: int = Field(default=200, ge=50, le=500, description="Slow SMA period.")

    @model_validator(mode="after")
    def check_sma_order(self) -> "GoldenCrossInput":
        """Ensure fast < slow."""
        if self.fast >= self.slow:
            raise ValueError(f"fast ({self.fast}) must be less than slow ({self.slow})")
        return self


class Breakout52WInput(StrategyBaseInput):
    """Input for ``breakout_52w_analyze`` — 52-week high breakout with volume confirmation.

    Attributes:
        timeframe: Default ``"1Day"``.
        lookback_days: Calendar days to fetch. Default 400.
        lookback: Prior-high scan window in bars (252 = 1 trading year).
        vol_mult: Volume multiplier for breakout confirmation. Default 1.5×.
        trail_pct: Trailing stop distance (fraction). Default 10%.
    """

    timeframe: str = Field(default="1Day")
    lookback_days: int = Field(default=400, ge=252, le=730)
    lookback: int = Field(
        default=252, ge=60, le=504,
        description="Prior-high scan window in bars (252 = 1 trading year).",
    )
    vol_mult: float = Field(
        default=1.5, ge=0.5, le=5.0,
        description="Volume multiplier for breakout confirmation.",
    )
    trail_pct: float = Field(
        default=0.10, ge=0.01, le=0.30,
        description="Trailing stop distance (fraction). Default 10%.",
    )


class MeanReversionDailyInput(StrategyBaseInput):
    """Input for ``mean_reversion_daily_analyze`` — daily-bar Z-score mean reversion.

    Attributes:
        timeframe: Default ``"1Day"``.
        lookback_days: Calendar days to fetch. Default 90.
        lookback: Daily bars for the statistics window. Default 20.
        threshold: Z-score entry threshold (higher than intraday default 2.0). Default 2.5.
        ma_period: Moving average period for Bollinger calculation. Default 20.
    """

    timeframe: str = Field(default="1Day")
    lookback_days: int = Field(default=90, ge=21, le=365)
    lookback: int = Field(
        default=20, ge=10, le=100,
        description="Daily bars for the statistics window.",
    )
    threshold: float = Field(
        default=2.5, ge=0.5, le=5.0,
        description="Z-score entry threshold.",
    )
    ma_period: int = Field(
        default=20, ge=5, le=100,
        description="Moving average period.",
    )


class EarningsDriftInput(StrategyBaseInput):
    """Input for ``earnings_drift_analyze`` — post-earnings momentum drift ride.

    Attributes:
        timeframe: Default ``"1Day"``.
        lookback_days: Calendar days to fetch. Default 60.
        lookback: Catalyst scan window in bars. Default 10.
        min_move: Minimum catalyst-day move (fraction). Default 4%.
        vol_mult: Volume multiplier for catalyst-day confirmation. Default 2.0×.
        hold_days: Sessions to hold the drift position. Default 5.
    """

    timeframe: str = Field(default="1Day")
    lookback_days: int = Field(default=60, ge=10, le=365)
    lookback: int = Field(
        default=10, ge=5, le=60,
        description="Catalyst scan window in bars.",
    )
    min_move: float = Field(
        default=0.04, ge=0.01, le=0.20,
        description="Minimum catalyst-day move (fraction). Default 4%.",
    )
    vol_mult: float = Field(
        default=2.0, ge=0.5, le=10.0,
        description="Volume multiplier for catalyst-day confirmation.",
    )
    hold_days: int = Field(
        default=5, ge=1, le=30,
        description="Sessions to hold the drift position.",
    )
