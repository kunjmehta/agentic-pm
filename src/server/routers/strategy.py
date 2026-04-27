"""Strategy router — read-only StrategyDAO endpoints at /v1/strategy/..."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from src.server.routers._helpers import _df_to_records
from src.common.utils import get_logger
from src.server.models.endpoints import (
    ActionableSignalsResponse,
    LatestSignalResponse,
    RecentSignalsResponse,
    StrategyPerformanceResponse,
)
from src.server.models.strategies import StrategySignalOutput

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/strategy", tags=["strategy"])


def _dao():
    from src.common.dao.strategy_dao import StrategyDAO
    return StrategyDAO()


@router.get("/actionable", response_model=ActionableSignalsResponse)
async def get_actionable_signals(
    min_confidence: float = Query(default=0.7, ge=0.0, le=1.0),
    action: Optional[str] = Query(None, description="Filter by action e.g. 'buy' | 'sell'"),
):
    """Return all strategy signals that meet the confidence threshold.

    Args:
        min_confidence: Minimum confidence score (0–1, default 0.7).
        action: Optional action filter (buy / sell / hold).

    Returns:
        Dict with ``signals`` list and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_actionable_signals(min_confidence=min_confidence, action_filter=action)
        dao.close()
        records = _df_to_records(df)
        return {"signals": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[strategy/actionable] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{strategy_name}/performance", response_model=StrategyPerformanceResponse)
async def get_strategy_performance(
    strategy_name: str,
    days: int = Query(default=30, ge=1, le=365),
):
    """Return performance statistics for a strategy over the last N days.

    Returns:
        Dict with ``strategy_name``, ``days``, and ``performance``.
    """
    try:
        dao = _dao()
        perf = dao.get_strategy_performance(strategy_name, days=days)
        dao.close()
        return {"strategy_name": strategy_name, "days": days, "performance": perf}
    except Exception as exc:
        logger.warning(f"[strategy/{strategy_name}/performance] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/{strategy_name}/latest", response_model=LatestSignalResponse)
async def get_latest_signal(symbol: str, strategy_name: str):
    """Return the most recent signal for a symbol + strategy combination.

    Returns:
        Dict with ``symbol``, ``strategy_name``, and ``signal`` (dict or null).
    """
    try:
        dao = _dao()
        signal = dao.get_latest_signal(symbol.upper(), strategy_name)
        dao.close()
        return {"symbol": symbol.upper(), "strategy_name": strategy_name, "signal": signal}
    except Exception as exc:
        logger.warning(f"[strategy/{symbol}/{strategy_name}/latest] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{symbol}/{strategy_name}/signals", response_model=RecentSignalsResponse)
async def get_recent_signals(
    symbol: str,
    strategy_name: str,
    limit: int = Query(default=10, ge=1, le=200),
):
    """Return recent signals for a symbol + strategy combination.

    Returns:
        Dict with ``signals`` list and ``count``.
    """
    try:
        dao = _dao()
        df = dao.get_recent_signals(symbol.upper(), strategy_name, limit=limit)
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "strategy_name": strategy_name, "signals": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[strategy/{symbol}/{strategy_name}/signals] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── On-demand signal generation ───────────────────────────────────────────────

class RunSignalsRequest(BaseModel):
    """Request body for on-demand strategy-signal generation.

    Attributes:
        symbol: Stock ticker (case-insensitive, normalised to upper-case).
        strategy_name: One of the 9 supported strategy names or ``"all"``
            to run every strategy applicable to *timeframe*.
        timeframe: AlpacaDAO canonical timeframe string (default ``"1Min"``).
        lookback_bars: How many historical bars to fetch for the run
            (default 300 — enough for golden-cross / 52w-breakout warmup).
        params_override: Optional flat dict of config-key overrides passed
            directly to the skill's ``analyze_bars`` call (e.g.
            ``{"lookback": 50, "threshold": 3.0}``).
    """

    symbol: str = Field(..., description="Ticker symbol, e.g. 'AAPL'")
    strategy_name: str = Field(
        default="all",
        description=(
            "Strategy name or 'all'.  Valid names: mean-reversion, "
            "vwap-reversion, opening-range-breakout, rsi-divergence, "
            "momentum-burst, golden-cross, breakout-52w, "
            "mean-reversion-daily, earnings-drift"
        ),
    )
    timeframe: str = Field(default="1Min", description="Bar timeframe, e.g. '1Min', '1Day'")
    lookback_bars: int = Field(default=300, ge=10, le=2000)
    params_override: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional param overrides forwarded to analyze_bars.",
    )


_STRATEGY_TO_TIMEFRAME: Dict[str, str] = {
    "mean-reversion": "intraday",
    "vwap-reversion": "intraday",
    "opening-range-breakout": "intraday",
    "rsi-divergence": "intraday",
    "momentum-burst": "intraday",
    "golden-cross": "1Day",
    "breakout-52w": "1Day",
    "mean-reversion-daily": "1Day",
    "earnings-drift": "1Day",
}


@router.post("/signals/run", response_model=Dict[str, Any])
async def run_signals_on_demand(body: RunSignalsRequest = Body(...)):
    """Trigger on-demand strategy signal generation for a symbol.

    Fetches the most recent *lookback_bars* bars for *symbol* / *timeframe*,
    runs the requested strategy (or all applicable strategies when
    ``strategy_name == "all"``), persists every signal to StrategyDAO, and
    returns a summary dict.

    Args:
        body: ``RunSignalsRequest`` payload.

    Returns:
        Dict with ``symbol``, ``timeframe``, ``strategy_name``, ``results``
        (list of ``StrategySignalOutput``-compatible dicts), and ``count``.

    Raises:
        HTTPException 400: Unknown strategy name.
        HTTPException 500: Any unexpected error.
    """
    symbol = body.symbol.upper()
    timeframe = body.timeframe

    if body.strategy_name != "all" and body.strategy_name not in _STRATEGY_TO_TIMEFRAME:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{body.strategy_name}'. "
                   f"Valid strategies: {sorted(_STRATEGY_TO_TIMEFRAME)} + 'all'",
        )

    try:
        from src.common.dao.alpaca_dao import AlpacaDAO
        from src.common.config import config as cfg

        a_dao = AlpacaDAO()
        bars = a_dao.get_bars(symbol, timeframe=timeframe, limit=body.lookback_bars)
        a_dao.close()

        if bars is None or bars.empty:
            raise HTTPException(status_code=404, detail=f"No bars found for {symbol}/{timeframe}")

        from src.common.data_gatherer.db_stream_handlers import (
            _run_all_strategy_signals,
        )

        await _run_all_strategy_signals(symbol, timeframe, bars, cfg)

        # Return the freshest signal for each strategy from StrategyDAO
        from src.common.dao.strategy_dao import StrategyDAO
        s_dao = StrategyDAO()

        if body.strategy_name == "all":
            strategies_to_query = [
                s for s, tf in _STRATEGY_TO_TIMEFRAME.items()
                if tf == "intraday" and timeframe != "1Day"
                or tf == "1Day" and timeframe == "1Day"
            ]
        else:
            strategies_to_query = [body.strategy_name]

        results = []
        for strat in strategies_to_query:
            sig = s_dao.get_latest_signal(symbol, strat)
            if sig:
                results.append(sig)
        s_dao.close()

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_name": body.strategy_name,
            "results": results,
            "count": len(results),
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[strategy/signals/run] {symbol} {timeframe}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
