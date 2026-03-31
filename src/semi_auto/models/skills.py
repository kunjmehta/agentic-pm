"""Pydantic input and output models for all semi-auto skill functions.

Input models validate + normalise parameters produced by LLM reasoning agents
before they reach the underlying skill classes or DAO layer.  Extra fields the
LLM may emit (task_id, note, workflow_type, etc.) are silently discarded via
``model_config = ConfigDict(extra="ignore")``.

Output models provide typed, machine-readable return shapes for each skill call
so downstream nodes (synthesizer, executor) can work with guaranteed structure.

Usage in registry wrappers::

    inp = MomentumInput.model_validate(kwargs)  # raises ValidationError on bad input
    result = _momentum_skill.generate_signals(inp.symbol, ...)
    return MomentumOutput(**result).model_dump()
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_VALID_TIMEFRAMES = {"1Min", "5Min", "15Min", "1Hour", "1Day"}

# Aliases the LLM commonly emits → canonical forms accepted by AlpacaDAO
_TIMEFRAME_ALIASES: Dict[str, str] = {
    "1d": "1Day", "1day": "1Day", "day": "1Day", "daily": "1Day",
    "1h": "1Hour", "1hour": "1Hour", "hour": "1Hour", "hourly": "1Hour",
    "1m": "1Min", "1min": "1Min", "minute": "1Min",
    "5m": "5Min", "5min": "5Min",
    "15m": "15Min", "15min": "15Min",
}

_VALID_STRATEGIES = {"buy-and-hold", "mean-reversion", "momentum", "value"}


def _normalise_timeframe(v: str) -> str:
    """Return canonical timeframe string, falling back to the raw value if unknown."""
    if not v:
        return "1Day"
    return _TIMEFRAME_ALIASES.get(v.lower(), v)


# ===========================================================================
# Quant Skill — Input Models
# ===========================================================================

class QuantIndicatorInput(BaseModel):
    """Base input for the four indicator functions (momentum, volatility, volume, candle).

    Supports two operating modes:
    - **Live mode** (default): ``lookback_days`` back from today.
    - **Historical mode**: activated when both ``start_date`` **and** ``end_date``
      are supplied.  ``lookback_days`` is ignored in this mode.

    Attributes:
        symbol: Stock ticker symbol, automatically upper-cased.
        timeframe: AlpacaDAO canonical timeframe string.
        lookback_days: Calendar days to look back (live mode).
        start_date: YYYY-MM-DD start of range (historical mode).
        end_date: YYYY-MM-DD end of range (historical mode).
    """

    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(description="Stock ticker symbol, e.g. 'AAPL'")
    timeframe: str = Field(default="1Day", description="AlpacaDAO canonical timeframe")
    lookback_days: int = Field(
        default=90, ge=1, le=730,
        description="Calendar days to look back (live mode only)",
    )
    start_date: Optional[str] = Field(
        default=None, description="YYYY-MM-DD — enables historical mode",
    )
    end_date: Optional[str] = Field(
        default=None, description="YYYY-MM-DD — enables historical mode",
    )

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        """Normalise ticker to upper-case and strip whitespace."""
        return v.strip().upper()

    @field_validator("timeframe")
    @classmethod
    def normalise_timeframe(cls, v: str) -> str:
        """Convert alias timeframe strings to canonical form."""
        return _normalise_timeframe(v)

    @model_validator(mode="after")
    def check_date_pair(self) -> "QuantIndicatorInput":
        """Ensure start_date and end_date are either both set or both absent."""
        has_start = self.start_date is not None
        has_end = self.end_date is not None
        if has_start != has_end:
            raise ValueError(
                "Both start_date and end_date must be provided together for historical mode "
                f"(got start_date={self.start_date!r}, end_date={self.end_date!r})"
            )
        if has_start and has_end and self.start_date >= self.end_date:
            raise ValueError(
                f"start_date {self.start_date!r} must be strictly before end_date {self.end_date!r}"
            )
        return self

    @property
    def is_historical(self) -> bool:
        """Return True when both date bounds are set."""
        return self.start_date is not None and self.end_date is not None


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


class MeanReversionInput(BaseModel):
    """Input for ``mean_reversion_analyze`` — Z-score / mean-reversion signals.

    Attributes:
        symbol: Stock ticker.
        lookback: Statistical lookback in trading bars.
        threshold: Z-score entry threshold.
        start_date: YYYY-MM-DD start (historical mode).
        end_date: YYYY-MM-DD end (historical mode).
        timeframe: Bar timeframe used only in historical mode.
    """

    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(description="Stock ticker symbol")
    lookback: int = Field(
        default=60, ge=5, le=500,
        description="Trading bars for statistical lookback window",
    )
    threshold: float = Field(
        default=2.0, ge=0.5, le=5.0,
        description="Z-score threshold for entry signal",
    )
    start_date: Optional[str] = Field(default=None, description="YYYY-MM-DD — historical mode")
    end_date: Optional[str] = Field(default=None, description="YYYY-MM-DD — historical mode")
    timeframe: str = Field(default="1Day", description="Bar timeframe (historical mode only)")

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("timeframe")
    @classmethod
    def normalise_timeframe(cls, v: str) -> str:
        return _normalise_timeframe(v)

    @model_validator(mode="after")
    def check_date_pair(self) -> "MeanReversionInput":
        has_start = self.start_date is not None
        has_end = self.end_date is not None
        if has_start != has_end:
            raise ValueError(
                "Both start_date and end_date must be provided together "
                f"(got start_date={self.start_date!r}, end_date={self.end_date!r})"
            )
        if has_start and has_end and self.start_date >= self.end_date:
            raise ValueError(
                f"start_date {self.start_date!r} must be before end_date {self.end_date!r}"
            )
        return self

    @property
    def is_historical(self) -> bool:
        return self.start_date is not None and self.end_date is not None


# ===========================================================================
# Backtester Skill — Input Models
# ===========================================================================

class BacktestInput(BaseModel):
    """Input for ``backtest_strategy``.

    Note: use the field name ``ticker`` (not ``symbol``) — the registry wrapper
    already accepts ``symbol`` as an alias and resolves it to ``ticker``.

    Attributes:
        ticker: Stock ticker.
        start_date: YYYY-MM-DD backtest start.
        end_date: YYYY-MM-DD backtest end.
        strategy: Strategy name — one of ``buy-and-hold``, ``mean-reversion``,
            ``momentum``, ``value``.
        initial_capital: Starting capital in USD.
        strategy_params: Optional strategy-specific parameter overrides.
    """

    model_config = ConfigDict(extra="ignore")

    ticker: str = Field(description="Stock ticker symbol")
    start_date: str = Field(description="YYYY-MM-DD backtest start date")
    end_date: str = Field(description="YYYY-MM-DD backtest end date")
    strategy: str = Field(
        default="mean-reversion",
        description="Strategy — buy-and-hold | mean-reversion | momentum | value",
    )
    initial_capital: float = Field(
        default=100_000.0, gt=0,
        description="Starting capital in USD",
    )
    strategy_params: Optional[Dict[str, Any]] = Field(default=None)

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        """Normalise and validate strategy name."""
        v_lower = v.lower().strip()
        if v_lower not in _VALID_STRATEGIES:
            raise ValueError(
                f"strategy must be one of {sorted(_VALID_STRATEGIES)}, got {v!r}"
            )
        return v_lower

    @model_validator(mode="after")
    def check_dates(self) -> "BacktestInput":
        if self.start_date >= self.end_date:
            raise ValueError(
                f"start_date {self.start_date!r} must be before end_date {self.end_date!r}"
            )
        return self


class DataAvailabilityInput(BaseModel):
    """Input for ``check_data_availability``.

    Attributes:
        symbol: Stock ticker.
        start_date: YYYY-MM-DD range start.
        end_date: YYYY-MM-DD range end.
        timeframe: Bar timeframe to check.
    """

    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(description="Stock ticker symbol")
    start_date: str = Field(description="YYYY-MM-DD")
    end_date: str = Field(description="YYYY-MM-DD")
    timeframe: str = Field(default="1Min", description="Bar timeframe to check")

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("timeframe")
    @classmethod
    def normalise_timeframe(cls, v: str) -> str:
        return _normalise_timeframe(v)


class HistoricalDataInput(DataAvailabilityInput):
    """Input for ``fetch_historical_data`` (same shape as DataAvailabilityInput)."""


# ===========================================================================
# Quant Skill — Output Models
# ===========================================================================

class MACDOutput(BaseModel):
    """MACD indicator values."""

    model_config = ConfigDict(extra="allow")

    value: Optional[float] = None
    signal: Optional[float] = None
    histogram: Optional[float] = None


class MomentumOutput(BaseModel):
    """Validated output from ``calc_momentum``.

    Attributes:
        symbol: Ticker.
        macd: MACD sub-object.
        rsi: Latest RSI value (0-100).
        timeframe: Bar timeframe used.
        timestamp: Result timestamp ISO string.
        mode: ``"live"`` or ``"historical"``.
        start_date: Historical range start (historical mode only).
        end_date: Historical range end (historical mode only).
        error: Error message if computation failed.
    """

    model_config = ConfigDict(extra="allow")

    symbol: str
    macd: MACDOutput = Field(default_factory=MACDOutput)
    rsi: Optional[float] = None
    timeframe: str = "1Day"
    timestamp: str = ""
    mode: str = "live"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    error: Optional[str] = None


class VolatilityOutput(BaseModel):
    """Validated output from ``calc_volatility_bands``.

    Attributes:
        symbol: Ticker.
        upper / middle / lower: Bollinger Band levels.
        bandwidth: Band width normalised to middle.
        mode: ``"live"`` or ``"historical"``.
        error: Error message if computation failed.
    """

    model_config = ConfigDict(extra="allow")

    symbol: str
    upper: Optional[float] = None
    middle: Optional[float] = None
    lower: Optional[float] = None
    bandwidth: Optional[float] = None
    timeframe: str = "1Day"
    timestamp: str = ""
    mode: str = "live"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    error: Optional[str] = None


class VolumeOutput(BaseModel):
    """Validated output from ``calc_volume_flow``.

    Attributes:
        symbol: Ticker.
        obv: On-Balance Volume latest value.
        volume_trend: ``"increasing"`` | ``"decreasing"`` | ``"neutral"``.
        avg_volume_10d: 10-day average volume.
        current_vs_avg: Ratio of current day volume to 10-day average.
        error: Error message if computation failed.
    """

    model_config = ConfigDict(extra="allow")

    symbol: str
    obv: Optional[float] = None
    volume_trend: Optional[str] = None
    avg_volume_10d: Optional[float] = None
    current_vs_avg: Optional[float] = None
    timeframe: str = "1Day"
    timestamp: str = ""
    mode: str = "live"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    error: Optional[str] = None


class CandleOutput(BaseModel):
    """Validated output from ``analyze_candle_structure``.

    Attributes:
        symbol: Ticker.
        patterns: List of detected pattern names.
        last_candle_type: ``"bullish"`` | ``"bearish"`` | ``"neutral"``.
        last_body_pct: Last candle body size as % of range.
        pattern_count: Total number of patterns detected.
        error: Error message if computation failed.
    """

    model_config = ConfigDict(extra="allow")

    symbol: str
    patterns: List[str] = Field(default_factory=list)
    last_candle_type: Optional[str] = None
    last_body_pct: Optional[float] = None
    pattern_count: int = 0
    timeframe: str = "1Day"
    timestamp: str = ""
    mode: str = "live"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    error: Optional[str] = None


# ===========================================================================
# Backtester Skill — Output Models
# ===========================================================================

class BacktestMetrics(BaseModel):
    """Full backtest performance metrics.

    All fields are optional because not every strategy or data set will
    produce every metric (e.g. sortino requires negative returns).
    """

    model_config = ConfigDict(extra="allow")

    total_return_pct: Optional[float] = None
    total_return_dollars: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    max_drawdown_dollars: Optional[float] = None
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    total_trades: Optional[int] = None
    winning_trades: Optional[int] = None
    losing_trades: Optional[int] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    avg_trade: Optional[float] = None
    largest_win: Optional[float] = None
    largest_loss: Optional[float] = None
    initial_capital: Optional[float] = None
    final_capital: Optional[float] = None
    volatility: Optional[float] = None
    calmar_ratio: Optional[float] = None


class BacktestOutput(BaseModel):
    """Validated output from ``backtest_strategy``.

    Attributes:
        status: ``"completed"`` | ``"error"``.
        strategy: Strategy name used.
        ticker: Stock ticker.
        start_date: Backtest start date.
        end_date: Backtest end date.
        run_id: Unique run identifier stored in DB.
        metrics: Full set of performance metrics.
        summary: Human-readable one-sentence summary.
        recommendation: ``"RECOMMENDED"`` | ``"NOT RECOMMENDED"`` | etc.
        trades_count: Total number of trades executed.
        error: Error message if status == ``"error"``.
    """

    model_config = ConfigDict(extra="allow")

    status: str = "completed"
    strategy: str
    ticker: str
    start_date: str
    end_date: str
    run_id: Optional[str] = None
    metrics: Optional[BacktestMetrics] = None
    summary: Optional[str] = None
    recommendation: Optional[str] = None
    trades_count: Optional[int] = None
    error: Optional[str] = None


# ===========================================================================
# Functional test
# ===========================================================================

if __name__ == "__main__":
    from pydantic import ValidationError

    print("=" * 60)
    print("models/skills.py Functional Tests")
    print("=" * 60)

    # --- QuantIndicatorInput ---
    print("\n[1/7] MomentumInput — live mode")
    m = MomentumInput(symbol="aapl", timeframe="1day", lookback_days=60)
    assert m.symbol == "AAPL"
    assert m.timeframe == "1Day"
    assert not m.is_historical
    print(f"  OK: symbol={m.symbol}, timeframe={m.timeframe}, lookback={m.lookback_days}")

    print("\n[2/7] MomentumInput — historical mode")
    m2 = MomentumInput(symbol="MSFT", start_date="2024-01-01", end_date="2024-06-30")
    assert m2.is_historical
    assert m2.start_date == "2024-01-01"
    print(f"  OK: historical mode start={m2.start_date} end={m2.end_date}")

    print("\n[3/7] MomentumInput — extra fields ignored")
    m3 = MomentumInput.model_validate({
        "symbol": "TSLA", "timeframe": "1Day", "task_id": "q001", "note": "test"
    })
    assert not hasattr(m3, "task_id") or m3.task_id is None  # extra fields ignored
    print("  OK: extra LLM fields silently discarded")

    print("\n[4/7] MomentumInput — validation error (only start_date provided)")
    try:
        MomentumInput(symbol="GOOG", start_date="2024-01-01")
        assert False, "Should have raised"
    except ValidationError as e:
        print(f"  OK: raised ValidationError — {e.errors()[0]['msg']}")

    print("\n[5/7] BacktestInput — valid")
    b = BacktestInput(ticker="spy", start_date="2023-01-01", end_date="2023-12-31", strategy="momentum")
    assert b.ticker == "SPY"
    assert b.strategy == "momentum"
    print(f"  OK: ticker={b.ticker}, strategy={b.strategy}, capital={b.initial_capital:,.0f}")

    print("\n[6/7] BacktestInput — invalid strategy")
    try:
        BacktestInput(ticker="AAPL", start_date="2023-01-01", end_date="2023-06-01", strategy="rsi_breakout")
        assert False, "Should have raised"
    except ValidationError as e:
        print(f"  OK: raised ValidationError — {e.errors()[0]['msg']}")

    print("\n[7/7] BacktestOutput — partial metrics")
    bo = BacktestOutput(
        strategy="mean-reversion",
        ticker="AAPL",
        start_date="2023-01-01",
        end_date="2023-12-31",
        metrics=BacktestMetrics(total_return_pct=12.5, sharpe_ratio=1.3),
    )
    assert bo.metrics.total_return_pct == 12.5
    print(f"  OK: BacktestOutput metrics.total_return_pct={bo.metrics.total_return_pct}")

    print("\n[ALL OK] models/skills.py tests complete")
