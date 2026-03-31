"""Pydantic response models for every router endpoint.

Organises models by router so each ``response_model=`` declaration can be
imported cleanly:

    from src.semi_auto.models.endpoints import WatchlistResponse

All models use ``model_config = ConfigDict(extra="allow")`` for DAO leaf-level
records so unexpected DB columns flow through without validation errors.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Shared leaf-level models
# ---------------------------------------------------------------------------


class OHLCVBar(BaseModel):
    """A single OHLCV candlestick bar from the database.

    Extra columns (e.g. vwap, trade_count) are allowed through.
    """

    model_config = ConfigDict(extra="allow")

    t: Optional[str] = Field(None, description="Bar timestamp (ISO-8601)")
    o: Optional[float] = Field(None, description="Open price")
    h: Optional[float] = Field(None, description="High price")
    l: Optional[float] = Field(None, description="Low price")
    c: Optional[float] = Field(None, description="Close price")
    v: Optional[float] = Field(None, description="Volume")


class TradeRecord(BaseModel):
    """A single tick-level trade record."""

    model_config = ConfigDict(extra="allow")

    symbol: Optional[str] = None
    price: Optional[float] = None
    size: Optional[float] = None
    timestamp: Optional[str] = None


class IndicatorRecord(BaseModel):
    """A single row of pre-computed technical indicators."""

    model_config = ConfigDict(extra="allow")

    symbol: Optional[str] = None
    timestamp: Optional[str] = None
    timeframe: Optional[str] = None
    macd_value: Optional[float] = None
    macd_signal: Optional[float] = None
    rsi: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    obv: Optional[float] = None
    volume_trend: Optional[str] = None
    z_score: Optional[float] = None
    vwap: Optional[float] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class ComponentStatus(BaseModel):
    """Status dict for one health-check component."""

    model_config = ConfigDict(extra="allow")

    status: str


class HealthResponse(BaseModel):
    """Response for GET /v1/health (liveness).

    Attributes:
        status: Always ``"ok"`` when the server is reachable.
        graph_ready: Whether the LangGraph compiled graph is initialised.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str
    graph_ready: bool
    timestamp: str


class DetailedHealthResponse(BaseModel):
    """Response for GET /v1/health/detailed (per-component).

    Attributes:
        status: ``"ok"`` when all components report OK, else ``"degraded"``.
        components: Map of component name → :class:`ComponentStatus`.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str
    components: Dict[str, Any]
    timestamp: str


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


class PortfolioHealthResponse(BaseModel):
    """Response for GET /v1/portfolio/health.

    Attributes:
        status: ``"success"`` or ``"error"``.
        health: Raw dict from ``check_portfolio_health`` registry function.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str
    health: Dict[str, Any]
    timestamp: str


class PortfolioHistoryResponse(BaseModel):
    """Response for GET /v1/portfolio/history.

    Attributes:
        status: Always ``"success"``.
        snapshots: List of portfolio snapshot dicts from the database.
        count: Number of items returned.
        start: Requested start date (may be ``None``).
        end: Requested end date (may be ``None``).
    """

    status: str = "success"
    snapshots: List[Any] = Field(default_factory=list)
    count: int
    start: Optional[str] = None
    end: Optional[str] = None


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class CleanupResponse(BaseModel):
    """Response for POST /v1/admin/cleanup.

    Attributes:
        status: ``"success"`` or ``"error"``.
        deleted_count: Number of expired threads removed.
        dry_run: Whether this was a dry run (no actual deletion).
        detail: Optional error or informational message.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str
    deleted_count: int = 0
    dry_run: bool = True
    detail: Optional[str] = None
    timestamp: str


class AdminStatsResponse(BaseModel):
    """Response for GET /v1/admin/stats.

    Attributes:
        interactions: Total stored interaction count.
        turn_count: Total agent turn count.
        latest_snapshot: Most recent portfolio snapshot dict, or ``None``.
        timestamp: ISO-8601 UTC timestamp.
    """

    interactions: int = 0
    turn_count: int = 0
    latest_snapshot: Optional[Dict[str, Any]] = None
    timestamp: str


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class DataStreamInfo(BaseModel):
    """Sub-section of :class:`IngestionStatusResponse`."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    running: bool = False
    symbols: List[str] = Field(default_factory=list)
    task_name: Optional[str] = None


class IngestionStatusResponse(BaseModel):
    """Response for GET /v1/ingestion/status."""

    data_stream: Any
    cache: Any
    etl: Any
    timestamp: str


class TriggerETLResponse(BaseModel):
    """Response for POST /v1/ingestion/trigger-etl.

    Attributes:
        status: ``"success"`` or ``"error"``.
        message: Human-readable summary.
        total_rows: Indicator rows written, or ``None`` on error.
        symbols: Symbols processed, or ``None`` on error.
        timestamp: ISO-8601 UTC timestamp.
        error: Error detail when ``status == "error"``.
    """

    status: str
    message: str
    total_rows: Optional[int] = None
    symbols: Optional[List[str]] = None
    timestamp: str
    error: Optional[str] = None


class FlushCacheResponse(BaseModel):
    """Response for POST /v1/ingestion/flush-cache.

    Attributes:
        status: ``"success"`` or ``"error"``.
        trades_flushed: Rows written to ``live_trades`` from cache.
        trades_archived: Rows moved to ``historical_trades``.
        message: Human-readable summary.
        timestamp: ISO-8601 UTC timestamp.
        archive_warning: Non-fatal warning if archive step failed.
        error: Present only when ``status == "error"``.
    """

    status: str
    trades_flushed: int = 0
    trades_archived: int = 0
    message: Optional[str] = None
    timestamp: str
    archive_warning: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Agent / HITL
# ---------------------------------------------------------------------------


class RejectResponse(BaseModel):
    """Response for POST /v1/reject/{thread_id}.

    Attributes:
        status: Always ``"cancelled"``.
        thread_id: Thread that was cancelled.
        message: Human-readable confirmation.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str = "cancelled"
    thread_id: str
    message: str
    timestamp: str


class ConversationResponse(BaseModel):
    """Response for GET /v1/conversations/{thread_id}.

    Attributes:
        thread_id: Requested thread UUID.
        turns: Interaction turn dicts up to ``limit``.
        count: Actual number of turns returned.
    """

    thread_id: str
    turns: List[Any] = Field(default_factory=list)
    count: int


class AgentStateResponse(BaseModel):
    """Response for GET /v1/agent/state/{thread_id}.

    Attributes:
        thread_id: Requested thread UUID.
        state: LangGraph checkpoint state values (sensitive fields stripped).
    """

    thread_id: str
    state: Dict[str, Any]


class RegistryResponse(BaseModel):
    """Response for GET /v1/registry.

    Attributes:
        registry: Map of function name → parameter schema.
        count: Number of registered functions.
    """

    registry: Dict[str, Any]
    count: int


# ---------------------------------------------------------------------------
# Market data  (AlpacaDAO)
# ---------------------------------------------------------------------------


class WatchlistResponse(BaseModel):
    """Response for GET /v1/market/watchlist.

    Attributes:
        symbols: List of ticker strings.
        count: Length of ``symbols``.
    """

    symbols: List[str]
    count: int


class WatchlistMemberResponse(BaseModel):
    """Response for GET /v1/market/watchlist/{symbol}.

    Attributes:
        symbol: Upper-cased ticker.
        in_watchlist: Whether the symbol is currently in the watchlist.
    """

    symbol: str
    in_watchlist: bool


class BarsResponse(BaseModel):
    """Response for GET /v1/market/bars.

    Attributes:
        symbol: Upper-cased ticker.
        timeframe: Bar timeframe (e.g. ``"1Day"``).
        bars: List of OHLCV bar dicts.
        count: Number of bars returned.
    """

    symbol: str
    timeframe: str
    bars: List[Any] = Field(default_factory=list)
    count: int


class LatestBarResponse(BaseModel):
    """Response for GET /v1/market/bars/{symbol}/latest.

    Attributes:
        symbol: Upper-cased ticker.
        timeframe: Bar timeframe.
        bar: Most recent OHLCV bar dict, or ``None`` if no data.
    """

    symbol: str
    timeframe: str
    bar: Optional[Dict[str, Any]] = None


class TradesResponse(BaseModel):
    """Response for GET /v1/market/trades.

    Attributes:
        symbol: Upper-cased ticker.
        trades: List of tick-level trade dicts.
        count: Number of trades returned.
    """

    symbol: str
    trades: List[Any] = Field(default_factory=list)
    count: int


class IndicatorsResponse(BaseModel):
    """Response for GET /v1/market/indicators.

    Attributes:
        symbol: Upper-cased ticker.
        timeframe: Indicator timeframe.
        indicators: List of computed indicator dicts.
        count: Number of rows returned.
    """

    symbol: str
    timeframe: str
    indicators: List[Any] = Field(default_factory=list)
    count: int


class IntradayStatsResponse(BaseModel):
    """Response for GET /v1/market/stats/{symbol}.

    Attributes:
        symbol: Upper-cased ticker.
        date: Date string YYYY-MM-DD.
        stats: Intraday statistics dict, or ``None`` if unavailable.
    """

    symbol: str
    date: str
    stats: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Fundamentals  (AlphaVantageDAO)
# ---------------------------------------------------------------------------


class FundamentalsListResponse(BaseModel):
    """Response for GET /v1/fundamentals.

    Attributes:
        fundamentals: List of fundamental dicts (one per symbol).
        count: Number of symbols.
    """

    fundamentals: List[Any] = Field(default_factory=list)
    count: int


class CompanyOverviewResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}.

    Attributes:
        symbol: Upper-cased ticker.
        overview: Company overview dict, or ``None`` if not in DB.
    """

    symbol: str
    overview: Optional[Dict[str, Any]] = None


class DividendsResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}/dividends.

    Attributes:
        symbol: Upper-cased ticker.
        dividends: Dividend history rows.
        count: Number of rows.
    """

    symbol: str
    dividends: List[Any] = Field(default_factory=list)
    count: int


class EarningsResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}/earnings.

    Attributes:
        symbol: Upper-cased ticker.
        quarterly: True = quarterly data, False = annual.
        earnings: Earnings rows.
        count: Number of rows.
    """

    symbol: str
    quarterly: bool
    earnings: List[Any] = Field(default_factory=list)
    count: int


class IncomeStatementResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}/income.

    Attributes:
        symbol: Upper-cased ticker.
        income_statements: Income statement rows.
        count: Number of rows.
    """

    symbol: str
    income_statements: List[Any] = Field(default_factory=list)
    count: int


class BalanceSheetResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}/balance-sheet.

    Attributes:
        symbol: Upper-cased ticker.
        balance_sheets: Balance sheet rows.
        count: Number of rows.
    """

    symbol: str
    balance_sheets: List[Any] = Field(default_factory=list)
    count: int


class CashFlowResponse(BaseModel):
    """Response for GET /v1/fundamentals/{symbol}/cash-flow.

    Attributes:
        symbol: Upper-cased ticker.
        cash_flows: Cash flow rows.
        count: Number of rows.
    """

    symbol: str
    cash_flows: List[Any] = Field(default_factory=list)
    count: int


# ---------------------------------------------------------------------------
# Analyst  (AnalystDAO)
# ---------------------------------------------------------------------------


class AnalystSymbolsResponse(BaseModel):
    """Response for GET /v1/analyst/symbols.

    Attributes:
        symbols: List of tickers with analyst data.
        count: Number of symbols.
    """

    symbols: List[str]
    count: int


class EODSummariesResponse(BaseModel):
    """Response for GET /v1/analyst/{symbol}/eod (date range).

    Attributes:
        symbol: Upper-cased ticker.
        summaries: Analyst EOD summary rows.
        count: Number of rows.
    """

    symbol: str
    summaries: List[Any] = Field(default_factory=list)
    count: int


class LatestEODResponse(BaseModel):
    """Response for GET /v1/analyst/{symbol}/eod/latest.

    Attributes:
        symbol: Upper-cased ticker.
        summary: Most recent EOD summary dict, or ``None`` if no data.
    """

    symbol: str
    summary: Optional[Dict[str, Any]] = None


class RecentEODsResponse(BaseModel):
    """Response for GET /v1/analyst/{symbol}/eod/recent.

    Attributes:
        symbol: Upper-cased ticker.
        summaries: Up to ``count`` most recent EOD summary dicts.
        count: Actual number returned.
    """

    symbol: str
    summaries: List[Any] = Field(default_factory=list)
    count: int


# ---------------------------------------------------------------------------
# Strategy  (StrategyDAO)
# ---------------------------------------------------------------------------


class ActionableSignalsResponse(BaseModel):
    """Response for GET /v1/strategy/actionable.

    Attributes:
        signals: Signals meeting the confidence threshold.
        count: Number of signals.
    """

    signals: List[Any] = Field(default_factory=list)
    count: int


class StrategyPerformanceResponse(BaseModel):
    """Response for GET /v1/strategy/{strategy_name}/performance.

    Attributes:
        strategy_name: Name of the strategy.
        days: Look-back window in days.
        performance: Performance stats dict, or ``None`` if no data.
    """

    strategy_name: str
    days: int
    performance: Optional[Dict[str, Any]] = None


class LatestSignalResponse(BaseModel):
    """Response for GET /v1/strategy/{symbol}/{strategy_name}/latest.

    Attributes:
        symbol: Upper-cased ticker.
        strategy_name: Strategy name.
        signal: Most recent signal dict, or ``None``.
    """

    symbol: str
    strategy_name: str
    signal: Optional[Dict[str, Any]] = None


class RecentSignalsResponse(BaseModel):
    """Response for GET /v1/strategy/{symbol}/{strategy_name}/signals.

    Attributes:
        symbol: Upper-cased ticker.
        strategy_name: Strategy name.
        signals: Recent signal rows.
        count: Number of rows.
    """

    symbol: str
    strategy_name: str
    signals: List[Any] = Field(default_factory=list)
    count: int


# ---------------------------------------------------------------------------
# Backtest  (BacktestDAO)
# ---------------------------------------------------------------------------


class BacktestRunsResponse(BaseModel):
    """Response for GET /v1/backtest/runs.

    Attributes:
        runs: List of backtest run summary dicts.
        count: Number of runs.
    """

    runs: List[Any] = Field(default_factory=list)
    count: int


class BacktestRunResponse(BaseModel):
    """Response for GET /v1/backtest/runs/{run_id}.

    Attributes:
        run_id: Run identifier.
        run: Run detail dict, or ``None`` if not found.
    """

    run_id: str
    run: Optional[Dict[str, Any]] = None


class BacktestTradesResponse(BaseModel):
    """Response for GET /v1/backtest/runs/{run_id}/trades.

    Attributes:
        run_id: Run identifier.
        trades: Trade rows for the run.
        count: Number of trade rows.
    """

    run_id: str
    trades: List[Any] = Field(default_factory=list)
    count: int


class BacktestPerformanceResponse(BaseModel):
    """Response for GET /v1/backtest/runs/{run_id}/performance.

    Attributes:
        run_id: Run identifier.
        performance: Daily performance rows.
        count: Number of rows.
    """

    run_id: str
    performance: List[Any] = Field(default_factory=list)
    count: int


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


class RootResponse(BaseModel):
    """Response for GET /.

    Attributes:
        name: API name.
        version: Semver string.
        description: One-line description.
        port: Configured port.
        endpoints: Map of path → description.
    """

    name: str
    version: str
    description: str
    port: Any
    endpoints: Dict[str, str]


if __name__ == "__main__":
    """Smoke test: instantiate key models."""
    print("=" * 60)
    print("models/endpoints.py smoke tests")
    print("=" * 60)

    w = WatchlistResponse(symbols=["AAPL", "MSFT"], count=2)
    assert w.count == 2
    print("[OK] WatchlistResponse")

    b = BarsResponse(symbol="AAPL", timeframe="1Day", bars=[{"c": 155.0}], count=1)
    assert b.symbol == "AAPL"
    print("[OK] BarsResponse")

    h = HealthResponse(status="ok", graph_ready=True, timestamp="2024-01-01T00:00:00Z")
    assert h.graph_ready is True
    print("[OK] HealthResponse")

    r = RejectResponse(thread_id="t1", message="cancelled", timestamp="2024-01-01T00:00:00Z")
    assert r.status == "cancelled"
    print("[OK] RejectResponse")

    print("\n[ALL OK] models/endpoints.py smoke tests passed")
