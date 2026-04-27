"""Output models for all quant, backtester, and portfolio skill functions.

``StrategySignalOutput`` and ``MeanReversionOutput`` share the scalar fields
defined in ``BaseSignalOutput`` (from .shared).  All other output models are
stand-alone Pydantic classes.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.server.models.strategies.shared import BaseSignalOutput

# ===========================================================================
# Quant Indicator Outputs
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

    symbol: str = ""
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

    symbol: str = ""
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

    symbol: str = ""
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

    symbol: str = ""
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
# Backtester Outputs
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
# MeanReversion Skill — Output Models
# ===========================================================================


class MeanReversionStatistics(BaseModel):
    """Statistics sub-object for MeanReversionOutput."""

    model_config = ConfigDict(extra="allow")

    mean: Optional[float] = None
    std_dev: Optional[float] = None
    z_score: Optional[float] = None
    percentile: Optional[float] = None
    vwap: Optional[float] = None


class MeanReversionMovingAverages(BaseModel):
    """Moving averages sub-object for MeanReversionOutput."""

    model_config = ConfigDict(extra="allow")

    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    ema_20: Optional[float] = None


class MeanReversionSignals(BaseModel):
    """Signals sub-object for MeanReversionOutput."""

    model_config = ConfigDict(extra="allow")

    current_state: str = "unknown"
    z_score_signal: str = "unknown"
    ma_cross_signal: str = "unknown"
    bollinger_signal: str = "unknown"
    overall_signal: str = "hold"


class MeanReversionLevels(BaseModel):
    """Price levels sub-object for MeanReversionOutput."""

    model_config = ConfigDict(extra="allow")

    resistance: Optional[float] = None
    support: Optional[float] = None
    upper_band: Optional[float] = None
    lower_band: Optional[float] = None


class MeanReversionRecommendation(BaseModel):
    """Trade recommendation sub-object for MeanReversionOutput."""

    model_config = ConfigDict(extra="allow")

    action: str = "hold"
    confidence: float = 0.0
    reason: str = ""
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class MeanReversionOutput(BaseSignalOutput):
    """Validated output from ``mean_reversion_analyze``.

    Extends BaseSignalOutput with nested sub-objects for statistics, moving
    averages, signals, price levels, and a trade recommendation.

    Attributes:
        statistics: Z-score, mean, std-dev, percentile, optional VWAP.
        moving_averages: SMA-20, SMA-50, EMA-20.
        signals: Per-indicator signals and combined overall_signal.
        levels: Support, resistance, Bollinger band bounds.
        trade_recommendation: action, confidence, entry/stop/target levels.
        parameters: Lookback, threshold, ma_period used.
    """

    timeframe: str = "1Day"   # concrete default (overrides Optional[str] from base)
    timestamp: str = ""        # non-optional default for this output
    statistics: Optional[MeanReversionStatistics] = None
    moving_averages: Optional[MeanReversionMovingAverages] = None
    signals: Optional[MeanReversionSignals] = None
    levels: Optional[MeanReversionLevels] = None
    trade_recommendation: Optional[MeanReversionRecommendation] = None
    parameters: Optional[Dict[str, Any]] = None


class StrategySignalOutput(BaseSignalOutput):
    """Generic signal output for all 8 new quant strategy wrappers.

    Extends BaseSignalOutput with flat trade-signal fields (action, confidence,
    entry/stop/target).  Extra fields emitted by individual strategies (e.g.
    ``deviation_pct``, ``high_52w``, ``bar_return_pct``) are preserved via
    ``extra="allow"`` (inherited from BaseSignalOutput).

    Attributes:
        action: ``"buy"`` | ``"sell"`` | ``"hold"``.
        confidence: Conviction score 0–1.
        entry_price: Suggested entry price (null for hold).
        stop_loss: Stop-loss price (null for hold).
        take_profit: Take-profit target (null for hold).
        reason: Human-readable explanation.
    """

    action: str = "hold"
    confidence: float = 0.0
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: Optional[str] = None


# ===========================================================================
# Portfolio Skill — Output Models
# ===========================================================================


class PortfolioStatusOutput(BaseModel):
    """Validated output from ``get_portfolio_status``.

    Attributes:
        equity: Total portfolio value.
        cash: Available cash balance.
        buying_power: Margin buying power.
        long_positions: Number of long positions.
        short_positions: Number of short positions.
        portfolio_value: Portfolio market value.
        last_equity: Previous equity value.
        timestamp: ISO timestamp of the snapshot.
    """

    model_config = ConfigDict(extra="allow")

    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    long_positions: int = 0
    short_positions: int = 0
    portfolio_value: float = 0.0
    last_equity: float = 0.0
    timestamp: str = ""
    error: Optional[str] = None


class PositionsSummaryOutput(BaseModel):
    """Validated output from ``get_positions_summary``.

    Attributes:
        positions: List of position dicts from Alpaca.
        count: Number of open positions.
        total_market_value: Sum of market values across all positions.
        total_unrealized_pl: Sum of unrealized P&L across all positions.
        timestamp: ISO timestamp.
    """

    model_config = ConfigDict(extra="allow")

    positions: List[Dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    total_market_value: float = 0.0
    total_unrealized_pl: float = 0.0
    timestamp: str = ""
    error: Optional[str] = None


class HealthViolation(BaseModel):
    """A single risk-rule violation or warning."""

    model_config = ConfigDict(extra="allow")

    rule: str = ""
    symbol: Optional[str] = None
    current: Optional[float] = None
    limit: Optional[float] = None
    message: str = ""


class HealthRiskParams(BaseModel):
    """Risk parameters used during portfolio health check."""

    model_config = ConfigDict(extra="allow")

    position_limit_percent: Optional[float] = None
    max_position_size: Optional[float] = None
    daily_loss_limit: Optional[float] = None


class HealthCheckOutput(BaseModel):
    """Validated output from ``check_portfolio_health``.

    Attributes:
        health_status: ``"healthy"`` | ``"warning"`` | ``"unhealthy"``.
        violations: Hard risk-rule breaches.
        warnings: Soft risk-rule warnings.
        checks_performed: Names of checks that were run.
        risk_parameters_used: Thresholds used for evaluation.
    """

    model_config = ConfigDict(extra="allow")

    health_status: str = "healthy"
    violations: List[HealthViolation] = Field(default_factory=list)
    warnings: List[HealthViolation] = Field(default_factory=list)
    checks_performed: List[str] = Field(default_factory=list)
    risk_parameters_used: Optional[HealthRiskParams] = None
    timestamp: str = ""
    error: Optional[str] = None


class FetchHistoricalDataOutput(BaseModel):
    """Validated output from ``fetch_historical_data``.

    Attributes:
        status: ``"success"`` | ``"error"``.
        bars_fetched: Number of bars fetched or found in cache.
        data_source: ``"alpaca_api"`` | ``"database_cache"`` | None.
    """

    model_config = ConfigDict(extra="allow")

    status: str = "success"
    bars_fetched: Optional[int] = None
    symbol: Optional[str] = None
    date_range: Optional[str] = None
    timeframe: Optional[str] = None
    message: Optional[str] = None
    data_source: Optional[str] = None
    error: Optional[str] = None
    suggestion: Optional[str] = None


class DataAvailabilityOutput(BaseModel):
    """Validated output from ``check_data_availability``.

    Attributes:
        available: ``True`` (full coverage), ``False`` (no data),
            or ``"partial"`` (< 80% coverage).
        bar_count: Bars found in the database.
        expected_bars: Expected bar count for the date range.
        coverage_pct: Percentage of expected bars found.
        action_needed: Suggested follow-up action.
    """

    model_config = ConfigDict(extra="allow")

    available: Any = False
    bar_count: int = 0
    expected_bars: Optional[int] = None
    coverage_pct: Optional[float] = None
    symbol: Optional[str] = None
    date_range: Optional[str] = None
    message: Optional[str] = None
    action_needed: Optional[str] = None
    error: Optional[str] = None


# ===========================================================================
# Snapshot + Simulation Output Models
# ===========================================================================


class SnapshotSaveOutput(BaseModel):
    """Validated output from ``save_eod_snapshot``.

    Attributes:
        status: ``"success"`` | ``"error"``.
        snapshot_id: DB row ID of the saved snapshot.
        positions_count: Number of positions in the snapshot.
    """

    model_config = ConfigDict(extra="allow")

    status: str = "success"
    message: Optional[str] = None
    snapshot_id: Optional[Any] = None
    date: Optional[str] = None
    positions_count: Optional[int] = None
    long_positions: Optional[int] = None
    short_positions: Optional[int] = None
    error: Optional[str] = None


class SimulationOutput(BaseModel):
    """Shared base for snapshot-worth and swap-simulation results.

    Attributes:
        initial_worth: Portfolio value at the snapshot date.
        final_worth: Portfolio value at end_date.
        return_pct: Percentage return over the period.
        return_dollars: Dollar return over the period.
    """

    model_config = ConfigDict(extra="allow")

    snapshot_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_worth: Optional[float] = None
    final_worth: Optional[float] = None
    return_pct: Optional[float] = None
    return_dollars: Optional[float] = None
    positions_at_end: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    error: Optional[str] = None


class SnapshotWorthOutput(SimulationOutput):
    """Validated output from ``snapshot_worth`` — no position swaps applied."""


class SwapPositionsOutput(SimulationOutput):
    """Validated output from ``swap_positions`` — includes swap metadata."""

    swaps_applied: Optional[Dict[str, Any]] = None
    initial_worth_before_swap: Optional[float] = None
