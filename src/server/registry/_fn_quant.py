"""Quant skill registry functions — indicators, strategies, and backtester.

Covers:
  - Technical indicators: momentum (MACD/RSI), volatility (Bollinger), volume (OBV), candles
  - Intraday strategies: VWAP reversion, opening-range breakout, RSI divergence, momentum burst
  - Swing strategies: golden cross, 52-week breakout, mean reversion (daily), earnings drift
  - Mean reversion (intraday, with AnalysisDAO persistence)
  - Backtest strategy runner
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.utils import get_logger
from src.server.models.strategies import (
    BacktestInput,
    CandleInput,
    MeanReversionInput,
    MomentumInput,
    VolatilityInput,
    VolumeInput,
    BacktestOutput,
    CandleOutput,
    MeanReversionOutput,
    MomentumOutput,
    VolatilityOutput,
    VolumeOutput,
)
from src.server.skills.quant import (
    momentum_skill as _momentum_skill,
    volatility_skill as _volatility_skill,
    volume_skill as _volume_skill,
    candlestick_skill as _candlestick_skill,
    mean_reversion_skill as _mean_reversion_skill,
    vwap_reversion_skill as _vwap_reversion_skill,
    opening_range_breakout_skill as _opening_range_breakout_skill,
    rsi_divergence_scalp_skill as _rsi_divergence_scalp_skill,
    momentum_burst_skill as _momentum_burst_skill,
    golden_cross_skill as _golden_cross_skill,
    breakout_52w_skill as _breakout_52w_skill,
    earnings_drift_skill as _earnings_drift_skill,
)
from src.server.skills.backtester.backtest_strategy import (
    backtest_strategy_core as _backtest_strategy_raw,
)
from src.server.registry._fn_helpers import (
    _fetch_bars_range,
    _out,
    _to_native,
)

logger = get_logger(__name__)


# ── Quant indicators ──────────────────────────────────────────────────────────


def _calc_momentum_wrapped(
    symbol: str,
    timeframe: str = "1Min",
    lookback_days: int = 90,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_extra,
) -> Dict:
    """Compute MACD + RSI signals.

    Supports two modes:
    - **Live mode** (default): fetches recent bars using ``lookback_days`` from today.
    - **Historical mode**: analyzes a specific date range when ``start_date`` and
      ``end_date`` are both provided.

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
            return _out(MomentumOutput, {"error": f"No data for {inp.symbol}/{inp.timeframe} in range {inp.start_date}–{inp.end_date}", "symbol": inp.symbol})
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
            return _out(VolatilityOutput, {"error": f"No data for {inp.symbol}/{inp.timeframe} in range {inp.start_date}–{inp.end_date}", "symbol": inp.symbol})
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
            return _out(VolumeOutput, {"error": f"No data for {inp.symbol}/{inp.timeframe} in range {inp.start_date}–{inp.end_date}", "symbol": inp.symbol})
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
            return _out(CandleOutput, {"error": f"No data for {inp.symbol}/{inp.timeframe} in range {inp.start_date}–{inp.end_date}", "symbol": inp.symbol})
        result = _candlestick_skill.analyze_bars(df)
        result.update({"symbol": inp.symbol, "timeframe": inp.timeframe,
                       "start_date": inp.start_date, "end_date": inp.end_date, "mode": "historical"})
        return _out(CandleOutput, result)
    return _out(CandleOutput, _candlestick_skill.generate_signals(inp.symbol, timeframe=inp.timeframe, lookback_days=inp.lookback_days))


# ── Mean reversion (intraday) ──────────────────────────────────────────────────


def _save_mean_reversion_signal(symbol: str, timeframe: str, result: Dict) -> None:
    """Persist a mean-reversion analysis result to AnalysisDAO.

    Called after both live and historical runs so user-directed signals appear
    alongside automated pipeline signals (distinguishable via model_used="user-directed").

    Args:
        symbol: Ticker (already upper-cased by MeanReversionInput).
        timeframe: Bar timeframe used for the analysis.
        result: Full analysis dict as returned by MeanReversionSkill.
    """
    try:
        from src.common.utils.container import get_analysis_dao
        rec = result.get("trade_recommendation", {})
        signals = result.get("signals", {})
        s_dao = get_analysis_dao()
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
        from src.common.utils import config as _cfg
        if _cfg.get("strategy.hitl.enabled", False):
            try:
                get_analysis_dao().execute(
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
                logger.info(f"[registry] Signal for {symbol} marked 'pending_review' (HITL enabled)")
            except Exception as _hitl_exc:
                logger.warning(f"[registry] HITL status update failed for {symbol}: {_hitl_exc}")
        logger.info(
            f"[registry] Persisted user-directed signal for {symbol}/{timeframe}: "
            f"action={rec.get('action','hold')}  confidence={rec.get('confidence',0.0):.2f}"
        )
    except Exception as exc:
        logger.warning(f"[registry] AnalysisDAO persist failed for {symbol}: {exc}")


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

    Results are persisted to ``strategy_results`` (``model_used="user-directed"``).

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
                return _out(MeanReversionOutput, {"error": f"No data for {inp.symbol}/{inp.timeframe} in range {inp.start_date}–{inp.end_date}", "symbol": inp.symbol})
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

        if "error" not in result:
            _save_mean_reversion_signal(inp.symbol, inp.timeframe, result)

        return _out(MeanReversionOutput, result)
    except Exception as exc:
        logger.warning(f"[registry] mean_reversion_analyze failed for {inp.symbol}: {exc}")
        return _out(MeanReversionOutput, {"error": str(exc), "symbol": inp.symbol})


# ── Day-trading strategies ─────────────────────────────────────────────────────


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
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}–{end_date}"}
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
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}–{end_date}"}
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
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}–{end_date}"}
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
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}–{end_date}"}
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


# ── Swing / multi-day strategies ──────────────────────────────────────────────


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
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}–{end_date}"}
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
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}–{end_date}"}
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
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}–{end_date}"}
            result = _mean_reversion_skill.analyze_bars(
                df, lookback=lookback, threshold=threshold, ma_period=ma_period,
            )
            result.update({"symbol": symbol, "timeframe": timeframe,
                           "start_date": start_date, "end_date": end_date, "mode": "historical"})
        else:
            result = _mean_reversion_skill.generate_signals(
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
                return {"error": f"No data for {symbol}/{timeframe} in range {start_date}–{end_date}"}
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


# ── Backtester ────────────────────────────────────────────────────────────────


def _backtest_strategy(
    symbol: str = None,
    start_date: str = None,
    end_date: str = None,
    strategy: str = "mean-reversion",
    initial_capital: float = 100000.0,
    strategy_params: Dict = None,
    ticker: str = None,       # legacy alias
    task_id: str = None,      # absorbed from LLM planning
    workflow_type: str = None,
    note: str = None,
    metrics_requested: list = None,
    **kwargs,
) -> Dict:
    """Run backtest_strategy_core for the given symbol and strategy.

    ``ticker`` is accepted as a legacy alias but ``symbol`` is the canonical param.
    Extra kwargs (task_id, workflow_type, note, metrics_requested) are silently
    absorbed — they come from LLM planning but are not used by the core skill.

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
    resolved_ticker = symbol or ticker
    if not resolved_ticker:
        return {"error": "backtest_strategy requires 'symbol'"}
    if not start_date or not end_date:
        return {"error": "backtest_strategy requires 'start_date' and 'end_date'"}

    resolved_strategy = strategy
    resolved_params = strategy_params
    if isinstance(strategy, dict):
        resolved_strategy = strategy.get("name", "mean-reversion")
        if not resolved_params:
            resolved_params = strategy.get("params")

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
