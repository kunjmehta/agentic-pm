"""Data availability pre-check node for the semi-auto multi-agent system.

Runs immediately after ``classify_intent`` so every downstream reasoning
agent (quant, backtester) knows exactly what data already exists in the
database before deciding which functions to call.

Three independent checks are performed against AlpacaDAO:

* **indicators_available** — pre-computed rows exist in ``computed_indicators``
  for this symbol + 1Min timeframe within the last 24 hours (i.e. the stream
  pipeline has already run for today).
* **bars_available** — ``market_bars`` contains sufficient 1Min OHLCV data for
  the symbol (≥ the configured strategy lookback, default 120 bars).
* **trades_available** — ``historical_trades`` contains at least one trade
  record for the symbol in the last 24 hours.

All checks are non-blocking: any database error causes that flag to be set to
``False`` with a warning log — the graph is **never** blocked by a failed check.

If no symbol was extracted by the classifier (e.g. a pure portfolio query), all
three flags are set to ``False`` and the node returns immediately.

Sets state field: ``data_availability``
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger, config

logger = get_logger(__name__)

# How far back to look for "recent" indicator / trade rows (hours).
_RECENCY_HOURS: int = 24
# How far back to look for bar availability (calendar days).
_BARS_LOOKBACK_DAYS: int = 90
# Minimum bar count required to declare bars_available=True.
_MIN_BARS: int = 120  # matches strategy.mean_reversion.lookback default


def _check_indicators(symbol: str, timeframe: str, now: datetime) -> Dict[str, Any]:
    """Check whether pre-computed indicators exist for *symbol* in the last 24 h.

    Args:
        symbol: Upper-cased stock ticker.
        timeframe: Bar timeframe string (e.g. ``"1Min"``).
        now: Reference timestamp for the recency window.

    Returns:
        Dict with ``available`` (bool), ``row_count`` (int), and
        ``latest_ts`` (ISO string or None).
    """
    try:
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        df = dao.get_computed_indicators(
            symbol,
            start=now - timedelta(hours=_RECENCY_HOURS),
            end=now,
            timeframe=timeframe,
        )
        dao.close()
        row_count = len(df) if df is not None else 0
        latest_ts: Optional[str] = None
        if row_count > 0 and "timestamp" in df.columns:
            raw = df["timestamp"].max()
            latest_ts = str(raw) if raw is not None else None
        return {"available": row_count > 0, "row_count": row_count, "latest_ts": latest_ts}
    except Exception as exc:
        logger.warning(f"[data_avail] indicator check failed for {symbol}/{timeframe}: {exc}")
        return {"available": False, "row_count": 0, "latest_ts": None}


def _check_bars(symbol: str, timeframe: str, now: datetime) -> Dict[str, Any]:
    """Check whether sufficient OHLCV bars exist for *symbol*.

    Args:
        symbol: Upper-cased stock ticker.
        timeframe: Bar timeframe string.
        now: Reference timestamp.

    Returns:
        Dict with ``available`` (bool), ``bar_count`` (int), and
        ``latest_ts`` (ISO string or None).
    """
    try:
        from src.common.dao import AlpacaDAO
        min_bars = int(config.get("strategy.mean_reversion.lookback", default=_MIN_BARS))
        dao = AlpacaDAO()
        df = dao.get_bars(
            symbol=symbol,
            start=now - timedelta(days=_BARS_LOOKBACK_DAYS),
            end=now,
            timeframe=timeframe,
        )
        dao.close()
        bar_count = len(df) if df is not None else 0
        latest_ts: Optional[str] = None
        if bar_count > 0 and "timestamp" in df.columns:
            latest_ts = str(df["timestamp"].max())
        return {
            "available": bar_count >= min_bars,
            "bar_count": bar_count,
            "latest_ts": latest_ts,
        }
    except Exception as exc:
        logger.warning(f"[data_avail] bars check failed for {symbol}/{timeframe}: {exc}")
        return {"available": False, "bar_count": 0, "latest_ts": None}


def _check_trades(symbol: str, now: datetime) -> Dict[str, Any]:
    """Check whether recent trade records exist for *symbol*.

    Args:
        symbol: Upper-cased stock ticker.
        now: Reference timestamp.

    Returns:
        Dict with ``available`` (bool) and ``trade_count`` (int).
    """
    try:
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        df = dao.get_trades(
            symbol,
            start=now - timedelta(hours=_RECENCY_HOURS),
            end=now,
        )
        dao.close()
        trade_count = len(df) if df is not None else 0
        return {"available": trade_count > 0, "trade_count": trade_count}
    except Exception as exc:
        logger.warning(f"[data_avail] trades check failed for {symbol}: {exc}")
        return {"available": False, "trade_count": 0}


def data_availability_node(state: dict) -> dict:
    """Pre-check data availability for the resolved symbol before agent reasoning.

    Runs immediately after ``classify_intent`` so both quant and backtester
    reasoning nodes receive concrete availability flags instead of having to
    guess or query the DB themselves.

    Args:
        state: Current ``GraphState`` dict — must have ``symbol`` set by the
               classifier (may be ``None`` for portfolio-only queries).

    Returns:
        Partial state update with ``data_availability`` dict.
    """
    symbol: Optional[str] = state.get("symbol")
    timeframe: str = "1Min"  # Intraday standard — indicators are always 1Min

    now = datetime.now(timezone.utc)
    checked_at = now.isoformat()

    if not symbol:
        # Portfolio-only query — no symbol to check, skip all DB lookups.
        result = {
            "symbol": None,
            "timeframe": timeframe,
            "indicators_available": False,
            "bars_available": False,
            "trades_available": False,
            "indicator_rows": 0,
            "bar_count": 0,
            "trade_count": 0,
            "latest_indicator_ts": None,
            "latest_bar_ts": None,
            "checked_at": checked_at,
            "note": "No symbol resolved — portfolio query",
        }
        logger.info("[data_avail] no symbol — skipping data checks")
        return {"data_availability": result}

    logger.info(f"[data_avail] checking {symbol}/{timeframe} ...")

    ind = _check_indicators(symbol, timeframe, now)
    bars = _check_bars(symbol, timeframe, now)
    trades = _check_trades(symbol, now)

    result = {
        "symbol": symbol,
        "timeframe": timeframe,
        # ── Primary flags consumed by reasoning agents ─────────────────────
        "indicators_available": ind["available"],
        "bars_available": bars["available"],
        "trades_available": trades["available"],
        # ── Metadata (for logging / synthesizer context) ────────────────────
        "indicator_rows": ind["row_count"],
        "bar_count": bars["bar_count"],
        "trade_count": trades["trade_count"],
        "latest_indicator_ts": ind["latest_ts"],
        "latest_bar_ts": bars["latest_ts"],
        "checked_at": checked_at,
    }

    logger.info(
        f"[data_avail] {symbol}/{timeframe} — "
        f"indicators={ind['available']} ({ind['row_count']} rows)  "
        f"bars={bars['available']} ({bars['bar_count']} bars)  "
        f"trades={trades['available']} ({trades['trade_count']} trades)"
    )

    return {"data_availability": result}


if __name__ == "__main__":
    """Functional test against the live market DB."""
    import json

    print("=" * 60)
    print("data_availability_node Functional Test")
    print("=" * 60)

    # Test 1: known symbol
    print("\n[1/2] Testing with symbol=AAPL ...")
    r1 = data_availability_node({"symbol": "AAPL"})
    da = r1["data_availability"]
    print(json.dumps(da, indent=2, default=str))
    assert "indicators_available" in da
    assert "bars_available" in da
    assert "trades_available" in da
    print("[OK] All flags present")

    # Test 2: no symbol (portfolio query)
    print("\n[2/2] Testing with symbol=None ...")
    r2 = data_availability_node({"symbol": None})
    da2 = r2["data_availability"]
    assert da2["indicators_available"] is False
    assert da2["bars_available"] is False
    print("[OK] Symbol=None → all False")

    print("\n[ALL OK] data_availability_node smoke test passed")
