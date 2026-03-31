"""Market data router — read-only AlpacaDAO endpoints at /v1/market/..."""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.semi_auto.routers._helpers import _df_to_records
from src.common.utils import get_logger
from src.semi_auto.models.endpoints import (
    BarsResponse,
    IndicatorsResponse,
    IntradayStatsResponse,
    LatestBarResponse,
    TradesResponse,
    WatchlistMemberResponse,
    WatchlistResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/market", tags=["market-data"])


def _dao():
    from src.common.dao.alpaca_dao import AlpacaDAO
    return AlpacaDAO()


# ── Watchlist ──────────────────────────────────────────────────────────────────


@router.get("/watchlist", response_model=WatchlistResponse)
async def get_watchlist(active_only: bool = Query(default=True)):
    """Return all symbols currently in the watchlist.

    Args:
        active_only: If True (default), only return active symbols.

    Returns:
        Dict with ``symbols`` list and ``count``.
    """
    try:
        dao = _dao()
        symbols = dao.get_watchlist(active_only=active_only)
        dao.close()
        return {"symbols": symbols, "count": len(symbols)}
    except Exception as exc:
        logger.warning(f"[market/watchlist] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/watchlist/{symbol}", response_model=WatchlistMemberResponse)
async def is_in_watchlist(symbol: str):
    """Check whether a symbol is in the watchlist.

    Args:
        symbol: Stock ticker (e.g. AAPL).

    Returns:
        Dict with ``symbol`` and ``in_watchlist`` bool.
    """
    try:
        dao = _dao()
        result = dao.is_in_watchlist(symbol.upper())
        dao.close()
        return {"symbol": symbol.upper(), "in_watchlist": result}
    except Exception as exc:
        logger.warning(f"[market/watchlist/{symbol}] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── OHLCV bars ─────────────────────────────────────────────────────────────────


@router.get("/bars", response_model=BarsResponse)
async def get_bars(
    symbol: str = Query(..., description="Stock ticker"),
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    timeframe: str = Query(default="1Day", description="Bar timeframe e.g. 1Min | 1Hour | 1Day"),
):
    """Fetch stored OHLCV bars for a symbol and date range.

    Returns:
        Dict with ``bars`` list and ``count``.
    """
    try:
        from datetime import datetime as _dt
        dao = _dao()
        df = dao.get_bars(symbol.upper(), _dt.fromisoformat(start), _dt.fromisoformat(end), timeframe)
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "timeframe": timeframe, "bars": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[market/bars] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/bars/{symbol}/latest", response_model=LatestBarResponse)
async def get_latest_bar(
    symbol: str,
    timeframe: str = Query(default="1Day"),
):
    """Fetch the most recent OHLCV bar for a symbol.

    Returns:
        Dict with ``symbol``, ``timeframe``, and ``bar`` (dict or null).
    """
    try:
        dao = _dao()
        bar = dao.get_latest_bar(symbol.upper(), timeframe=timeframe)
        dao.close()
        return {"symbol": symbol.upper(), "timeframe": timeframe, "bar": bar}
    except Exception as exc:
        logger.warning(f"[market/bars/{symbol}/latest] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Trades ─────────────────────────────────────────────────────────────────────


@router.get("/trades", response_model=TradesResponse)
async def get_trades(
    symbol: str = Query(..., description="Stock ticker"),
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    limit: int = Query(default=1000, ge=1, le=50000),
):
    """Fetch recent tick-level trades (live_trades ∪ historical_trades).

    Returns:
        Dict with ``trades`` list and ``count``.
    """
    try:
        from datetime import datetime as _dt
        dao = _dao()
        df = dao.get_recent_trades(symbol.upper(), _dt.fromisoformat(start), _dt.fromisoformat(end), limit=limit)
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "trades": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[market/trades] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Indicators ─────────────────────────────────────────────────────────────────


@router.get("/indicators", response_model=IndicatorsResponse)
async def get_computed_indicators(
    symbol: str = Query(...),
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    timeframe: str = Query(default="1Day"),
):
    """Fetch pre-computed technical indicators from the DB.

    Returns:
        Dict with ``indicators`` list and ``count``.
    """
    try:
        from datetime import datetime as _dt
        dao = _dao()
        df = dao.get_computed_indicators(symbol.upper(), _dt.fromisoformat(start), _dt.fromisoformat(end), timeframe)
        dao.close()
        records = _df_to_records(df)
        return {"symbol": symbol.upper(), "timeframe": timeframe, "indicators": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[market/indicators] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Intraday stats ─────────────────────────────────────────────────────────────


@router.get("/stats/{symbol}", response_model=IntradayStatsResponse)
async def get_intraday_stats(
    symbol: str,
    date: str = Query(..., description="Date YYYY-MM-DD"),
):
    """Calculate intraday OHLCV statistics for a symbol on a given date.

    Returns:
        Dict with ``symbol``, ``date``, and ``stats``.
    """
    try:
        from datetime import date as _date
        dao = _dao()
        stats = dao.calculate_intraday_stats(symbol.upper(), _date.fromisoformat(date))
        dao.close()
        return {"symbol": symbol.upper(), "date": date, "stats": stats}
    except Exception as exc:
        logger.warning(f"[market/stats/{symbol}] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
