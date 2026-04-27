"""Strategy router — read-only AnalysisDAO endpoints at /v1/strategy/..."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from src.common.dao.analysis_dao import AnalysisDAO
from src.server.registry.register_strategies import ensure_strategies_registered
from src.common.registry.strategy_registry import get_registry
from src.common.utils import get_logger
from src.server.models.endpoints import (
    ActionableSignalsResponse,
    LatestSignalResponse,
    RecentSignalsResponse,
    StrategyPerformanceResponse,
)
from src.server.routers._helpers import _df_to_records, dao_context, handle_http_errors, run_in_thread

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/strategy", tags=["strategy"])


@router.get("/actionable", response_model=ActionableSignalsResponse)
@handle_http_errors
async def get_actionable_signals(
    min_confidence: float = Query(default=0.7, ge=0.0, le=1.0),
    action: Optional[str] = Query(None, description="Filter by action e.g. 'buy' | 'sell'"),
) -> Dict[str, Any]:
    """Return all strategy signals that meet the confidence threshold.

    Args:
        min_confidence: Minimum confidence score (0–1, default 0.7).
        action: Optional action filter (buy / sell / hold).

    Returns:
        Dict with ``signals`` list and ``count``.
    """
    def _fetch():
        with dao_context(AnalysisDAO) as dao:
            return dao.get_actionable_signals(min_confidence=min_confidence, action_filter=action)

    records = _df_to_records(await run_in_thread(_fetch))
    return {"signals": records, "count": len(records)}


@router.get("/{strategy_name}/performance", response_model=StrategyPerformanceResponse)
@handle_http_errors
async def get_strategy_performance(
    strategy_name: str,
    days: int = Query(default=30, ge=1, le=365),
) -> Dict[str, Any]:
    """Return performance statistics for a strategy over the last N days.

    Returns:
        Dict with ``strategy_name``, ``days``, and ``performance``.
    """
    def _fetch():
        with dao_context(AnalysisDAO) as dao:
            return dao.get_strategy_performance(strategy_name, days=days)

    perf = await run_in_thread(_fetch)
    return {"strategy_name": strategy_name, "days": days, "performance": perf}


@router.get("/{symbol}/{strategy_name}/latest", response_model=LatestSignalResponse)
@handle_http_errors
async def get_latest_signal(symbol: str, strategy_name: str) -> Dict[str, Any]:
    """Return the most recent signal for a symbol + strategy combination.

    Returns:
        Dict with ``symbol``, ``strategy_name``, and ``signal`` (dict or null).
    """
    def _fetch():
        with dao_context(AnalysisDAO) as dao:
            return dao.get_latest_signal(symbol.upper(), strategy_name)

    signal = await run_in_thread(_fetch)
    return {"symbol": symbol.upper(), "strategy_name": strategy_name, "signal": signal}


@router.get("/{symbol}/{strategy_name}/signals", response_model=RecentSignalsResponse)
@handle_http_errors
async def get_recent_signals(
    symbol: str,
    strategy_name: str,
    limit: int = Query(default=10, ge=1, le=200),
) -> Dict[str, Any]:
    """Return recent signals for a symbol + strategy combination.

    Returns:
        Dict with ``signals`` list and ``count``.
    """
    def _fetch():
        with dao_context(AnalysisDAO) as dao:
            return dao.get_recent_signals(symbol.upper(), strategy_name, limit=limit)

    records = _df_to_records(await run_in_thread(_fetch))
    return {
        "symbol": symbol.upper(),
        "strategy_name": strategy_name,
        "signals": records,
        "count": len(records),
    }


# ── On-demand signal generation ───────────────────────────────────────────────


class RunSignalsRequest(BaseModel):
    """Request body for on-demand strategy-signal generation.

    Attributes:
        symbol: Stock ticker (case-insensitive, normalised to upper-case).
        strategy_name: Registered strategy name or ``"all"`` to run every
            strategy applicable to *timeframe*.
        timeframe: AlpacaDAO canonical timeframe string (default ``"1Min"``).
        lookback_bars: How many historical bars to fetch for the run.
        params_override: Optional flat dict of config-key overrides passed
            to the skill's ``analyze_bars`` call.
    """

    symbol: str = Field(..., description="Ticker symbol, e.g. 'AAPL'")
    strategy_name: str = Field(default="all", description="Strategy name or 'all'")
    timeframe: str = Field(default="1Min", description="Bar timeframe, e.g. '1Min', '1Day'")
    lookback_bars: int = Field(default=300, ge=10, le=2000)
    params_override: Optional[Dict[str, Any]] = Field(default=None)


@router.post("/signals/run", response_model=Dict[str, Any])
@handle_http_errors
async def run_signals_on_demand(body: RunSignalsRequest = Body(...)) -> Dict[str, Any]:
    """Trigger on-demand strategy signal generation for a symbol.

    Fetches the most recent *lookback_bars* bars for *symbol* / *timeframe*,
    runs the requested strategy (or all applicable strategies when
    ``strategy_name == "all"``), persists every signal to AnalysisDAO, and
    returns a summary dict.

    Args:
        body: ``RunSignalsRequest`` payload.

    Returns:
        Dict with ``symbol``, ``timeframe``, ``strategy_name``, ``results``,
        and ``count``.

    Raises:
        HTTPException 400: Unknown strategy name.
        HTTPException 404: No bars found for symbol/timeframe.
    """
    symbol = body.symbol.upper()
    timeframe = body.timeframe

    # Validate strategy name against registry (not a hardcoded list)
    ensure_strategies_registered()
    registry = get_registry()
    if body.strategy_name != "all" and registry.get_metadata(body.strategy_name) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown strategy '{body.strategy_name}'. "
                f"Registered: {registry.get_all_names()}"
            ),
        )

    from datetime import datetime, timedelta
    from src.common.utils.container import get_alpaca_dao

    def _fetch_bars():
        end = datetime.now()
        # approximate: lookback_bars * minutes per bar → convert to days
        _mins_per_bar = {"1Min": 1, "5Min": 5, "15Min": 15, "1H": 60, "1Day": 1440}.get(timeframe, 1)
        lookback_days = max(1, (body.lookback_bars * _mins_per_bar) // 390 + 1)
        start = end - timedelta(days=lookback_days)
        return get_alpaca_dao().get_bars(symbol, start=start, end=end, timeframe=timeframe)

    bars = await run_in_thread(_fetch_bars)
    if bars is None or bars.empty:
        raise HTTPException(status_code=404, detail=f"No bars found for {symbol}/{timeframe}")

    from src.common.ingestion import get_indicators_etl
    await get_indicators_etl().trigger_bar_computation(symbol, timeframe)

    strategies_to_query: List[str] = (
        registry.list_by_timeframe(timeframe)
        if body.strategy_name == "all"
        else [body.strategy_name]
    )

    def _fetch_signals():
        results = []
        with dao_context(AnalysisDAO) as dao:
            for strat in strategies_to_query:
                sig = dao.get_latest_signal(symbol, strat)
                if sig:
                    results.append(sig)
        return results

    results = await run_in_thread(_fetch_signals)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "strategy_name": body.strategy_name,
        "results": results,
        "count": len(results),
    }


# ── Registry API Endpoints ───────────────────────────────────────────────────


@router.get("/registry/list", response_model=Dict[str, Any])
@handle_http_errors
async def list_all_strategies(
    category: Optional[str] = Query(None, description="Filter by category (intraday, daily)"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe (1Min, 5Min, 1Day)"),
    tag: Optional[str] = Query(None, description="Filter by tag (mean-reversion, volume, etc.)"),
) -> Dict[str, Any]:
    """List all registered strategies with optional filters.

    Returns:
        Dict with ``strategies``, ``count``, and ``filters``.
    """
    ensure_strategies_registered()
    registry = get_registry()

    if category:
        names = registry.list_by_category(category)
    elif timeframe:
        names = registry.list_by_timeframe(timeframe)
    elif tag:
        names = registry.list_by_tag(tag)
    else:
        names = registry.get_all_names()

    strategies = [
        metadata.to_dict()
        for name in names
        if (metadata := registry.get_metadata(name)) is not None
    ]
    return {
        "strategies": strategies,
        "count": len(strategies),
        "filters": {"category": category, "timeframe": timeframe, "tag": tag},
    }


@router.get("/registry/{strategy_name}", response_model=Dict[str, Any])
@handle_http_errors
async def get_strategy_metadata(strategy_name: str) -> Dict[str, Any]:
    """Get detailed metadata for a specific strategy.

    Returns:
        Strategy metadata dict.

    Raises:
        HTTPException 404: Strategy not found.
    """
    ensure_strategies_registered()
    registry = get_registry()
    metadata = registry.get_metadata(strategy_name)
    if metadata is None:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{strategy_name}' not found. Available: {registry.get_all_names()}",
        )
    return metadata.to_dict()
