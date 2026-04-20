"""Shared constants, helpers, and base models for all strategy and indicator I/O.

All input models extend StrategyBaseInput; all signal output models extend
BaseSignalOutput.  Centralising these here avoids duplicating validators across
QuantIndicatorInput, the 8 new strategy inputs, and MeanReversionInput.
"""

from typing import Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Timeframe normalisation
# ---------------------------------------------------------------------------

# Aliases the LLM commonly emits → canonical forms accepted by AlpacaDAO
_TIMEFRAME_ALIASES: Dict[str, str] = {
    "1d": "1Day", "1day": "1Day", "day": "1Day", "daily": "1Day",
    "1h": "1Hour", "1hour": "1Hour", "hour": "1Hour", "hourly": "1Hour",
    "1m": "1Min", "1min": "1Min", "minute": "1Min",
}


def _normalise_timeframe(v: str) -> str:
    """Return canonical timeframe string, falling back to the raw value if unknown."""
    if not v:
        return "1Day"
    return _TIMEFRAME_ALIASES.get(v.lower(), v)


# ---------------------------------------------------------------------------
# Strategy validation
# ---------------------------------------------------------------------------

_VALID_STRATEGIES: Set[str] = {
    # L1 strategies
    "buy-and-hold", "mean-reversion", "momentum", "value",
    # Day trading
    "vwap-reversion", "opening-range-breakout", "rsi-divergence", "momentum-burst",
    # Swing
    "golden-cross", "breakout-52w", "mean-reversion-daily", "earnings-drift",
}

# Fuzzy keyword map for LLM-variant strategy names (e.g. "momentum_SMA_50_200")
_FUZZY_MAP: List[Tuple[str, List[str]]] = [
    ("mean-reversion",         ["mean", "reversion"]),
    ("buy-and-hold",           ["buy", "hold"]),
    ("momentum",               ["momentum"]),
    ("value",                  ["value"]),
    ("vwap-reversion",         ["vwap"]),
    ("opening-range-breakout", ["opening", "range"]),
    ("rsi-divergence",         ["rsi", "divergence"]),
    ("momentum-burst",         ["momentum", "burst"]),
    ("golden-cross",           ["golden", "cross"]),
    ("breakout-52w",           ["52", "breakout"]),
    ("mean-reversion-daily",   ["mean", "reversion", "daily"]),
    ("earnings-drift",         ["earnings", "drift"]),
]


# ---------------------------------------------------------------------------
# StrategyBaseInput — unified base for all input models
# ---------------------------------------------------------------------------

class StrategyBaseInput(BaseModel):
    """Unified base for all strategy and indicator input models.

    Provides symbol normalisation, timeframe alias resolution, optional
    date-range validation, and the ``is_historical`` property.  Subclasses
    declare their own defaults for ``timeframe`` and ``lookback_days`` to match
    the strategy's natural operating window.

    Supports two modes:
    - **Live mode** (default): fetch ``lookback_days`` calendar days back from today.
    - **Historical mode**: activated when *both* ``start_date`` **and** ``end_date``
      are supplied; ``lookback_days`` is ignored in this mode.

    Attributes:
        symbol: Stock ticker symbol (auto upper-cased).
        timeframe: AlpacaDAO canonical timeframe string.
        lookback_days: Calendar days to look back (live mode only).
        start_date: YYYY-MM-DD start of range (historical mode).
        end_date: YYYY-MM-DD end of range (historical mode).
    """

    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(description="Stock ticker symbol, e.g. 'AAPL'")
    timeframe: str
    lookback_days: int
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
    def check_date_pair(self) -> "StrategyBaseInput":
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


# ---------------------------------------------------------------------------
# BaseSignalOutput — shared base for strategy signal output models
# ---------------------------------------------------------------------------

class BaseSignalOutput(BaseModel):
    """Shared base for all strategy signal output models.

    Holds the scalar fields common to both ``StrategySignalOutput`` (flat signals
    from the 8 new quant strategies) and ``MeanReversionOutput`` (rich nested
    output with statistics, levels, and recommendation sub-objects).

    Attributes:
        symbol: Ticker this output is for.
        timeframe: Bar timeframe used for the analysis.
        timestamp: ISO 8601 timestamp of the analysis.
        current_price: Last known price at analysis time.
        mode: Operating mode — ``"live"`` or ``"historical"``.
        error: Non-None when analysis failed; contains the error message.
    """

    model_config = ConfigDict(extra="allow")

    symbol: str = ""
    timeframe: Optional[str] = None
    timestamp: Optional[str] = None
    current_price: Optional[float] = None
    mode: str = "live"
    error: Optional[str] = None
