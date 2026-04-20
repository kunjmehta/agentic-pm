"""Shared leaf-level data record models used across multiple endpoint responses."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
