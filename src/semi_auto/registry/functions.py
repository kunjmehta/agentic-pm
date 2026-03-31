"""Function registry for the semi-auto executor node.

Maps string function names (as output by LLM reasoning agents) to Python callables.
Quant skill functions require a pandas DataFrame so they are wrapped to fetch bars
from AlpacaDAO internally before calling the underlying skill.

Skills are loaded through src/semi_auto/skills/ which isolates all src/agentic/
imports to a single boundary layer.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.semi_auto.models.skills import (
    BacktestInput,
    CandleInput,
    DataAvailabilityInput,
    HistoricalDataInput,
    MeanReversionInput,
    MomentumInput,
    VolatilityInput,
    VolumeInput,
    # Output models
    BacktestOutput,
    CandleOutput,
    DataAvailabilityOutput,
    FetchHistoricalDataOutput,
    HealthCheckOutput,
    MeanReversionOutput,
    MomentumOutput,
    PortfolioStatusOutput,
    PositionsSummaryOutput,
    SnapshotSaveOutput,
    SnapshotWorthOutput,
    SwapPositionsOutput,
    VolatilityOutput,
    VolumeOutput,
)

logger = get_logger(__name__)

# ── Portfolio skills ───────────────────────────────────────────────────────────

from src.semi_auto.skills.portfolio.skills import (
    portfolio_skills as _portfolio_skills,
    get_portfolio_status_core,
    get_positions_summary_core,
    check_portfolio_health_core,
    fetch_historical_data_core,
    check_data_availability_core,
)

# ── Quant skills ──────────────────────────────────────────────────────────────

from src.semi_auto.skills.quant.skills import (
    momentum_skill as _momentum_skill,
    volatility_skill as _volatility_skill,
    volume_skill as _volume_skill,
    candlestick_skill as _candlestick_skill,
    mean_reversion_skill as _mean_reversion_skill,
    # Legacy function aliases (used by _calc_*_wrapped helpers below)
    calc_momentum_package as _calc_momentum_raw,
    calc_volatility_bands as _calc_volatility_raw,
    calc_volume_flow as _calc_volume_raw,
    analyze_candle_structure as _analyze_candles_raw,
)

# ── Backtester skills ─────────────────────────────────────────────────────────

from src.semi_auto.skills.backtester.skills import (
    backtest_skill as _backtest_skill,
    snapshot_skill as _snapshot_skill,
    swap_skill as _swap_skill,
    backtest_strategy_core as _backtest_strategy_raw,
    save_eod_snapshot_core as _save_eod_snapshot_raw,
    snapshot_worth_core as _snapshot_worth_raw,
    swap_positions_core as _swap_positions_raw,
)


# ── Wrapper helpers ───────────────────────────────────────────────────────────

def _fetch_bars_for_symbol(symbol: str, timeframe: str = "1Min", lookback_days: int = 90):
    """Fetch OHLCV bars from AlpacaDAO for a symbol.

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe string e.g. "1Day", "1Min".
        lookback_days: How many calendar days to look back.

    Returns:
        pandas DataFrame or None on failure.
    """
    try:
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        df = dao.get_bars(symbol, start=start, end=end, timeframe=timeframe)
        dao.close()
        if df is None or df.empty:
            logger.warning(f"[registry] no bars found for {symbol}/{timeframe}")
            return None
        return df
    except Exception as exc:
        logger.warning(f"[registry] bar fetch failed for {symbol}: {exc}")
        return None


def _fetch_bars_range(
    skill_name: str,
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str,
):
    """Fetch bars from AlpacaDAO for an explicit date range.

    Args:
        skill_name: Caller label for logging.
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".
        timeframe: AlpacaDAO canonical timeframe string.

    Returns:
        pandas DataFrame or None on failure.
    """
    try:
        from datetime import datetime as _dt
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        df = dao.get_bars(
            symbol,
            _dt.fromisoformat(start_date),
            _dt.fromisoformat(end_date),
            timeframe,
        )
        dao.close()
        if df is None or df.empty:
            logger.warning(f"[{skill_name}] no bars for {symbol}/{timeframe} {start_date}–{end_date}")
            return None
        return df
    except Exception as exc:
        logger.warning(f"[{skill_name}] bar fetch failed for {symbol}: {exc}")
        return None


def _calc_momentum_wrapped(
    symbol: str,
    timeframe: str = "1Min",
    lookback_days: int = 90,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,  # absorb LLM-injected fields (task_id, note, etc.)
) -> Dict:
    """Compute MACD + RSI signals.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Input is validated and normalised via :class:`~src.semi_auto.models.skills.MomentumInput`
    before the skill is called (symbols are upper-cased, timeframe aliases are resolved, and
    date-pair consistency is enforced).

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe (alias-aware, e.g. "1d" → "1Day").
        lookback_days: Calendar days to look back (live mode only).
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Dict with macd, rsi, symbol, timeframe, timestamp — or error dict.
    """
    try:
        inp = MomentumInput(
            symbol=symbol, timeframe=timeframe, lookback_days=lookback_days,
            start_date=start_date, end_date=end_date,
        )
    except Exception as exc:
        logger.warning(f"[registry] MomentumInput validation failed: {exc}")
        return {"error": f"Invalid parameters for calc_momentum: {exc}"}

    if inp.is_historical:
        df = _fetch_bars_range("calc_momentum", inp.symbol, inp.start_date, inp.end_date, inp.timeframe)
        if df is None:
            return _out(MomentumOutput, {"error": f"No data for {inp.symbol}/{inp.timeframe} in range {inp.start_date}\u2013{inp.end_date}", "symbol": inp.symbol})
        result = _momentum_skill.analyze_bars(df)
        result.update({"symbol": inp.symbol, "timeframe": inp.timeframe,
                       "start_date": inp.start_date, "end_date": inp.end_date, "mode": "historical"})
        return _out(MomentumOutput, result)
    return _out(MomentumOutput, _momentum_skill.generate_signals(inp.symbol, timeframe=inp.timeframe, lookback_days=inp.lookback_days))


def _calc_volatility_wrapped(
    symbol: str,
    timeframe: str = "1Min",
    lookback_days: int = 90,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """Compute Bollinger Band signals.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Input is validated and normalised via :class:`~src.semi_auto.models.skills.VolatilityInput`.

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe.
        lookback_days: Calendar days to look back (live mode only).
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Dict with upper, middle, lower, bandwidth — or error dict.
    """
    try:
        inp = VolatilityInput(
            symbol=symbol, timeframe=timeframe, lookback_days=lookback_days,
            start_date=start_date, end_date=end_date,
        )
    except Exception as exc:
        logger.warning(f"[registry] VolatilityInput validation failed: {exc}")
        return {"error": f"Invalid parameters for calc_volatility_bands: {exc}"}

    if inp.is_historical:
        df = _fetch_bars_range("calc_volatility_bands", inp.symbol, inp.start_date, inp.end_date, inp.timeframe)
        if df is None:
            return _out(VolatilityOutput, {"error": f"No data for {inp.symbol}/{inp.timeframe} in range {inp.start_date}\u2013{inp.end_date}", "symbol": inp.symbol})
        result = _volatility_skill.analyze_bars(df)
        result.update({"symbol": inp.symbol, "timeframe": inp.timeframe,
                       "start_date": inp.start_date, "end_date": inp.end_date, "mode": "historical"})
        return _out(VolatilityOutput, result)
    return _out(VolatilityOutput, _volatility_skill.generate_signals(inp.symbol, timeframe=inp.timeframe, lookback_days=inp.lookback_days))


def _calc_volume_wrapped(
    symbol: str,
    timeframe: str = "1Min",
    lookback_days: int = 90,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """Compute OBV + volume flow signals.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Input is validated and normalised via :class:`~src.semi_auto.models.skills.VolumeInput`.

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe.
        lookback_days: Calendar days to look back (live mode only).
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Dict with obv, volume_trend, avg_volume_10d, current_vs_avg — or error dict.
    """
    try:
        inp = VolumeInput(
            symbol=symbol, timeframe=timeframe, lookback_days=lookback_days,
            start_date=start_date, end_date=end_date,
        )
    except Exception as exc:
        logger.warning(f"[registry] VolumeInput validation failed: {exc}")
        return {"error": f"Invalid parameters for calc_volume_flow: {exc}"}

    if inp.is_historical:
        df = _fetch_bars_range("calc_volume_flow", inp.symbol, inp.start_date, inp.end_date, inp.timeframe)
        if df is None:
            return _out(VolumeOutput, {"error": f"No data for {inp.symbol}/{inp.timeframe} in range {inp.start_date}\u2013{inp.end_date}", "symbol": inp.symbol})
        result = _volume_skill.analyze_bars(df)
        result.update({"symbol": inp.symbol, "timeframe": inp.timeframe,
                       "start_date": inp.start_date, "end_date": inp.end_date, "mode": "historical"})
        return _out(VolumeOutput, result)
    return _out(VolumeOutput, _volume_skill.generate_signals(inp.symbol, timeframe=inp.timeframe, lookback_days=inp.lookback_days))


def _analyze_candles_wrapped(
    symbol: str,
    timeframe: str = "1Min",
    lookback_days: int = 30,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """Detect candlestick patterns.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Input is validated and normalised via :class:`~src.semi_auto.models.skills.CandleInput`.

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe.
        lookback_days: Calendar days to look back (live mode only).
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Dict with patterns, last_candle_type, last_body_pct, pattern_count — or error dict.
    """
    try:
        inp = CandleInput(
            symbol=symbol, timeframe=timeframe, lookback_days=lookback_days,
            start_date=start_date, end_date=end_date,
        )
    except Exception as exc:
        logger.warning(f"[registry] CandleInput validation failed: {exc}")
        return {"error": f"Invalid parameters for analyze_candle_structure: {exc}"}

    if inp.is_historical:
        df = _fetch_bars_range("analyze_candle_structure", inp.symbol, inp.start_date, inp.end_date, inp.timeframe)
        if df is None:
            return _out(CandleOutput, {"error": f"No data for {inp.symbol}/{inp.timeframe} in range {inp.start_date}\u2013{inp.end_date}", "symbol": inp.symbol})
        result = _candlestick_skill.analyze_bars(df)
        result.update({"symbol": inp.symbol, "timeframe": inp.timeframe,
                       "start_date": inp.start_date, "end_date": inp.end_date, "mode": "historical"})
        return _out(CandleOutput, result)
    return _out(CandleOutput, _candlestick_skill.generate_signals(inp.symbol, timeframe=inp.timeframe, lookback_days=inp.lookback_days))


def _mean_reversion_analyze(
    symbol: str,
    lookback: int = 60,
    threshold: float = 2.0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timeframe: str = "1Min",
    **_extra,
) -> Dict:
    """Run full mean-reversion analysis — Z-score, Bollinger, signal, recommendation.

    Supports two modes:
    - **Live mode** (default): fetches recent bars from today back ``lookback`` bars.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Input is validated and normalised via :class:`~src.semi_auto.models.skills.MeanReversionInput`.

    Args:
        symbol: Stock ticker.
        lookback: Lookback period in trading days.
        threshold: Z-score threshold for entry signal.
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).
        timeframe: Bar timeframe (historical mode only; live always uses default).

    Returns:
        Full analysis dict with statistics, signals, trade_recommendation — or error dict.
    """
    try:
        inp = MeanReversionInput(
            symbol=symbol, lookback=lookback, threshold=threshold,
            start_date=start_date, end_date=end_date, timeframe=timeframe,
        )
    except Exception as exc:
        logger.warning(f"[registry] MeanReversionInput validation failed: {exc}")
        return {"error": f"Invalid parameters for mean_reversion_analyze: {exc}"}

    try:
        if inp.is_historical:
            df = _fetch_bars_range("mean_reversion_analyze", inp.symbol, inp.start_date, inp.end_date, inp.timeframe)
            if df is None:
                return _out(MeanReversionOutput, {"error": f"No data for {inp.symbol}/{inp.timeframe} in range {inp.start_date}\u2013{inp.end_date}", "symbol": inp.symbol})
            result = _mean_reversion_skill.analyze_bars(df, threshold=inp.threshold, lookback=inp.lookback)
            result.update({"symbol": inp.symbol, "start_date": inp.start_date,
                           "end_date": inp.end_date, "mode": "historical"})
            return _out(MeanReversionOutput, result)
        return _out(MeanReversionOutput, _mean_reversion_skill.generate_signals(
            symbol=inp.symbol, lookback=inp.lookback, threshold=inp.threshold
        ))
    except Exception as exc:
        logger.warning(f"[registry] mean_reversion_analyze failed for {inp.symbol}: {exc}")
        return _out(MeanReversionOutput, {"error": str(exc), "symbol": inp.symbol})


def _backtest_strategy(
    symbol: str = None,
    start_date: str = None,
    end_date: str = None,
    strategy: str = "mean-reversion",
    initial_capital: float = 100000.0,
    strategy_params: Dict = None,
    # LLM may pass these — accepted and ignored
    ticker: str = None,
    task_id: str = None,
    workflow_type: str = None,
    note: str = None,
    metrics_requested: list = None,
    **kwargs,
) -> Dict:
    """Run backtest_strategy_core for the given symbol and strategy.

    ``ticker`` is accepted as a legacy alias but ``symbol`` is the canonical param.
    Extra kwargs (task_id, workflow_type, note, metrics_requested) are silently
    absorbed — they come from LLM planning but are not used by the core skill.

    Input is validated and normalised via :class:`~src.semi_auto.models.skills.BacktestInput`
    (strategy names are lower-cased and validated, symbol is upper-cased).

    Args:
        symbol: Stock symbol (canonical param name).
        ticker: Legacy alias for symbol.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".
        strategy: One of "buy-and-hold", "mean-reversion", "momentum", "value".
        initial_capital: Starting capital in USD.
        strategy_params: Optional strategy-specific parameters dict.

    Returns:
        Backtest result dict, or error dict.
    """
    # Resolve symbol — accept either 'symbol' or legacy 'ticker'
    resolved_ticker = symbol or ticker
    if not resolved_ticker:
        return {"error": "backtest_strategy requires 'symbol'"}
    if not start_date or not end_date:
        return {"error": "backtest_strategy requires 'start_date' and 'end_date'"}

    # Resolve strategy name — normalise dict form {"name": ..., "params": ...}
    resolved_strategy = strategy
    resolved_params = strategy_params
    if isinstance(strategy, dict):
        resolved_strategy = strategy.get("name", "mean-reversion")
        if not resolved_params:
            resolved_params = strategy.get("params")

    # Validate inputs via Pydantic
    try:
        inp = BacktestInput(
            ticker=resolved_ticker,
            start_date=start_date,
            end_date=end_date,
            strategy=resolved_strategy,
            initial_capital=initial_capital,
            strategy_params=resolved_params,
        )
    except Exception as exc:
        logger.warning(f"[registry] BacktestInput validation failed: {exc}")
        return {"error": f"Invalid parameters for backtest_strategy: {exc}"}

    if _backtest_strategy_raw is None:
        return {"error": "backtest_strategy skill not available"}
    try:
        result = _backtest_strategy_raw(
            ticker=inp.ticker,
            start_date=inp.start_date,
            end_date=inp.end_date,
            strategy=inp.strategy,
            initial_capital=inp.initial_capital,
            strategy_params=inp.strategy_params,
            save_to_db=True,
        )
        return _out(BacktestOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] backtest_strategy failed for {inp.ticker}: {exc}")
        return _out(BacktestOutput, {"status": "failed", "error": str(exc),
                                     "strategy": inp.strategy, "ticker": inp.ticker,
                                     "start_date": inp.start_date, "end_date": inp.end_date})


# ── DAO wrapper helpers ───────────────────────────────────────────────────────

def _to_native(obj: Any) -> Any:
    """Recursively convert non-JSON-serialisable types to native Python equivalents.

    Handles numpy scalar types, pandas Timestamps, Decimals, and nested
    containers so that results from DAO layers can be safely JSON-serialised
    or passed as plain dicts to the executor/synthesizer.

    Args:
        obj: Any Python object — scalar, dict, list, or nested structure.

    Returns:
        Object with all non-native types replaced by their Python equivalents.
    """
    import decimal
    if obj is None:
        return None
    # numpy integer / float scalars
    try:
        import numpy as np  # only imported on demand to avoid hard dependency
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return [_to_native(v) for v in obj.tolist()]
    except ImportError:
        pass
    # pandas Timestamp
    try:
        import pandas as pd
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except ImportError:
        pass
    # Decimal
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    # datetime
    from datetime import date, datetime
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    # containers
    if isinstance(obj, dict):
        return {str(k): _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    return obj


def _df_to_records(df) -> list:
    """Convert a DataFrame to a list of native dicts. Returns [] if empty/None."""
    try:
        if df is None or (hasattr(df, "empty") and df.empty):
            return []
        return _to_native(df.to_dict("records"))
    except Exception:
        return []


def _out(model_cls, raw: Dict) -> Dict:
    """Validate a raw skill result through its Pydantic output model.

    All output models use ``extra="allow"`` so extra fields pass through
    unchanged.  On unexpected validation failure the raw dict is returned
    as-is so the executor is never blocked.

    Args:
        model_cls: A Pydantic BaseModel subclass with ``extra="allow"``.
        raw: Raw dict returned by a skill function.

    Returns:
        Validated and coerced dict (defaults filled, types coerced).
    """
    try:
        return model_cls.model_validate(raw).model_dump()
    except Exception as exc:
        logger.debug(f"[registry._out] output validation skipped ({model_cls.__name__}): {exc}")
        return raw


# ── AlpacaDAO wrappers ────────────────────────────────────────────────────────

# Timeframe aliases the LLM commonly emits → canonical values accepted by AlpacaDAO
_TIMEFRAME_ALIASES = {
    "1d": "1Day", "1day": "1Day", "day": "1Day", "daily": "1Day",
    "1h": "1Hour", "1hour": "1Hour", "hour": "1Hour", "hourly": "1Hour",
    "1m": "1Min", "1min": "1Min", "minute": "1Min",
    "5m": "5Min", "5min": "5Min",
    "15m": "15Min", "15min": "15Min",
}

_VALID_TIMEFRAMES = {"1Min", "5Min", "15Min", "1Hour", "1Day"}


def _normalize_timeframe(tf: str, default: str = "1Min") -> str:
    """Normalise LLM timeframe strings to AlpacaDAO canonical form.

    Args:
        tf: Raw timeframe string from LLM (e.g. "1d", "1Day", "daily").
        default: Returned when tf is None or unrecognised.

    Returns:
        Canonical timeframe string accepted by AlpacaDAO.
    """
    if not tf:
        return default
    canonical = _TIMEFRAME_ALIASES.get(tf.lower(), tf)
    return canonical if canonical in _VALID_TIMEFRAMES else default


def _check_data_availability_wrapped(
    symbol: str = "",
    ticker: str = "",
    start_date: str = "",
    end_date: str = "",
    timeframe: str = "1Min",
    **kwargs,
) -> Dict:
    """Wrapper that accepts both 'symbol' and 'ticker' parameter names.

    The LLM sometimes emits 'ticker' (matching backtest_strategy) for this
    function which expects 'symbol'. This wrapper normalises either form.

    Input is validated via :class:`~src.semi_auto.models.skills.DataAvailabilityInput`
    which also normalises timeframe aliases (e.g. "1d" → "1Day").

    Args:
        symbol: Stock ticker (canonical param name).
        ticker: Alias accepted for LLM compatibility — mapped to symbol.
        start_date: Start date "YYYY-MM-DD".
        end_date: End date "YYYY-MM-DD".
        timeframe: Bar timeframe (default "1Min").

    Returns:
        Result dict from check_data_availability_core, or error dict.
    """
    if check_data_availability_core is None:
        return {"error": "check_data_availability skill not available"}
    resolved_symbol = symbol or ticker
    if not resolved_symbol:
        return {"error": "check_data_availability: 'symbol' is required"}
    if ticker and not symbol:
        logger.info(f"[registry] check_data_availability: mapped 'ticker' → 'symbol' ({ticker})")
    try:
        inp = DataAvailabilityInput(
            symbol=resolved_symbol, start_date=start_date, end_date=end_date, timeframe=timeframe,
        )
    except Exception as exc:
        logger.warning(f"[registry] DataAvailabilityInput validation failed: {exc}")
        return {"error": f"Invalid parameters for check_data_availability: {exc}"}
    try:
        result = check_data_availability_core(
            symbol=inp.symbol,
            start_date=inp.start_date,
            end_date=inp.end_date,
            timeframe=inp.timeframe,
        )
        return _out(DataAvailabilityOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] check_data_availability failed for {inp.symbol}: {exc}")
        return _out(DataAvailabilityOutput, {"error": str(exc)})


def _fetch_historical_data_wrapped(
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1Min",
    **kwargs,
) -> Dict:
    """Normalising wrapper around fetch_historical_data_core.

    Input is validated via :class:`~src.semi_auto.models.skills.HistoricalDataInput`
    which converts LLM-emitted timeframe aliases (e.g. "1d") to canonical form
    and upper-cases the symbol before calling the underlying skill.

    Args:
        symbol: Stock ticker.
        start_date: Start date "YYYY-MM-DD".
        end_date: End date "YYYY-MM-DD".
        timeframe: Bar timeframe — normalised automatically.

    Returns:
        Result dict from fetch_historical_data_core, or error dict.
    """
    if fetch_historical_data_core is None:
        return {"error": "fetch_historical_data skill not available"}
    try:
        inp = HistoricalDataInput(
            symbol=symbol, start_date=start_date, end_date=end_date, timeframe=timeframe,
        )
    except Exception as exc:
        logger.warning(f"[registry] HistoricalDataInput validation failed: {exc}")
        return {"error": f"Invalid parameters for fetch_historical_data: {exc}"}
    if inp.timeframe != timeframe:
        logger.info(f"[registry] fetch_historical_data: normalised timeframe '{timeframe}' → '{inp.timeframe}'")
    try:
        result = fetch_historical_data_core(
            symbol=inp.symbol,
            start_date=inp.start_date,
            end_date=inp.end_date,
            timeframe=inp.timeframe,
        )
        return _out(FetchHistoricalDataOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] fetch_historical_data failed for {inp.symbol}: {exc}")
        return _out(FetchHistoricalDataOutput, {"error": str(exc)})


def _get_market_bars(symbol: str, start_date: str, end_date: str, timeframe: str = "1Min") -> list:
    """Fetch raw OHLCV bars from DB for a symbol and date range.

    Args:
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".
        timeframe: Bar timeframe e.g. "1Day", "1Min".

    Returns:
        List of bar dicts or empty list.
    """
    try:
        from datetime import datetime as _dt
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        df = dao.get_bars(symbol, _dt.fromisoformat(start_date), _dt.fromisoformat(end_date), timeframe)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_market_bars failed for {symbol}: {exc}")
        return {"error": str(exc)}



# ── Portfolio + Backtester thin wrappers (Pydantic-validated output) ─────────


def _get_portfolio_status_wrapped(**kwargs) -> Dict:
    """Wrap get_portfolio_status_core with PortfolioStatusOutput validation."""
    try:
        result = get_portfolio_status_core()
        return _out(PortfolioStatusOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] get_portfolio_status failed: {exc}")
        return _out(PortfolioStatusOutput, {"error": str(exc)})


def _get_positions_summary_wrapped(**kwargs) -> Dict:
    """Wrap get_positions_summary_core with PositionsSummaryOutput validation."""
    try:
        result = get_positions_summary_core()
        return _out(PositionsSummaryOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] get_positions_summary failed: {exc}")
        return _out(PositionsSummaryOutput, {"error": str(exc)})


def _check_portfolio_health_wrapped(
    portfolio_status: "Optional[Dict]" = None,
    positions_data: "Optional[Dict]" = None,
    **kwargs,
) -> Dict:
    """Wrap check_portfolio_health_core with HealthCheckOutput validation.

    Auto-fetches portfolio_status and positions_data if not provided.
    """
    try:
        if portfolio_status is None:
            portfolio_status = get_portfolio_status_core()
        if positions_data is None:
            positions_data = get_positions_summary_core()
        result = check_portfolio_health_core(
            portfolio_status=portfolio_status,
            positions_data=positions_data,
        )
        return _out(HealthCheckOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] check_portfolio_health failed: {exc}")
        return _out(HealthCheckOutput, {"error": str(exc)})


def _save_eod_snapshot_wrapped(
    timestamp: "Optional[str]" = None,
    equity: float = 0.0,
    cash: float = 0.0,
    buying_power: float = 0.0,
    positions: "Optional[list]" = None,
    daily_pnl: "Optional[float]" = None,
    total_pnl: "Optional[float]" = None,
    daily_pnl_percent: "Optional[float]" = None,
    snapshot_source: str = "manual",
    **kwargs,
) -> Dict:
    """Wrap save_eod_snapshot_core with SnapshotSaveOutput validation."""
    try:
        from datetime import datetime as _dt
        result = _save_eod_snapshot_raw(
            timestamp=timestamp or _dt.now().isoformat(),
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            positions=positions or [],
            daily_pnl=daily_pnl,
            total_pnl=total_pnl,
            daily_pnl_percent=daily_pnl_percent,
            snapshot_source=snapshot_source,
        )
        return _out(SnapshotSaveOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] save_eod_snapshot failed: {exc}")
        return _out(SnapshotSaveOutput, {"status": "error", "error": str(exc)})


def _snapshot_worth_wrapped(
    snapshot_date: "Optional[str]" = None,
    end_date: "Optional[str]" = None,
    **kwargs,
) -> Dict:
    """Wrap snapshot_worth_core with SnapshotWorthOutput validation."""
    if not snapshot_date or not end_date:
        return _out(SnapshotWorthOutput, {
            "error": "snapshot_worth requires 'snapshot_date' and 'end_date'"
        })
    try:
        result = _snapshot_worth_raw(snapshot_date=snapshot_date, end_date=end_date)
        return _out(SnapshotWorthOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] snapshot_worth failed: {exc}")
        return _out(SnapshotWorthOutput, {"error": str(exc)})


def _swap_positions_wrapped(
    snapshot_date: "Optional[str]" = None,
    end_date: "Optional[str]" = None,
    tickers: "Optional[Dict]" = None,
    **kwargs,
) -> Dict:
    """Wrap swap_positions_core with SwapPositionsOutput validation."""
    if not snapshot_date or not end_date:
        return _out(SwapPositionsOutput, {
            "error": "swap_positions requires 'snapshot_date' and 'end_date'"
        })
    if not tickers:
        return _out(SwapPositionsOutput, {"error": "swap_positions requires 'tickers' mapping"})
    try:
        result = _swap_positions_raw(
            snapshot_date=snapshot_date, end_date=end_date, tickers=tickers
        )
        return _out(SwapPositionsOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] swap_positions failed: {exc}")
        return _out(SwapPositionsOutput, {"error": str(exc)})

def _get_latest_price(symbol: str, timeframe: str = "1Min") -> dict:
    """Get the most recent bar for a symbol.

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe.

    Returns:
        Bar dict with open/high/low/close/volume or error dict.
    """
    try:
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        result = dao.get_latest_bar(symbol, timeframe)
        dao.close()
        return _to_native(result) if result else {"error": f"No bar found for {symbol}"}
    except Exception as exc:
        logger.warning(f"[registry] get_latest_price failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_precomputed_indicators(symbol: str, start_date: str, end_date: str, timeframe: str = "1Min") -> list:
    """Retrieve pre-computed technical indicators stored in DB.

    Args:
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".
        timeframe: Bar timeframe.

    Returns:
        List of indicator record dicts or empty list.
    """
    try:
        from datetime import datetime as _dt
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        df = dao.get_computed_indicators(symbol, _dt.fromisoformat(start_date), _dt.fromisoformat(end_date), timeframe)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_precomputed_indicators failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_tick_trades(symbol: str, start_date: str, end_date: str, limit: int = 1000) -> list:
    """Retrieve historical tick-level trades for a symbol.

    Args:
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".
        limit: Max number of trades to return.

    Returns:
        List of trade dicts or empty list.
    """
    try:
        from datetime import datetime as _dt
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        df = dao.get_trades(symbol, _dt.fromisoformat(start_date), _dt.fromisoformat(end_date), limit=limit)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_tick_trades failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_trade_count(symbol: str, start_date: str, end_date: str) -> dict:
    """Get count of trades for a symbol in a date range.

    Args:
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".

    Returns:
        Dict with count key.
    """
    try:
        from datetime import datetime as _dt
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        count = dao.get_trade_count(symbol, _dt.fromisoformat(start_date), _dt.fromisoformat(end_date))
        dao.close()
        return {"symbol": symbol, "start_date": start_date, "end_date": end_date, "trade_count": count}
    except Exception as exc:
        logger.warning(f"[registry] get_trade_count failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_intraday_stats(symbol: str, date: str) -> dict:
    """Calculate intraday statistics (VWAP, high/low range, trade count) for a date.

    Args:
        symbol: Stock ticker.
        date: Date string "YYYY-MM-DD".

    Returns:
        Intraday stats dict.
    """
    try:
        from datetime import date as _date
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        result = dao.calculate_intraday_stats(symbol, _date.fromisoformat(date))
        dao.close()
        return _to_native(result) if result else {"error": f"No intraday data for {symbol} on {date}"}
    except Exception as exc:
        logger.warning(f"[registry] get_intraday_stats failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_watchlist() -> list:
    """Get all symbols currently in the active watchlist.

    Returns:
        List of symbol strings.
    """
    try:
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        result = dao.get_watchlist(active_only=True)
        dao.close()
        return result or []
    except Exception as exc:
        logger.warning(f"[registry] get_watchlist failed: {exc}")
        return {"error": str(exc)}


# ── AlphaVantageDAO wrappers ──────────────────────────────────────────────────

def _get_company_fundamentals(symbol: str) -> dict:
    """Retrieve company overview: PE ratio, market cap, sector, EPS, 52-week range.

    Args:
        symbol: Stock ticker.

    Returns:
        Company overview dict or error dict.
    """
    try:
        from src.common.dao import AlphaVantageDAO
        dao = AlphaVantageDAO()
        result = dao.get_company_overview(symbol)
        dao.close()
        return _to_native(result) if result else {"error": f"No fundamentals found for {symbol}"}
    except Exception as exc:
        logger.warning(f"[registry] get_company_fundamentals failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_dividends(symbol: str, limit: int = 10) -> list:
    """Retrieve dividend history for a symbol.

    Args:
        symbol: Stock ticker.
        limit: Max number of dividend records to return.

    Returns:
        List of dividend dicts or empty list.
    """
    try:
        from src.common.dao import AlphaVantageDAO
        dao = AlphaVantageDAO()
        df = dao.get_dividends(symbol, limit=limit)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_dividends failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_earnings_history(symbol: str, quarterly: bool = True, limit: int = 4) -> list:
    """Retrieve historical earnings data (reported vs estimated EPS).

    Args:
        symbol: Stock ticker.
        quarterly: True for quarterly, False for annual.
        limit: Max number of periods.

    Returns:
        List of earnings dicts or empty list.
    """
    try:
        from src.common.dao import AlphaVantageDAO
        dao = AlphaVantageDAO()
        df = dao.get_earnings(symbol, quarterly=quarterly, limit=limit)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_earnings_history failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_income_statement(symbol: str, quarterly: bool = False, limit: int = 4) -> list:
    """Retrieve income statement data (revenue, net income, EBITDA).

    Args:
        symbol: Stock ticker.
        quarterly: True for quarterly, False for annual.
        limit: Max number of periods.

    Returns:
        List of income statement dicts or empty list.
    """
    try:
        from src.common.dao import AlphaVantageDAO
        dao = AlphaVantageDAO()
        df = dao.get_income_statement(symbol, quarterly=quarterly, limit=limit)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_income_statement failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_balance_sheet(symbol: str, quarterly: bool = False, limit: int = 4) -> list:
    """Retrieve balance sheet data (assets, liabilities, equity).

    Args:
        symbol: Stock ticker.
        quarterly: True for quarterly, False for annual.
        limit: Max number of periods.

    Returns:
        List of balance sheet dicts or empty list.
    """
    try:
        from src.common.dao import AlphaVantageDAO
        dao = AlphaVantageDAO()
        df = dao.get_balance_sheet(symbol, quarterly=quarterly, limit=limit)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_balance_sheet failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_cash_flow(symbol: str, quarterly: bool = False, limit: int = 4) -> list:
    """Retrieve cash flow statement data.

    Args:
        symbol: Stock ticker.
        quarterly: True for quarterly, False for annual.
        limit: Max number of periods.

    Returns:
        List of cash flow dicts or empty list.
    """
    try:
        from src.common.dao import AlphaVantageDAO
        dao = AlphaVantageDAO()
        df = dao.get_cash_flow(symbol, quarterly=quarterly, limit=limit)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_cash_flow failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_all_fundamentals() -> list:
    """Retrieve all company fundamentals stored in the database.

    Returns:
        List of company overview dicts for all tracked symbols.
    """
    try:
        from src.common.dao import AlphaVantageDAO
        dao = AlphaVantageDAO()
        df = dao.get_all_fundamentals()
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_all_fundamentals failed: {exc}")
        return {"error": str(exc)}


# ── AnalystDAO wrappers ───────────────────────────────────────────────────────

def _get_eod_summaries(symbol: str, start_date: str, end_date: str) -> list:
    """Get end-of-day analyst summaries for a symbol in a date range.

    Args:
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".

    Returns:
        List of EOD summary dicts or empty list.
    """
    try:
        from datetime import date as _date
        from src.common.dao import AnalystDAO
        dao = AnalystDAO()
        df = dao.get_eod_summaries(symbol, _date.fromisoformat(start_date), _date.fromisoformat(end_date))
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_eod_summaries failed for {symbol}: {exc}")
        return {"error": str(exc)}


# ── StrategyDAO wrappers ──────────────────────────────────────────────────────

def _get_recent_signals(symbol: str, strategy_name: str, limit: int = 10) -> list:
    """Get recent strategy signals for a symbol.

    Args:
        symbol: Stock ticker.
        strategy_name: Name of the strategy.
        limit: Max number of signals.

    Returns:
        List of signal dicts or empty list.
    """
    try:
        from src.common.dao import StrategyDAO
        dao = StrategyDAO()
        df = dao.get_recent_signals(symbol, strategy_name, limit=limit)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_recent_signals failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_actionable_signals(min_confidence: float = 0.7, action_filter: str = None) -> list:
    """Get high-confidence actionable buy/sell signals from active strategies.

    Args:
        min_confidence: Minimum confidence threshold (0.0-1.0).
        action_filter: Optional filter: "buy", "sell", or None for all.

    Returns:
        List of actionable signal dicts.
    """
    try:
        from src.common.dao import StrategyDAO
        dao = StrategyDAO()
        df = dao.get_actionable_signals(min_confidence=min_confidence, action_filter=action_filter)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_actionable_signals failed: {exc}")
        return {"error": str(exc)}


def _get_strategy_performance(strategy_name: str, days: int = 30) -> dict:
    """Get aggregate performance statistics for a strategy over recent days.

    Args:
        strategy_name: Name of the strategy.
        days: Lookback period in days.

    Returns:
        Performance stats dict (win rate, avg return, signal count, etc.).
    """
    try:
        from src.common.dao import StrategyDAO
        dao = StrategyDAO()
        result = dao.get_strategy_performance(strategy_name, days=days)
        dao.close()
        return _to_native(result) if result else {"error": f"No performance data for {strategy_name}"}
    except Exception as exc:
        logger.warning(f"[registry] get_strategy_performance failed for {strategy_name}: {exc}")
        return {"error": str(exc)}


# ── BacktestDAO wrappers ──────────────────────────────────────────────────────

def _get_backtest_run(run_id: str) -> dict:
    """Get details of a specific backtest run.

    Args:
        run_id: Backtest run UUID.

    Returns:
        Run details dict or error dict.
    """
    try:
        from src.common.dao import BacktestDAO
        dao = BacktestDAO()
        result = dao.get_run(run_id)
        dao.close()
        return _to_native(result) if result else {"error": f"No backtest run found: {run_id}"}
    except Exception as exc:
        logger.warning(f"[registry] get_backtest_run failed for {run_id}: {exc}")
        return {"error": str(exc)}


def _get_recent_backtest_runs(strategy_name: str = None, limit: int = 10) -> list:
    """Get recent backtest runs, optionally filtered by strategy.

    Args:
        strategy_name: Optional strategy name filter.
        limit: Max number of runs to return.

    Returns:
        List of backtest run summary dicts.
    """
    try:
        from src.common.dao import BacktestDAO
        dao = BacktestDAO()
        result = dao.get_recent_runs(strategy_name=strategy_name, limit=limit)
        dao.close()
        return _to_native(result) if result else []
    except Exception as exc:
        logger.warning(f"[registry] get_recent_backtest_runs failed: {exc}")
        return {"error": str(exc)}


def _get_backtest_trades(run_id: str) -> list:
    """Get all trades executed in a specific backtest run.

    Args:
        run_id: Backtest run UUID.

    Returns:
        List of trade dicts or empty list.
    """
    try:
        from src.common.dao import BacktestDAO
        dao = BacktestDAO()
        df = dao.get_trades_for_run(run_id)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_backtest_trades failed for {run_id}: {exc}")
        return {"error": str(exc)}


def _get_backtest_performance(run_id: str) -> list:
    """Get daily performance history for a backtest run.

    Args:
        run_id: Backtest run UUID.

    Returns:
        List of daily performance dicts (date, equity, returns, etc.).
    """
    try:
        from src.common.dao import BacktestDAO
        dao = BacktestDAO()
        df = dao.get_performance_history(run_id)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_backtest_performance failed for {run_id}: {exc}")
        return {"error": str(exc)}


# ── PortfolioDAO wrappers ─────────────────────────────────────────────────────

def _get_portfolio_snapshot_history(start_date: str, end_date: str) -> list:
    """Get historical portfolio snapshots for a date range.

    Args:
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".

    Returns:
        List of snapshot dicts or empty list.
    """
    try:
        from datetime import date as _date
        from src.common.dao import PortfolioDAO
        dao = PortfolioDAO()
        df = dao.get_snapshot_history(_date.fromisoformat(start_date), _date.fromisoformat(end_date))
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_portfolio_snapshot_history failed: {exc}")
        return {"error": str(exc)}


def _get_risk_parameters() -> dict:
    """Get current portfolio risk parameters and thresholds.

    Returns:
        Dict of risk parameter names to values.
    """
    try:
        from src.common.dao import PortfolioDAO
        dao = PortfolioDAO()
        result = dao.get_risk_parameters()
        dao.close()
        return _to_native(result) if result else {}
    except Exception as exc:
        logger.warning(f"[registry] get_risk_parameters failed: {exc}")
        return {"error": str(exc)}


# ── Registry ─────────────────────────────────────────────────────────────────

FUNCTION_REGISTRY: Dict[str, Optional[Callable]] = {
    # ── Portfolio core ────────────────────────────────────────────────────────
    "get_portfolio_status":    _get_portfolio_status_wrapped,
    "get_positions_summary":   _get_positions_summary_wrapped,
    "check_portfolio_health":  _check_portfolio_health_wrapped,
    "fetch_historical_data":   _fetch_historical_data_wrapped,
    "check_data_availability": _check_data_availability_wrapped,
    # ── Quant indicators (wrapped to fetch bars internally) ───────────────────
    "calc_momentum":           _calc_momentum_wrapped,
    "calc_volatility_bands":   _calc_volatility_wrapped,
    "calc_volume_flow":        _calc_volume_wrapped,
    "analyze_candle_structure": _analyze_candles_wrapped,
    "mean_reversion_analyze":  _mean_reversion_analyze,
    # ── Backtester core ───────────────────────────────────────────────────────
    "backtest_strategy":       _backtest_strategy,
    # ── AlpacaDAO market data ─────────────────────────────────────────────────
    "get_market_bars":         _get_market_bars,
    "get_latest_price":        _get_latest_price,
    "get_precomputed_indicators": _get_precomputed_indicators,
    "get_tick_trades":         _get_tick_trades,
    "get_trade_count":         _get_trade_count,
    "get_intraday_stats":      _get_intraday_stats,
    "get_watchlist":           _get_watchlist,
    # ── AlphaVantageDAO fundamentals ──────────────────────────────────────────
    "get_company_fundamentals": _get_company_fundamentals,
    "get_dividends":           _get_dividends,
    "get_earnings_history":    _get_earnings_history,
    "get_income_statement":    _get_income_statement,
    "get_balance_sheet":       _get_balance_sheet,
    "get_cash_flow":           _get_cash_flow,
    "get_all_fundamentals":    _get_all_fundamentals,
    # ── AnalystDAO ────────────────────────────────────────────────────────────
    "get_eod_summaries":       _get_eod_summaries,
    # ── StrategyDAO ───────────────────────────────────────────────────────────
    "get_recent_signals":      _get_recent_signals,
    "get_actionable_signals":  _get_actionable_signals,
    "get_strategy_performance": _get_strategy_performance,
    # ── BacktestDAO ───────────────────────────────────────────────────────────
    "get_backtest_run":        _get_backtest_run,
    "get_recent_backtest_runs": _get_recent_backtest_runs,
    "get_backtest_trades":     _get_backtest_trades,
    "get_backtest_performance": _get_backtest_performance,
    # ── PortfolioDAO ──────────────────────────────────────────────────────────
    "get_portfolio_snapshot_history": _get_portfolio_snapshot_history,
    "get_risk_parameters":     _get_risk_parameters,
    # ── Backtester workflow B & C ─────────────────────────────────────────────
    "save_eod_snapshot":       _save_eod_snapshot_wrapped,
    "snapshot_worth":          _snapshot_worth_wrapped,
    "swap_positions":          _swap_positions_wrapped,
}

# Filter out None entries at load time so executor can detect unavailable fns
AVAILABLE_FUNCTIONS = {k: v for k, v in FUNCTION_REGISTRY.items() if v is not None}


def get_registry_schema() -> Dict[str, Any]:
    """Return a schema-like dict describing all registered functions.

    Used by GET /v1/registry API endpoint.

    Returns:
        Dict mapping function_name to parameter documentation.
    """
    return {
        "get_portfolio_status": {
            "description": "Fetch current portfolio equity, cash, and position counts.",
            "params": {},
        },
        "get_positions_summary": {
            "description": "Fetch all open positions with unrealized P&L.",
            "params": {},
        },
        "check_portfolio_health": {
            "description": "Validate portfolio against risk parameters.",
            "params": {
                "portfolio_status": "dict — injected from get_portfolio_status result",
                "positions_data": "dict — injected from get_positions_summary result",
            },
            "note": "depends_on: ['pm_001', 'pm_002'] — injected automatically by executor",
        },
        "fetch_historical_data": {
            "description": "Fetch and store historical OHLCV bars from Alpaca.",
            "params": {
                "symbol": "str — stock ticker",
                "start_date": "str — YYYY-MM-DD",
                "end_date": "str — YYYY-MM-DD",
                "timeframe": "str — '1Min' | '5Min' | '1Hour' | '1Day' (default '1Min')",
            },
        },
        "check_data_availability": {
            "description": "Check if historical bars exist in DB for the given period.",
            "params": {
                "symbol": "str",
                "start_date": "str — YYYY-MM-DD",
                "end_date": "str — YYYY-MM-DD",
            },
        },
        "calc_momentum": {
            "description": "Compute MACD and RSI momentum indicators.",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Min'",
                "lookback_days": "int — default 90",
            },
        },
        "calc_volatility_bands": {
            "description": "Compute Bollinger Bands (upper, middle, lower, bandwidth).",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Min'",
                "lookback_days": "int — default 90",
            },
        },
        "calc_volume_flow": {
            "description": "Compute OBV and volume trend indicators.",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Min'",
                "lookback_days": "int — default 90",
            },
        },
        "analyze_candle_structure": {
            "description": "Detect candlestick patterns (engulfing, doji, hammer, etc.).",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Min'",
                "lookback_days": "int — default 30",
            },
        },
        "mean_reversion_analyze": {
            "description": "Run full mean-reversion analysis including z-score and signals.",
            "params": {
                "symbol": "str",
                "lookback": "int — default 60",
                "threshold": "float — default 2.0",
            },
        },
        "backtest_strategy": {
            "description": "Backtest a trading strategy on historical data.",
            "params": {
                "ticker": "str",
                "start_date": "str — YYYY-MM-DD",
                "end_date": "str — YYYY-MM-DD",
                "strategy": "str — 'buy-and-hold' | 'mean-reversion' | 'momentum' | 'value'",
                "initial_capital": "float — default 100000.0",
            },
        },
        # ── AlpacaDAO ─────────────────────────────────────────────────────────
        "get_market_bars": {
            "description": "Fetch raw OHLCV bars from DB for a symbol and date range.",
            "params": {"symbol": "str", "start_date": "str — YYYY-MM-DD", "end_date": "str — YYYY-MM-DD", "timeframe": "str — default '1Min'"},
        },
        "get_latest_price": {
            "description": "Get the most recent bar for a symbol (open/high/low/close/volume).",
            "params": {"symbol": "str", "timeframe": "str — default '1Min'"},
        },
        "get_precomputed_indicators": {
            "description": "Retrieve pre-computed technical indicators stored in DB.",
            "params": {"symbol": "str", "start_date": "str — YYYY-MM-DD", "end_date": "str — YYYY-MM-DD", "timeframe": "str — default '1Min'"},
        },
        "get_tick_trades": {
            "description": "Retrieve historical tick-level trades for a symbol.",
            "params": {"symbol": "str", "start_date": "str — YYYY-MM-DD", "end_date": "str — YYYY-MM-DD", "limit": "int — default 1000"},
        },
        "get_trade_count": {
            "description": "Get the count of trades for a symbol in a date range.",
            "params": {"symbol": "str", "start_date": "str — YYYY-MM-DD", "end_date": "str — YYYY-MM-DD"},
        },
        "get_intraday_stats": {
            "description": "Calculate intraday stats (VWAP, high/low range, trade count) for a date.",
            "params": {"symbol": "str", "date": "str — YYYY-MM-DD"},
        },
        "get_watchlist": {
            "description": "Get all symbols currently in the active watchlist.",
            "params": {},
        },
        # ── AlphaVantageDAO ───────────────────────────────────────────────────
        "get_company_fundamentals": {
            "description": "Retrieve company overview: PE ratio, market cap, sector, EPS, 52-week range.",
            "params": {"symbol": "str"},
        },
        "get_dividends": {
            "description": "Retrieve dividend history for a symbol.",
            "params": {"symbol": "str", "limit": "int — default 10"},
        },
        "get_earnings_history": {
            "description": "Retrieve historical earnings (reported vs estimated EPS, surprise %).",
            "params": {"symbol": "str", "quarterly": "bool — default True", "limit": "int — default 4"},
        },
        "get_income_statement": {
            "description": "Retrieve income statement data (revenue, net income, EBITDA).",
            "params": {"symbol": "str", "quarterly": "bool — default False", "limit": "int — default 4"},
        },
        "get_balance_sheet": {
            "description": "Retrieve balance sheet data (assets, liabilities, equity).",
            "params": {"symbol": "str", "quarterly": "bool — default False", "limit": "int — default 4"},
        },
        "get_cash_flow": {
            "description": "Retrieve cash flow statement data.",
            "params": {"symbol": "str", "quarterly": "bool — default False", "limit": "int — default 4"},
        },
        "get_all_fundamentals": {
            "description": "Retrieve all company fundamentals stored in DB for all tracked symbols.",
            "params": {},
        },
        # ── AnalystDAO ────────────────────────────────────────────────────────
        "get_eod_summaries": {
            "description": "Get end-of-day analyst summaries for a symbol in a date range.",
            "params": {"symbol": "str", "start_date": "str — YYYY-MM-DD", "end_date": "str — YYYY-MM-DD"},
        },
        # ── StrategyDAO ───────────────────────────────────────────────────────
        "get_recent_signals": {
            "description": "Get recent strategy signals for a symbol.",
            "params": {"symbol": "str", "strategy_name": "str", "limit": "int — default 10"},
        },
        "get_actionable_signals": {
            "description": "Get high-confidence actionable buy/sell signals from active strategies.",
            "params": {"min_confidence": "float — default 0.7", "action_filter": "str — 'buy'|'sell'|None"},
        },
        "get_strategy_performance": {
            "description": "Get aggregate performance statistics for a strategy over recent days.",
            "params": {"strategy_name": "str", "days": "int — default 30"},
        },
        # ── BacktestDAO ───────────────────────────────────────────────────────
        "get_backtest_run": {
            "description": "Get details of a specific completed backtest run.",
            "params": {"run_id": "str — backtest run UUID"},
        },
        "get_recent_backtest_runs": {
            "description": "List recent backtest runs, optionally filtered by strategy.",
            "params": {"strategy_name": "str — optional filter", "limit": "int — default 10"},
        },
        "get_backtest_trades": {
            "description": "Get all trades executed in a specific backtest run.",
            "params": {"run_id": "str"},
        },
        "get_backtest_performance": {
            "description": "Get daily performance history (equity curve) for a backtest run.",
            "params": {"run_id": "str"},
        },
        # ── PortfolioDAO ──────────────────────────────────────────────────────
        "get_portfolio_snapshot_history": {
            "description": "Get historical portfolio value snapshots for a date range.",
            "params": {"start_date": "str — YYYY-MM-DD", "end_date": "str — YYYY-MM-DD"},
        },
        "get_risk_parameters": {
            "description": "Get current portfolio risk parameters and thresholds.",
            "params": {},
        },
        "save_eod_snapshot": {
            "description": "Save an end-of-day portfolio snapshot with position details.",
            "params": {
                "timestamp": "str — ISO or YYYY-MM-DD HH:MM:SS",
                "equity": "float",
                "cash": "float",
                "buying_power": "float",
                "positions": "list[dict]",
                "daily_pnl": "float — optional",
                "snapshot_source": "str — default 'manual'",
            },
        },
        "snapshot_worth": {
            "description": "Calculate what the current portfolio would be worth at a future date (workflow B — no swaps).",
            "params": {
                "snapshot_date": "str — YYYY-MM-DD",
                "end_date": "str — YYYY-MM-DD",
            },
        },
        "swap_positions": {
            "description": "Simulate swapping portfolio positions and calculate resulting worth (workflow C).",
            "params": {
                "snapshot_date": "str — YYYY-MM-DD",
                "end_date": "str — YYYY-MM-DD",
                "tickers": "dict — {symbol: {swap_to: str, quantity: int}}",
            },
        },
    }


if __name__ == "__main__":
    """Smoke test: verify all registry imports and report availability."""
    print("=" * 60)
    print("registry/functions.py Smoke Tests")
    print("=" * 60)

    print(f"\nTotal registered functions: {len(FUNCTION_REGISTRY)}")
    print(f"Available (non-None):       {len(AVAILABLE_FUNCTIONS)}")

    for name, fn in FUNCTION_REGISTRY.items():
        status = "[OK]" if fn is not None else "[WARN] not available"
        print(f"  {status}  {name}")

    assert len(FUNCTION_REGISTRY) == 38, f"Expected 38 functions, got {len(FUNCTION_REGISTRY)}"  # noqa: E501
    print("\n[OK] All 38 functions registered")

    schema = get_registry_schema()
    assert len(schema) == 38, f"Expected 38 schema entries, got {len(schema)}"
    print("[OK] Registry schema returned")

    print("\n[ALL OK] registry/functions.py smoke test passed")
