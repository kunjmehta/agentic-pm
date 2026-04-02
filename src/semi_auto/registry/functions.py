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
from src.semi_auto.models.strategies import (
    BacktestInput,
    CandleInput,
    DataAvailabilityInput,
    MeanReversionInput,
    MomentumInput,
    VolatilityInput,
    VolumeInput,
    # Output models
    BacktestOutput,
    CandleOutput,
    DataAvailabilityOutput,
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
    check_data_availability_core,
    # Order execution (new)
    execute_order_core,
    close_position_core,
    scale_position_core,
    execute_strategy_signal_core,
)

# ── Quant skills ──────────────────────────────────────────────────────────────

from src.semi_auto.skills.quant.skills import (
    momentum_skill as _momentum_skill,
    volatility_skill as _volatility_skill,
    volume_skill as _volume_skill,
    candlestick_skill as _candlestick_skill,
    mean_reversion_skill as _mean_reversion_skill,
    # Strategy singletons (day-trading)
    vwap_reversion_skill as _vwap_reversion_skill,
    opening_range_breakout_skill as _opening_range_breakout_skill,
    rsi_divergence_scalp_skill as _rsi_divergence_scalp_skill,
    momentum_burst_skill as _momentum_burst_skill,
    # Strategy singletons (swing / multi-day)
    golden_cross_skill as _golden_cross_skill,
    breakout_52w_skill as _breakout_52w_skill,
    mean_reversion_daily_skill as _mean_reversion_daily_skill,
    earnings_drift_skill as _earnings_drift_skill,
    # Legacy function aliases (used by _calc_*_wrapped helpers below)
    calc_momentum_package as _calc_momentum_raw,
    calc_volatility_bands as _calc_volatility_raw,
    calc_volume_flow as _calc_volume_raw,
    analyze_candle_structure as _analyze_candles_raw,
)

# ── Backtester skills ─────────────────────────────────────────────────────────

from src.semi_auto.skills.backtester.backtest_strategy import (
    backtest_skill as _backtest_skill,
    backtest_strategy_core as _backtest_strategy_raw,
)
from src.semi_auto.skills.backtester.snapshot import (
    snapshot_skill as _snapshot_skill,
    save_eod_snapshot_core as _save_eod_snapshot_raw,
    snapshot_worth_core as _snapshot_worth_raw,
)
from src.semi_auto.skills.backtester.swap_positions import (
    swap_skill as _swap_skill,
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

def _save_mean_reversion_signal(symbol: str, timeframe: str, result: Dict) -> None:
    """Persist a mean-reversion analysis result to StrategyDAO.

    Called after both live and historical ``_mean_reversion_analyze`` runs so that
    user-directed signals appear alongside automated pipeline signals in the
    ``strategy_results`` table (distinguishable via ``model_used="user-directed"``).

    Args:
        symbol: Ticker (already upper-cased by MeanReversionInput).
        timeframe: Bar timeframe used for the analysis.
        result: Full analysis dict as returned by ``MeanReversionSkill``.
    """
    try:
        from src.common.dao.strategy_dao import StrategyDAO
        rec = result.get("trade_recommendation", {})
        signals = result.get("signals", {})
        s_dao = StrategyDAO()
        s_dao.save_strategy_result(
            symbol=symbol,
            strategy_name="mean-reversion",
            current_price=result.get("current_price", 0.0),
            statistics=result.get("statistics", {}),
            indicators={
                "moving_averages": result.get("moving_averages", {}),
                "levels": result.get("levels", {}),
            },
            signals=signals,
            action=rec.get("action", "hold"),
            confidence=float(rec.get("confidence", 0.0)),
            reason=rec.get("reason", ""),
            entry_price=rec.get("entry_price"),
            stop_loss=rec.get("stop_loss"),
            take_profit=rec.get("take_profit"),
            support_level=result.get("levels", {}).get("support"),
            resistance_level=result.get("levels", {}).get("resistance"),
            current_state=signals.get("current_state"),
            parameters=result.get("parameters", {}),
            timeframe=timeframe,
            model_used="user-directed",
        )
        # ------------------------------------------------------------------
        # Phase 25 — HITL gate: mark signal as pending_review when enabled
        # ------------------------------------------------------------------
        from src.common.utils import config as _cfg
        if _cfg.get("strategy.hitl.enabled", False):
            try:
                s_dao2 = StrategyDAO()
                s_dao2.execute(
                    """
                    UPDATE strategy_results
                       SET status = 'pending_review'
                     WHERE id = (
                           SELECT id FROM strategy_results
                            WHERE symbol = ? AND strategy_name = 'mean-reversion'
                            ORDER BY created_at DESC
                            LIMIT 1
                     )
                    """,
                    (symbol,),
                )
                s_dao2.close()
                logger.info(f"[registry] Signal for {symbol} marked 'pending_review' (HITL enabled)")
            except Exception as _hitl_exc:
                logger.warning(f"[registry] HITL status update failed for {symbol}: {_hitl_exc}")
        else:
            # Close the original dao only after potential HITL path (already closed above)
            pass
        s_dao.close()
        logger.info(
            f"[registry] Persisted user-directed signal for {symbol}/{timeframe}: "
            f"action={rec.get('action','hold')}  confidence={rec.get('confidence',0.0):.2f}"
        )
    except Exception as exc:
        logger.warning(f"[registry] StrategyDAO persist failed for {symbol}: {exc}")


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

    Results are persisted to ``strategy_results`` (``model_used="user-directed"``)
    so user-directed signals are queryable alongside automated pipeline signals.

    Input is validated and normalised via :class:`~src.semi_auto.models.skills.MeanReversionInput`.

    Args:
        symbol: Stock ticker.
        lookback: Lookback period in trading bars.
        threshold: Z-score threshold for entry signal.
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).
        timeframe: Bar timeframe. Defaults to ``"1Min"`` for intraday analysis.

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
            result = _mean_reversion_skill.analyze_bars(
                df, threshold=inp.threshold, lookback=inp.lookback, sr_lookback=inp.sr_lookback,
            )
            result.update({"symbol": inp.symbol, "start_date": inp.start_date,
                           "end_date": inp.end_date, "mode": "historical"})
        else:
            result = _mean_reversion_skill.generate_signals(
                symbol=inp.symbol, lookback=inp.lookback, threshold=inp.threshold,
                timeframe=inp.timeframe, sr_lookback=inp.sr_lookback,
            )

        # Persist to StrategyDAO (non-blocking — failures only warn)
        if "error" not in result:
            _save_mean_reversion_signal(inp.symbol, inp.timeframe, result)

        return _out(MeanReversionOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] mean_reversion_analyze failed for {inp.symbol}: {exc}")
        return _out(MeanReversionOutput, {"error": str(exc), "symbol": inp.symbol})


# ── Day-trading strategy wrappers ─────────────────────────────────────────────


def _vwap_reversion_wrapped(
    symbol: str,
    timeframe: str = "1Min",
    lookback_days: int = 5,
    dev_pct: float = 0.005,
    vol_mult: float = 2.0,
    stop_pct: float = 0.003,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """VWAP intraday reversion — detect deviation from VWAP and fade back.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Args:
        symbol: Stock ticker.
        timeframe: Bar resolution. Default ``"1Min"``.
        lookback_days: Calendar days to fetch (live mode only). Default 5.
        dev_pct: VWAP deviation threshold (fraction). Default 0.005 (0.5%).
        vol_mult: Volume spike multiplier. Default 2.0×.
        stop_pct: Stop-loss distance from entry (fraction). Default 0.3%.
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Signal dict with action, confidence, entry_price, stop_loss, take_profit — or error dict.
    """
    symbol = symbol.upper().strip()
    try:
        if start_date and end_date:
            df = _fetch_bars_range("vwap_reversion_analyze", symbol, start_date, end_date, timeframe)
            if df is None:
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}\u2013{end_date}"}
            result = _vwap_reversion_skill.analyze_bars(df, dev_pct=dev_pct, vol_mult=vol_mult, stop_pct=stop_pct)
            result.update({"symbol": symbol, "timeframe": timeframe,
                           "start_date": start_date, "end_date": end_date, "mode": "historical"})
        else:
            result = _vwap_reversion_skill.generate_signals(
                symbol=symbol, timeframe=timeframe, lookback_days=lookback_days,
                dev_pct=dev_pct, vol_mult=vol_mult, stop_pct=stop_pct,
            )
        return _to_native(result)
    except Exception as exc:
        logger.warning(f"[registry] vwap_reversion_analyze failed for {symbol}: {exc}")
        return {"error": str(exc), "symbol": symbol}


def _opening_range_breakout_wrapped(
    symbol: str,
    timeframe: str = "1Min",
    lookback_days: int = 2,
    range_bars: int = 15,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """Opening range breakout — trade breakouts beyond the first ``range_bars`` candles.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Args:
        symbol: Stock ticker.
        timeframe: Bar resolution. Default ``"1Min"``.
        lookback_days: Calendar days to fetch (live mode only). Default 2.
        range_bars: Number of opening bars that define the range. Default 15.
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Signal dict with action, confidence, breakout_side, stop_loss, take_profit — or error dict.
    """
    symbol = symbol.upper().strip()
    try:
        if start_date and end_date:
            df = _fetch_bars_range("opening_range_breakout_analyze", symbol, start_date, end_date, timeframe)
            if df is None:
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}\u2013{end_date}"}
            result = _opening_range_breakout_skill.analyze_bars(df, range_bars=range_bars)
            result.update({"symbol": symbol, "timeframe": timeframe,
                           "start_date": start_date, "end_date": end_date, "mode": "historical"})
        else:
            result = _opening_range_breakout_skill.generate_signals(
                symbol=symbol, timeframe=timeframe, lookback_days=lookback_days, range_bars=range_bars,
            )
        return _to_native(result)
    except Exception as exc:
        logger.warning(f"[registry] opening_range_breakout_analyze failed for {symbol}: {exc}")
        return {"error": str(exc), "symbol": symbol}


def _rsi_divergence_wrapped(
    symbol: str,
    timeframe: str = "1Min",
    lookback_days: int = 5,
    lookback: int = 20,
    oversold: float = 35.0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """RSI divergence scalp — detect bullish/bearish RSI divergence for scalp entries.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Args:
        symbol: Stock ticker.
        timeframe: Bar resolution. Default ``"1Min"``.
        lookback_days: Calendar days to fetch (live mode only). Default 5.
        lookback: Number of bars to scan for divergence. Default 20.
        oversold: RSI oversold threshold. Default 35.0.
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Signal dict with action, confidence, current_rsi, divergence_type — or error dict.
    """
    symbol = symbol.upper().strip()
    try:
        if start_date and end_date:
            df = _fetch_bars_range("rsi_divergence_analyze", symbol, start_date, end_date, timeframe)
            if df is None:
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}\u2013{end_date}"}
            result = _rsi_divergence_scalp_skill.analyze_bars(df, lookback=lookback, oversold=oversold)
            result.update({"symbol": symbol, "timeframe": timeframe,
                           "start_date": start_date, "end_date": end_date, "mode": "historical"})
        else:
            result = _rsi_divergence_scalp_skill.generate_signals(
                symbol=symbol, timeframe=timeframe, lookback_days=lookback_days,
                lookback=lookback, oversold=oversold,
            )
        return _to_native(result)
    except Exception as exc:
        logger.warning(f"[registry] rsi_divergence_analyze failed for {symbol}: {exc}")
        return {"error": str(exc), "symbol": symbol}


def _momentum_burst_wrapped(
    symbol: str,
    timeframe: str = "1Min",
    lookback_days: int = 3,
    vol_mult: float = 3.0,
    min_move: float = 0.005,
    trail_pct: float = 0.002,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """Momentum burst — detect explosive volume+price bars for momentum entries.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Args:
        symbol: Stock ticker.
        timeframe: Bar resolution. Default ``"1Min"``.
        lookback_days: Calendar days to fetch (live mode only). Default 3.
        vol_mult: Volume spike multiplier. Default 3.0×.
        min_move: Minimum bar price move (fraction). Default 0.5%.
        trail_pct: Trailing stop distance (fraction). Default 0.2%.
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Signal dict with action, confidence, bar_return_pct, volume_ratio — or error dict.
    """
    symbol = symbol.upper().strip()
    try:
        if start_date and end_date:
            df = _fetch_bars_range("momentum_burst_analyze", symbol, start_date, end_date, timeframe)
            if df is None:
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}\u2013{end_date}"}
            result = _momentum_burst_skill.analyze_bars(df, vol_mult=vol_mult, min_move=min_move, trail_pct=trail_pct)
            result.update({"symbol": symbol, "timeframe": timeframe,
                           "start_date": start_date, "end_date": end_date, "mode": "historical"})
        else:
            result = _momentum_burst_skill.generate_signals(
                symbol=symbol, timeframe=timeframe, lookback_days=lookback_days,
                vol_mult=vol_mult, min_move=min_move, trail_pct=trail_pct,
            )
        return _to_native(result)
    except Exception as exc:
        logger.warning(f"[registry] momentum_burst_analyze failed for {symbol}: {exc}")
        return {"error": str(exc), "symbol": symbol}


# ── Swing / multi-day strategy wrappers ───────────────────────────────────────


def _golden_cross_wrapped(
    symbol: str,
    timeframe: str = "1Day",
    lookback_days: int = 365,
    fast: int = 50,
    slow: int = 200,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """Golden / death cross — SMA-50 vs SMA-200 crossover signal on daily bars.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Args:
        symbol: Stock ticker.
        timeframe: Bar resolution. Default ``"1Day"``.
        lookback_days: Calendar days to fetch (live mode only). Default 365.
        fast: Fast SMA period. Default 50.
        slow: Slow SMA period. Default 200.
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Signal dict with action, confidence, sma_fast, sma_slow, cross_type — or error dict.
    """
    symbol = symbol.upper().strip()
    try:
        if start_date and end_date:
            df = _fetch_bars_range("golden_cross_analyze", symbol, start_date, end_date, timeframe)
            if df is None:
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}\u2013{end_date}"}
            result = _golden_cross_skill.analyze_bars(df, fast=fast, slow=slow)
            result.update({"symbol": symbol, "timeframe": timeframe,
                           "start_date": start_date, "end_date": end_date, "mode": "historical"})
        else:
            result = _golden_cross_skill.generate_signals(
                symbol=symbol, timeframe=timeframe, lookback_days=lookback_days, fast=fast, slow=slow,
            )
        return _to_native(result)
    except Exception as exc:
        logger.warning(f"[registry] golden_cross_analyze failed for {symbol}: {exc}")
        return {"error": str(exc), "symbol": symbol}


def _breakout_52w_wrapped(
    symbol: str,
    timeframe: str = "1Day",
    lookback_days: int = 400,
    lookback: int = 252,
    vol_mult: float = 1.5,
    trail_pct: float = 0.10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """52-week breakout — new annual high with volume confirmation.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Args:
        symbol: Stock ticker.
        timeframe: Bar resolution. Default ``"1Day"``.
        lookback_days: Calendar days to fetch (live mode only). Default 400.
        lookback: Prior-high scan window in bars. Default 252.
        vol_mult: Volume multiplier for confirmation. Default 1.5×.
        trail_pct: Trailing stop distance (fraction). Default 10%.
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Signal dict with action, confidence, high_52w, current_price, volume_ratio — or error dict.
    """
    symbol = symbol.upper().strip()
    try:
        if start_date and end_date:
            df = _fetch_bars_range("breakout_52w_analyze", symbol, start_date, end_date, timeframe)
            if df is None:
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}\u2013{end_date}"}
            result = _breakout_52w_skill.analyze_bars(df, lookback=lookback, vol_mult=vol_mult, trail_pct=trail_pct)
            result.update({"symbol": symbol, "timeframe": timeframe,
                           "start_date": start_date, "end_date": end_date, "mode": "historical"})
        else:
            result = _breakout_52w_skill.generate_signals(
                symbol=symbol, timeframe=timeframe, lookback_days=lookback_days,
                lookback=lookback, vol_mult=vol_mult, trail_pct=trail_pct,
            )
        return _to_native(result)
    except Exception as exc:
        logger.warning(f"[registry] breakout_52w_analyze failed for {symbol}: {exc}")
        return {"error": str(exc), "symbol": symbol}


def _mean_reversion_daily_wrapped(
    symbol: str,
    timeframe: str = "1Day",
    lookback_days: int = 90,
    lookback: int = 20,
    threshold: float = 2.5,
    ma_period: int = 20,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """Daily mean reversion — Z-score + Bollinger analysis on daily bars.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Args:
        symbol: Stock ticker.
        timeframe: Bar resolution. Default ``"1Day"``.
        lookback_days: Calendar days to fetch (live mode only). Default 90.
        lookback: Daily bars for statistics window. Default 20.
        threshold: Z-score entry threshold. Default 2.5.
        ma_period: Moving average period. Default 20.
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Full analysis dict with statistics, signals, trade_recommendation — or error dict.
    """
    symbol = symbol.upper().strip()
    try:
        if start_date and end_date:
            df = _fetch_bars_range("mean_reversion_daily_analyze", symbol, start_date, end_date, timeframe)
            if df is None:
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}\u2013{end_date}"}
            result = _mean_reversion_daily_skill.analyze_bars(
                df, lookback=lookback, threshold=threshold, ma_period=ma_period,
            )
            result.update({"symbol": symbol, "timeframe": timeframe,
                           "start_date": start_date, "end_date": end_date, "mode": "historical"})
        else:
            result = _mean_reversion_daily_skill.generate_signals(
                symbol=symbol, lookback=lookback, threshold=threshold,
                ma_period=ma_period, timeframe=timeframe,
            )
        return _to_native(result)
    except Exception as exc:
        logger.warning(f"[registry] mean_reversion_daily_analyze failed for {symbol}: {exc}")
        return {"error": str(exc), "symbol": symbol}


def _earnings_drift_wrapped(
    symbol: str,
    timeframe: str = "1Day",
    lookback_days: int = 60,
    lookback: int = 10,
    min_move: float = 0.04,
    vol_mult: float = 2.0,
    hold_days: int = 5,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """Earnings drift — ride post-earnings momentum for ``hold_days`` sessions.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

    Args:
        symbol: Stock ticker.
        timeframe: Bar resolution. Default ``"1Day"``.
        lookback_days: Calendar days to fetch (live mode only). Default 60.
        lookback: Catalyst scan window in bars. Default 10.
        min_move: Minimum catalyst-day move (fraction). Default 4%.
        vol_mult: Volume multiplier for catalyst day. Default 2.0×.
        hold_days: Drift hold window in sessions. Default 5.
        start_date: Optional start date "YYYY-MM-DD" (enables historical mode).
        end_date: Optional end date "YYYY-MM-DD" (enables historical mode).

    Returns:
        Signal dict with action, confidence, catalyst_move, days_since, take_profit — or error dict.
    """
    symbol = symbol.upper().strip()
    try:
        if start_date and end_date:
            df = _fetch_bars_range("earnings_drift_analyze", symbol, start_date, end_date, timeframe)
            if df is None:
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}\u2013{end_date}"}
            result = _earnings_drift_skill.analyze_bars(
                df, lookback=lookback, min_move=min_move, vol_mult=vol_mult, hold_days=hold_days,
            )
            result.update({"symbol": symbol, "timeframe": timeframe,
                           "start_date": start_date, "end_date": end_date, "mode": "historical"})
        else:
            result = _earnings_drift_skill.generate_signals(
                symbol=symbol, timeframe=timeframe, lookback_days=lookback_days,
                lookback=lookback, min_move=min_move, vol_mult=vol_mult, hold_days=hold_days,
            )
        return _to_native(result)
    except Exception as exc:
        logger.warning(f"[registry] earnings_drift_analyze failed for {symbol}: {exc}")
        return {"error": str(exc), "symbol": symbol}


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


def _get_market_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1Min",
    **kwargs,
) -> list:
    """Fetch OHLCV bars for a symbol; auto-fetches from Alpaca API if not in DB.

    Replaces the former ``fetch_historical_data`` registry function.  A single
    call now covers both ensuring data is present and returning the actual
    bar records — eliminating the two-step fetch-then-read pattern.

    Args:
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".
        timeframe: Bar timeframe e.g. "1Day", "1Min" (default "1Min").

    Returns:
        List of bar dicts; empty list if no data and API returned nothing.
    """
    try:
        from datetime import datetime as _dt
        from src.common.dao import AlpacaDAO

        # Normalise timeframe aliases the LLM commonly emits
        _TF_MAP = {"1d": "1Day", "1day": "1Day", "1h": "1Hour", "1hour": "1Hour",
                   "1m": "1Min", "1min": "1Min"}
        tf = _TF_MAP.get(timeframe.lower(), timeframe)

        start_dt = _dt.fromisoformat(start_date)
        end_dt   = _dt.fromisoformat(end_date)

        dao = AlpacaDAO()
        df = dao.get_bars(symbol, start_dt, end_dt, tf)
        dao.close()

        if df.empty:
            # Not in local DB — pull from Alpaca API; save_bars is called inside
            logger.info(f"[registry] get_market_bars: no local data for {symbol}, fetching from API")
            try:
                from src.common.external.alpaca import fetch_historical_bars
                df = fetch_historical_bars(
                    symbol=symbol, start=start_date, end=end_date, timeframe=tf
                )
            except Exception as fetch_exc:
                logger.warning(f"[registry] get_market_bars: API fetch failed for {symbol}: {fetch_exc}")

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


# ── Order execution wrappers (new) ────────────────────────────────────────────

def _execute_order_wrapped(
    symbol: str,
    qty: float,
    side: str,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    **kwargs,
) -> Dict:
    """Wrap execute_order_core — place a market or limit order.

    Args:
        symbol: Stock ticker.
        qty: Number of shares (> 0).
        side: "buy" or "sell".
        order_type: "market" (default) or "limit".
        limit_price: Required for limit orders.

    Returns:
        Order result dict with id, symbol, qty, side, type, status.
    """
    try:
        return execute_order_core(
            symbol=symbol,
            qty=qty,
            side=side,
            order_type=order_type,
            limit_price=limit_price,
        )
    except Exception as exc:
        logger.warning(f"[registry] execute_order failed ({side} {qty} {symbol}): {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _close_position_wrapped(symbol: str, **kwargs) -> Dict:
    """Wrap close_position_core — liquidate a position at market price.

    Args:
        symbol: Stock ticker whose position to close.

    Returns:
        Closing market-order result dict.
    """
    try:
        return close_position_core(symbol=symbol)
    except Exception as exc:
        logger.warning(f"[registry] close_position failed for {symbol}: {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _scale_position_wrapped(
    symbol: str,
    target_pct: float,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    **kwargs,
) -> Dict:
    """Wrap scale_position_core — resize position to a target % of equity.

    Args:
        symbol: Stock ticker.
        target_pct: Target position size as fraction of equity (e.g. 0.05 = 5%).
            Use 0.0 to fully close the position.
        order_type: "market" (default) or "limit".
        limit_price: Required for limit orders.

    Returns:
        Scale result dict with action, current_qty, target_qty, delta_qty,
        current_pct, order details.
    """
    try:
        return scale_position_core(
            symbol=symbol,
            target_pct=target_pct,
            order_type=order_type,
            limit_price=limit_price,
        )
    except Exception as exc:
        logger.warning(f"[registry] scale_position failed for {symbol}: {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _execute_strategy_signal_wrapped(
    symbol: str,
    signal: str,
    confidence: float = 1.0,
    base_position_pct: float = 0.05,
    order_type: str = "market",
    **kwargs,
) -> Dict:
    """Wrap execute_strategy_signal_core — translate a signal into a trade.

    Maps buy/sell/hold signals to actual Alpaca orders.  Confidence
    scales the allocated position size.

    Args:
        symbol: Stock ticker.
        signal: "buy" | "sell" | "hold" (case-insensitive).
        confidence: Conviction score 0–1.  Multiplies base_position_pct.
        base_position_pct: Max allocation per position (default 5%).
        order_type: "market" (default) or "limit".

    Returns:
        Dict with action, order (or None for hold), target_pct, confidence.
    """
    try:
        return execute_strategy_signal_core(
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            base_position_pct=base_position_pct,
            order_type=order_type,
        )
    except Exception as exc:
        logger.warning(f"[registry] execute_strategy_signal failed for {symbol}: {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol, "signal": signal}


# ── Raw Alpaca order wrappers (order_node) ─────────────────────────────────────

def _fetch_orders_wrapped(
    status: str = "all",
    limit: int = 100,
    **kwargs,
) -> Dict:
    """Fetch orders from Alpaca with optional status / limit filters.

    Args:
        status: ``'open'`` | ``'closed'`` | ``'all'`` (default ``'all'``).
        limit: Maximum number of orders to return (default 100).

    Returns:
        List of order dicts inside ``{"orders": [...], "count": int}``.
    """
    try:
        from src.common.external.alpaca_portfolio import fetch_orders as _fetch
        orders = _fetch(status=status, limit=limit)
        return {"orders": orders, "count": len(orders)}
    except Exception as exc:
        logger.warning(f"[registry] fetch_orders failed: {exc}")
        return {"status": "error", "error": str(exc)}


def _place_market_order_wrapped(
    symbol: str,
    qty: float,
    side: str,
    **kwargs,
) -> Dict:
    """Place a market order via Alpaca.

    Args:
        symbol: Stock ticker.
        qty: Shares to buy or sell (> 0).
        side: ``'buy'`` or ``'sell'``.

    Returns:
        Order result dict with id, symbol, qty, side, type, status.
    """
    try:
        from src.common.external.alpaca_portfolio import place_market_order as _place
        return _place(symbol=symbol, qty=qty, side=side)
    except Exception as exc:
        logger.warning(f"[registry] place_market_order failed ({side} {qty} {symbol}): {exc}")
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _place_limit_order_wrapped(
    symbol: str,
    qty: float,
    side: str,
    limit_price: float,
    time_in_force: str = "day",
    **kwargs,
) -> Dict:
    """Place a limit order via Alpaca.

    Args:
        symbol: Stock ticker.
        qty: Shares to buy or sell (> 0).
        side: ``'buy'`` or ``'sell'``.
        limit_price: Price cap (buy) or floor (sell).
        time_in_force: ``'day'`` | ``'gtc'`` | ``'ioc'`` | ``'fok'`` (default ``'day'``).

    Returns:
        Order result dict with id, symbol, qty, type, limit_price, status.
    """
    try:
        from src.common.external.alpaca_portfolio import place_limit_order as _place
        return _place(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=limit_price,
            time_in_force=time_in_force,
        )
    except Exception as exc:
        logger.warning(
            f"[registry] place_limit_order failed ({side} {qty} {symbol} @ {limit_price}): {exc}"
        )
        return {"status": "error", "error": str(exc), "symbol": symbol}


def _cancel_order_wrapped(order_id: str, **kwargs) -> Dict:
    """Cancel an open order by its UUID.

    Args:
        order_id: Alpaca order UUID string.

    Returns:
        ``{"order_id": str, "status": "cancelled", "timestamp": str}``.
    """
    try:
        from src.common.external.alpaca_portfolio import cancel_order as _cancel
        return _cancel(order_id=order_id)
    except Exception as exc:
        logger.warning(f"[registry] cancel_order failed ({order_id}): {exc}")
        return {"status": "error", "error": str(exc), "order_id": order_id}


def _cancel_all_orders_wrapped(**kwargs) -> Dict:
    """Cancel all open orders.

    Returns:
        ``{"cancelled_count": int, "status": "all_cancelled", "timestamp": str}``.
    """
    try:
        from src.common.external.alpaca_portfolio import cancel_all_orders as _cancel_all
        return _cancel_all()
    except Exception as exc:
        logger.warning(f"[registry] cancel_all_orders failed: {exc}")
        return {"status": "error", "error": str(exc)}


def _close_all_positions_wrapped(cancel_orders_first: bool = True, **kwargs) -> Dict:
    """Liquidate all open positions at market price.

    Args:
        cancel_orders_first: Cancel open orders before closing positions
            (default ``True`` to avoid partial-fill conflicts).

    Returns:
        ``{"closed_count": int, "status": "all_closed", "timestamp": str}``.
    """
    try:
        from src.common.external.alpaca_portfolio import close_all_positions as _close_all
        return _close_all(cancel_orders_first=cancel_orders_first)
    except Exception as exc:
        logger.warning(f"[registry] close_all_positions failed: {exc}")
        return {"status": "error", "error": str(exc)}


def _get_latest_price(symbol: str, timeframe: str = "1Min") -> dict:
    """Get the most recent price for a symbol.

    Priority order:
    1. **live_trades** — most recent tick from the last hour (freshest intraday price).
    2. **Latest bar close** — falls back to the most recent OHLCV bar when no
       live tick is available (e.g. after-hours or when streaming is inactive).

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe for the fallback bar query (default ``"1Min"``).

    Returns:
        Dict with at minimum a ``close`` key, plus source / timestamp metadata.
        Returns an error dict on failure.
    """
    try:
        from datetime import datetime as _dt, timedelta as _td
        from src.common.dao import AlpacaDAO

        symbol = symbol.strip().upper()
        dao = AlpacaDAO()

        # 1. Prefer freshest live tick from the last hour
        try:
            now = _dt.now()
            df_live = dao.get_recent_trades(
                symbol, start=now - _td(hours=1), end=now, limit=None
            )
            if not df_live.empty:
                last = df_live.iloc[-1]  # ASC order → iloc[-1] is most recent
                dao.close()
                return {
                    "symbol": symbol,
                    "close": float(last["price"]),
                    "source": "live_trades",
                    "timestamp": str(last["timestamp"]),
                }
        except Exception:
            pass  # live_trades unavailable — fall through to bar price

        # 2. Fall back to latest OHLCV bar (may be previous session close)
        result = dao.get_latest_bar(symbol, timeframe)
        dao.close()
        if result:
            result = _to_native(result)
            result.setdefault("source", "bar")
            return result
        return {"error": f"No price data found for {symbol}"}
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
    """Retrieve tick-level trades for a symbol across live and historical tables.

    Queries both the ``live_trades`` staging table and ``historical_trades``
    archive, deduplicating on (symbol, timestamp, trade_id) so rows that were
    just archived are not double-counted.

    Args:
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".
        limit: Max number of trades to return.

    Returns:
        List of trade dicts or error dict.
    """
    try:
        from datetime import datetime as _dt
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        df = dao.get_recent_trades(symbol, _dt.fromisoformat(start_date), _dt.fromisoformat(end_date), limit=limit)
        dao.close()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_tick_trades failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_trade_count(symbol: str, start_date: str, end_date: str) -> dict:
    """Get deduplicated trade count for a symbol across live and historical tables.

    Counts distinct (symbol, timestamp, trade_id) tuples from both
    ``live_trades`` and ``historical_trades`` to avoid undercounting
    trades that are still in the staging table awaiting archival.

    Args:
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".

    Returns:
        Dict with trade_count key.
    """
    try:
        from datetime import datetime as _dt
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        count = dao.get_recent_trade_count(symbol, _dt.fromisoformat(start_date), _dt.fromisoformat(end_date))
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
    "check_data_availability": _check_data_availability_wrapped,
    # ── Quant indicators (wrapped to fetch bars internally) ───────────────────
    "calc_momentum":           _calc_momentum_wrapped,
    "calc_volatility_bands":   _calc_volatility_wrapped,
    "calc_volume_flow":        _calc_volume_wrapped,
    "analyze_candle_structure": _analyze_candles_wrapped,
    "mean_reversion_analyze":  _mean_reversion_analyze,
    # ── Quant strategies — day trading ───────────────────────────────────────
    "vwap_reversion_analyze":           _vwap_reversion_wrapped,
    "opening_range_breakout_analyze":   _opening_range_breakout_wrapped,
    "rsi_divergence_analyze":           _rsi_divergence_wrapped,
    "momentum_burst_analyze":           _momentum_burst_wrapped,
    # ── Quant strategies — swing / multi-day ─────────────────────────────────
    "golden_cross_analyze":             _golden_cross_wrapped,
    "breakout_52w_analyze":             _breakout_52w_wrapped,
    "mean_reversion_daily_analyze":     _mean_reversion_daily_wrapped,
    "earnings_drift_analyze":           _earnings_drift_wrapped,
    # ── Backtester core ───────────────────────────────────────────────────────
    "backtest_strategy":       _backtest_strategy,
    # ── AlpacaDAO market data ─────────────────────────────────────────────────
    "get_market_bars":         _get_market_bars,
    # fetch_historical_data: alias of get_market_bars — used by quant + backtester
    # to explicitly signal "download bars into DB"; same implementation.
    "fetch_historical_data":   _get_market_bars,
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
    # ── Order execution & strategy scaling ───────────────────────────────────
    "execute_order":           _execute_order_wrapped,
    "close_position":          _close_position_wrapped,
    "scale_position":          _scale_position_wrapped,
    "execute_strategy_signal": _execute_strategy_signal_wrapped,
    # ── Raw Alpaca order operations (order_node) ───────────────────────────
    "fetch_orders":            _fetch_orders_wrapped,
    "place_market_order":      _place_market_order_wrapped,
    "place_limit_order":       _place_limit_order_wrapped,
    "cancel_order":            _cancel_order_wrapped,
    "cancel_all_orders":       _cancel_all_orders_wrapped,
    "close_all_positions":     _close_all_positions_wrapped,
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
        "check_data_availability": {
            "description": "Check if historical bars exist in DB for the given period.",
            "params": {
                "symbol": "str",
                "start_date": "str — YYYY-MM-DD",
                "end_date": "str — YYYY-MM-DD",
                "timeframe": "str — default '1Min'",
            },
        },
        "fetch_historical_data": {
            "description": "Download bars from Alpaca API and persist to local DB. "
                           "Alias of get_market_bars with explicit download semantics. "
                           "Use when data is confirmed missing; set priority=3.",
            "params": {
                "symbol": "str",
                "start_date": "str — YYYY-MM-DD",
                "end_date": "str — YYYY-MM-DD",
                "timeframe": "str — default '1Min'",
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
        # ── Day-trading strategies ────────────────────────────────────────────
        "vwap_reversion_analyze": {
            "description": "VWAP intraday reversion — detect deviation from VWAP and fade back to it.",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Min'",
                "lookback_days": "int — default 5",
                "dev_pct": "float — VWAP deviation threshold, default 0.005 (0.5%)",
                "vol_mult": "float — volume spike multiplier, default 2.0",
                "stop_pct": "float — stop-loss distance, default 0.003 (0.3%)",
                "start_date": "str — YYYY-MM-DD (enables historical mode)",
                "end_date": "str — YYYY-MM-DD (enables historical mode)",
            },
        },
        "opening_range_breakout_analyze": {
            "description": "Opening range breakout — trade breakouts beyond the first N-bar opening range.",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Min'",
                "lookback_days": "int — default 2",
                "range_bars": "int — opening range bar count, default 15",
                "start_date": "str — YYYY-MM-DD (enables historical mode)",
                "end_date": "str — YYYY-MM-DD (enables historical mode)",
            },
        },
        "rsi_divergence_analyze": {
            "description": "RSI divergence scalp — detect bullish/bearish RSI divergence for scalp entries.",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Min'",
                "lookback_days": "int — default 5",
                "lookback": "int — divergence scan window, default 20",
                "oversold": "float — RSI oversold threshold, default 35.0",
                "start_date": "str — YYYY-MM-DD (enables historical mode)",
                "end_date": "str — YYYY-MM-DD (enables historical mode)",
            },
        },
        "momentum_burst_analyze": {
            "description": "Momentum burst — detect explosive volume+price bars for momentum entries.",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Min'",
                "lookback_days": "int — default 3",
                "vol_mult": "float — volume spike multiplier, default 3.0",
                "min_move": "float — minimum bar price move, default 0.005 (0.5%)",
                "trail_pct": "float — trailing stop distance, default 0.002 (0.2%)",
                "start_date": "str — YYYY-MM-DD (enables historical mode)",
                "end_date": "str — YYYY-MM-DD (enables historical mode)",
            },
        },
        # ── Swing / multi-day strategies ──────────────────────────────────────
        "golden_cross_analyze": {
            "description": "Golden/death cross — SMA-50 vs SMA-200 crossover signal on daily bars.",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Day'",
                "lookback_days": "int — default 365",
                "fast": "int — fast SMA period, default 50",
                "slow": "int — slow SMA period, default 200",
                "start_date": "str — YYYY-MM-DD (enables historical mode)",
                "end_date": "str — YYYY-MM-DD (enables historical mode)",
            },
        },
        "breakout_52w_analyze": {
            "description": "52-week breakout — new annual high with volume confirmation.",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Day'",
                "lookback_days": "int — default 400",
                "lookback": "int — prior-high scan window, default 252",
                "vol_mult": "float — volume multiplier, default 1.5",
                "trail_pct": "float — trailing stop distance, default 0.10 (10%)",
                "start_date": "str — YYYY-MM-DD (enables historical mode)",
                "end_date": "str — YYYY-MM-DD (enables historical mode)",
            },
        },
        "mean_reversion_daily_analyze": {
            "description": "Daily mean reversion — Z-score + Bollinger analysis on daily bars (higher threshold than intraday).",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Day'",
                "lookback_days": "int — default 90",
                "lookback": "int — daily bars for statistics, default 20",
                "threshold": "float — Z-score entry threshold, default 2.5",
                "ma_period": "int — moving average period, default 20",
                "start_date": "str — YYYY-MM-DD (enables historical mode)",
                "end_date": "str — YYYY-MM-DD (enables historical mode)",
            },
        },
        "earnings_drift_analyze": {
            "description": "Earnings drift — ride post-earnings momentum for hold_days sessions.",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Day'",
                "lookback_days": "int — default 60",
                "lookback": "int — catalyst scan window, default 10",
                "min_move": "float — minimum catalyst-day move, default 0.04 (4%)",
                "vol_mult": "float — volume multiplier for catalyst day, default 2.0",
                "hold_days": "int — drift hold window in sessions, default 5",
                "start_date": "str — YYYY-MM-DD (enables historical mode)",
                "end_date": "str — YYYY-MM-DD (enables historical mode)",
            },
        },
        "backtest_strategy": {
            "description": "Backtest a trading strategy on historical data.",
            "params": {
                "ticker": "str",
                "start_date": "str — YYYY-MM-DD",
                "end_date": "str — YYYY-MM-DD",
                "strategy": (
                    "str — 'buy-and-hold' | 'mean-reversion' | 'momentum' | 'value' | "
                    "'vwap-reversion' | 'opening-range-breakout' | 'rsi-divergence' | 'momentum-burst' | "
                    "'golden-cross' | 'breakout-52w' | 'mean-reversion-daily' | 'earnings-drift'"
                ),
                "initial_capital": "float — default 100000.0",
            },
        },
        # ── AlpacaDAO ─────────────────────────────────────────────────────────
        "get_market_bars": {
            "description": "Fetch OHLCV bars for a symbol; auto-fetches from Alpaca API if not in local DB.",
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
                "snapshot_date": "str \u2014 YYYY-MM-DD",
                "end_date": "str \u2014 YYYY-MM-DD",
                "tickers": "dict \u2014 {symbol: {swap_to: str, quantity: int}}",
            },
        },
        # \u2500\u2500 Order execution & strategy scaling (new) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        "execute_order": {
            "description": "Place a market or limit order via Alpaca. Preferred for direct single-symbol execution.",
            "params": {
                "symbol": "str",
                "qty": "float \u2014 number of shares (> 0)",
                "side": "str \u2014 'buy' or 'sell'",
                "order_type": "str \u2014 'market' (default) or 'limit'",
                "limit_price": "float \u2014 required for limit orders",
            },
            "note": "REQUIRES HUMAN APPROVAL \u2014 always present to the user before executing",
        },
        "close_position": {
            "description": "Liquidate the full open position for a symbol at market price.",
            "params": {
                "symbol": "str",
            },
            "note": "REQUIRES HUMAN APPROVAL \u2014 always present to the user before executing",
        },
        "scale_position": {
            "description": (
                "Resize an open (or new) position to a target percentage of total equity. "
                "Use target_pct=0.0 to fully close the position. "
                "Computes the buy/sell delta automatically."
            ),
            "params": {
                "symbol": "str",
                "target_pct": "float \u2014 target allocation as fraction of equity (e.g. 0.05 = 5%)",
                "order_type": "str \u2014 'market' (default) or 'limit'",
                "limit_price": "float \u2014 required for limit orders",
            },
            "note": "REQUIRES HUMAN APPROVAL \u2014 always present to the user before executing",
        },
        "execute_strategy_signal": {
            "description": (
                "Translate a quant strategy signal (buy/sell/hold) into a live Alpaca order. "
                "Confidence score scales the position size relative to base_position_pct."
            ),
            "params": {
                "symbol": "str",
                "signal": "str \u2014 'buy' | 'sell' | 'hold'",
                "confidence": "float \u2014 conviction score 0\u20131, default 1.0",
                "base_position_pct": "float \u2014 max allocation per position, default 0.05",
                "order_type": "str \u2014 'market' (default) or 'limit'",
            },
            "note": "REQUIRES HUMAN APPROVAL \u2014 always present to the user before executing",
        },
        # \u2500\u2500 Raw Alpaca order operations (order_node) \u2500\u2500
        "fetch_orders": {
            "description": "List orders from Alpaca with optional status and limit filters.",
            "params": {
                "status": "str \u2014 'open' | 'closed' | 'all' (default 'all')",
                "limit": "int \u2014 max orders to return (default 100)",
            },
        },
        "place_market_order": {
            "description": "Place a market order for immediate execution at the best available price.",
            "params": {
                "symbol": "str",
                "qty": "float \u2014 number of shares (> 0)",
                "side": "str \u2014 'buy' or 'sell'",
            },
            "note": "REQUIRES HUMAN APPROVAL",
        },
        "place_limit_order": {
            "description": "Place a limit order that executes only at the specified price or better.",
            "params": {
                "symbol": "str",
                "qty": "float \u2014 number of shares (> 0)",
                "side": "str \u2014 'buy' or 'sell'",
                "limit_price": "float \u2014 price cap (buy) or floor (sell)",
                "time_in_force": "str \u2014 'day' | 'gtc' | 'ioc' | 'fok' (default 'day')",
            },
            "note": "REQUIRES HUMAN APPROVAL",
        },
        "cancel_order": {
            "description": "Cancel a specific open order by its Alpaca UUID.",
            "params": {
                "order_id": "str \u2014 Alpaca order UUID",
            },
            "note": "REQUIRES HUMAN APPROVAL",
        },
        "cancel_all_orders": {
            "description": "Cancel all open orders at once.",
            "params": {},
            "note": "REQUIRES HUMAN APPROVAL",
        },
        "close_all_positions": {
            "description": "Liquidate all open positions at market price.",
            "params": {
                "cancel_orders_first": "bool \u2014 cancel open orders before closing (default True)",
            },
            "note": "REQUIRES HUMAN APPROVAL",
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

    assert len(FUNCTION_REGISTRY) == 56, f"Expected 56 functions, got {len(FUNCTION_REGISTRY)}"  # noqa: E501
    print("\n[OK] All 56 functions registered")

    schema = get_registry_schema()
    assert len(schema) == 56, f"Expected 56 schema entries, got {len(schema)}"
    print("[OK] Registry schema returned")

    print("\n[ALL OK] registry/functions.py smoke test passed")
