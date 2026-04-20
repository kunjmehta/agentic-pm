"""Response models for market data endpoints (AlpacaDAO)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
