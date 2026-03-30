"""Function registry for the semi-auto executor node.

Maps string function names (as output by LLM reasoning agents) to Python callables.
Quant skill functions require a pandas DataFrame so they are wrapped to fetch bars
from AlpacaDAO internally before calling the underlying skill.

Hyphenated skill directories are loaded via importlib.util (same pattern as
src/langgraph/nodes/quant_node.py and src/langgraph/nodes/backtester_node.py).
"""

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

# ── Skill directory paths ─────────────────────────────────────────────────────

_QUANT_SKILLS = project_root / "src" / "agentic" / "agents" / "quant" / "skills"
_BT_SKILLS = project_root / "src" / "agentic" / "agents" / "backtester" / "skills"


def _load_skill(base_dir: Path, folder: str, filename: str):
    """Load a skill module from a potentially hyphenated folder.

    Args:
        base_dir: Parent directory containing skill folders.
        folder: Skill folder name (may contain hyphens).
        filename: Python file inside the folder.

    Returns:
        Loaded module object, or None on failure.
    """
    path = base_dir / folder / filename
    module_name = f"semi_auto_skill_{folder.replace('-', '_')}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        logger.warning(f"[registry] failed to load {folder}/{filename}: {exc}")
        return None


# ── Portfolio skills (normal Python imports) ──────────────────────────────────

try:
    from src.agentic.agents.portfolio.skills.portfoliostatus.status import (
        get_portfolio_status_core,
        get_positions_summary_core,
    )
except Exception as _e:
    logger.warning(f"[registry] portfolio status skill load failed: {_e}")
    get_portfolio_status_core = None
    get_positions_summary_core = None

try:
    from src.agentic.agents.portfolio.skills.health.health import check_portfolio_health_core
except Exception as _e:
    logger.warning(f"[registry] portfolio health skill load failed: {_e}")
    check_portfolio_health_core = None

try:
    from src.agentic.agents.portfolio.skills.datamanagement.data import (
        fetch_historical_data_core,
        check_data_availability_core,
    )
except Exception as _e:
    logger.warning(f"[registry] portfolio data skill load failed: {_e}")
    fetch_historical_data_core = None
    check_data_availability_core = None

# ── Quant skills (hyphenated directories via importlib) ───────────────────────

_momentum_mod = _load_skill(_QUANT_SKILLS, "momentum-indicators", "momentum.py")
_volatility_mod = _load_skill(_QUANT_SKILLS, "volatility-indicators", "volatility.py")
_volume_mod = _load_skill(_QUANT_SKILLS, "volume-indicators", "volume.py")
_candles_mod = _load_skill(_QUANT_SKILLS, "candlestick-patterns", "candles.py")
_mr_mod = _load_skill(_QUANT_SKILLS, "mean-reversion-strategy", "mean_reversion.py")

_calc_momentum_raw = getattr(_momentum_mod, "calc_momentum_package", None)
_calc_volatility_raw = getattr(_volatility_mod, "calc_volatility_bands", None)
_calc_volume_raw = getattr(_volume_mod, "calc_volume_flow", None)
_analyze_candles_raw = getattr(_candles_mod, "analyze_candle_structure", None)
_MeanReversionStrategy = getattr(_mr_mod, "MeanReversionStrategy", None)

# ── Backtester skills (hyphenated directories via importlib) ─────────────────

_bt_strategy_mod = _load_skill(_BT_SKILLS, "backtest-strategy", "strategy.py")
_backtest_strategy_raw = getattr(_bt_strategy_mod, "backtest_strategy_core", None)


# ── Wrapper helpers ───────────────────────────────────────────────────────────

def _fetch_bars_for_symbol(symbol: str, timeframe: str = "1Day", lookback_days: int = 90):
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


def _calc_momentum_wrapped(symbol: str, timeframe: str = "1Day", lookback_days: int = 90) -> Dict:
    """Fetch bars then compute MACD + RSI momentum indicators.

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe.
        lookback_days: Lookback period in calendar days.

    Returns:
        Dict with macd and rsi fields, or error dict.
    """
    if _calc_momentum_raw is None:
        return {"error": "momentum skill not available"}
    df = _fetch_bars_for_symbol(symbol, timeframe, lookback_days)
    if df is None:
        return {"error": f"No data for {symbol}/{timeframe}"}
    return _calc_momentum_raw(df)


def _calc_volatility_wrapped(symbol: str, timeframe: str = "1Day", lookback_days: int = 90) -> Dict:
    """Fetch bars then compute Bollinger Bands volatility indicators.

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe.
        lookback_days: Lookback period in calendar days.

    Returns:
        Dict with upper, middle, lower, bandwidth, or error dict.
    """
    if _calc_volatility_raw is None:
        return {"error": "volatility skill not available"}
    df = _fetch_bars_for_symbol(symbol, timeframe, lookback_days)
    if df is None:
        return {"error": f"No data for {symbol}/{timeframe}"}
    return _calc_volatility_raw(df)


def _calc_volume_wrapped(symbol: str, timeframe: str = "1Day", lookback_days: int = 90) -> Dict:
    """Fetch bars then compute OBV and volume flow indicators.

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe.
        lookback_days: Lookback period in calendar days.

    Returns:
        Dict with obv, volume_trend, avg_volume_10d, current_vs_avg, or error dict.
    """
    if _calc_volume_raw is None:
        return {"error": "volume skill not available"}
    df = _fetch_bars_for_symbol(symbol, timeframe, lookback_days)
    if df is None:
        return {"error": f"No data for {symbol}/{timeframe}"}
    return _calc_volume_raw(df)


def _analyze_candles_wrapped(symbol: str, timeframe: str = "1Day", lookback_days: int = 30) -> Dict:
    """Fetch bars then detect candlestick patterns.

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe.
        lookback_days: Lookback period in calendar days.

    Returns:
        Dict with patterns, last_candle_type, etc., or error dict.
    """
    if _analyze_candles_raw is None:
        return {"error": "candlestick skill not available"}
    df = _fetch_bars_for_symbol(symbol, timeframe, lookback_days)
    if df is None:
        return {"error": f"No data for {symbol}/{timeframe}"}
    return _analyze_candles_raw(df)


def _mean_reversion_analyze(symbol: str, lookback: int = 60, threshold: float = 2.0) -> Dict:
    """Run MeanReversionStrategy.analyze() for the given symbol.

    Args:
        symbol: Stock ticker.
        lookback: Lookback period in trading days.
        threshold: Z-score threshold for entry signal.

    Returns:
        Analysis dict from MeanReversionStrategy.analyze(), or error dict.
    """
    if _MeanReversionStrategy is None:
        return {"error": "mean_reversion skill not available"}
    try:
        strategy = _MeanReversionStrategy(symbol=symbol, lookback=lookback, threshold=threshold)
        return strategy.analyze()
    except Exception as exc:
        logger.warning(f"[registry] mean_reversion_analyze failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _backtest_strategy(
    ticker: str = None,
    start_date: str = None,
    end_date: str = None,
    strategy: str = "mean-reversion",
    initial_capital: float = 100000.0,
    strategy_params: Dict = None,
    # LLM may pass these — accepted and ignored
    symbol: str = None,
    task_id: str = None,
    workflow_type: str = None,
    note: str = None,
    metrics_requested: list = None,
    **kwargs,
) -> Dict:
    """Run backtest_strategy_core for the given ticker and strategy.

    Accepts ``symbol`` as an alias for ``ticker`` so the LLM can use either.
    Extra kwargs (task_id, workflow_type, note, metrics_requested) are silently
    absorbed — they come from LLM planning but are not used by the core skill.

    Args:
        ticker: Stock ticker (or use symbol).
        symbol: Alias for ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".
        strategy: One of "buy-and-hold", "mean-reversion", "momentum", "value".
        initial_capital: Starting capital in USD.
        strategy_params: Optional strategy-specific parameters dict.

    Returns:
        Backtest result dict, or error dict.
    """
    # Resolve ticker — accept either 'ticker' or 'symbol'
    resolved_ticker = ticker or symbol
    if not resolved_ticker:
        return {"error": "backtest_strategy requires 'ticker' or 'symbol'"}
    if not start_date or not end_date:
        return {"error": "backtest_strategy requires 'start_date' and 'end_date'"}

    # Resolve strategy name — normalise dict form {"name": ..., "params": ...}
    resolved_strategy = strategy
    resolved_params = strategy_params
    if isinstance(strategy, dict):
        resolved_strategy = strategy.get("name", "mean-reversion")
        if not resolved_params:
            resolved_params = strategy.get("params")

    if _backtest_strategy_raw is None:
        return {"error": "backtest_strategy skill not available"}
    try:
        return _backtest_strategy_raw(
            ticker=resolved_ticker,
            start_date=start_date,
            end_date=end_date,
            strategy=resolved_strategy,
            initial_capital=initial_capital,
            strategy_params=resolved_params,
            save_to_db=True,
        )
    except Exception as exc:
        logger.warning(f"[registry] backtest_strategy failed for {resolved_ticker}: {exc}")
        return {"error": str(exc)}


# ── DAO wrapper helpers ───────────────────────────────────────────────────────

def _df_to_records(df) -> list:
    """Convert a DataFrame to a list of native dicts. Returns [] if empty/None."""
    try:
        if df is None or (hasattr(df, "empty") and df.empty):
            return []
        return _to_native(df.to_dict("records"))
    except Exception:
        return []


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
        return check_data_availability_core(
            symbol=resolved_symbol,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
        )
    except Exception as exc:
        logger.warning(f"[registry] check_data_availability failed for {resolved_symbol}: {exc}")
        return {"error": str(exc)}


def _fetch_historical_data_wrapped(
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1Min",
    **kwargs,
) -> Dict:
    """Normalising wrapper around fetch_historical_data_core.

    Converts LLM-emitted timeframe aliases (e.g. "1d") to canonical form
    before calling the underlying skill.

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
    tf = _normalize_timeframe(timeframe, default="1Min")
    if tf != timeframe:
        logger.info(f"[registry] fetch_historical_data: normalised timeframe '{timeframe}' → '{tf}'")
    try:
        return fetch_historical_data_core(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            timeframe=tf,
        )
    except Exception as exc:
        logger.warning(f"[registry] fetch_historical_data failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_market_bars(symbol: str, start_date: str, end_date: str, timeframe: str = "1Day") -> list:
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


def _get_latest_price(symbol: str, timeframe: str = "1Day") -> dict:
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


def _get_precomputed_indicators(symbol: str, start_date: str, end_date: str, timeframe: str = "1Day") -> list:
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


def _get_latest_eod(symbol: str) -> dict:
    """Get the most recent EOD analyst summary for a symbol.

    Args:
        symbol: Stock ticker.

    Returns:
        EOD summary dict or error dict.
    """
    try:
        from src.common.dao import AnalystDAO
        dao = AnalystDAO()
        result = dao.get_latest_eod(symbol)
        dao.close()
        return _to_native(result) if result else {"error": f"No EOD summary found for {symbol}"}
    except Exception as exc:
        logger.warning(f"[registry] get_latest_eod failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_recent_eods(symbol: str, count: int = 5) -> list:
    """Get the N most recent EOD analyst summaries for a symbol.

    Args:
        symbol: Stock ticker.
        count: Number of summaries to return.

    Returns:
        List of EOD summary dicts.
    """
    try:
        from src.common.dao import AnalystDAO
        dao = AnalystDAO()
        result = dao.get_recent_eods(symbol, count=count)
        dao.close()
        return _to_native(result) if result else []
    except Exception as exc:
        logger.warning(f"[registry] get_recent_eods failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_analyst_symbols() -> list:
    """Get all symbols that have EOD analyst summaries.

    Returns:
        List of symbol strings.
    """
    try:
        from src.common.dao import AnalystDAO
        dao = AnalystDAO()
        result = dao.get_all_symbols()
        dao.close()
        return result or []
    except Exception as exc:
        logger.warning(f"[registry] get_analyst_symbols failed: {exc}")
        return {"error": str(exc)}


# ── StrategyDAO wrappers ──────────────────────────────────────────────────────

def _get_latest_signal(symbol: str, strategy_name: str) -> dict:
    """Get the most recent strategy signal for a symbol.

    Args:
        symbol: Stock ticker.
        strategy_name: Name of the strategy (e.g. "mean-reversion").

    Returns:
        Signal dict with action, confidence, timestamp or error dict.
    """
    try:
        from src.common.dao import StrategyDAO
        dao = StrategyDAO()
        result = dao.get_latest_signal(symbol, strategy_name)
        dao.close()
        return _to_native(result) if result else {"error": f"No signal found for {symbol}/{strategy_name}"}
    except Exception as exc:
        logger.warning(f"[registry] get_latest_signal failed for {symbol}: {exc}")
        return {"error": str(exc)}


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


def _get_backtest_returns(run_id: str) -> list:
    """Get daily returns series for a backtest run.

    Args:
        run_id: Backtest run UUID.

    Returns:
        List of {date, return} dicts or empty list.
    """
    try:
        from src.common.dao import BacktestDAO
        dao = BacktestDAO()
        series = dao.get_daily_returns(run_id)
        dao.close()
        if series is None or (hasattr(series, "empty") and series.empty):
            return []
        return _to_native([{"date": str(k), "return": v} for k, v in series.items()])
    except Exception as exc:
        logger.warning(f"[registry] get_backtest_returns failed for {run_id}: {exc}")
        return {"error": str(exc)}


# ── PortfolioDAO wrappers ─────────────────────────────────────────────────────

def _get_portfolio_snapshot() -> dict:
    """Get the most recent portfolio snapshot (equity, positions, P&L).

    Returns:
        Portfolio snapshot dict or error dict.
    """
    try:
        from src.common.dao import PortfolioDAO
        dao = PortfolioDAO()
        result = dao.get_latest_snapshot()
        dao.close()
        return _to_native(result) if result else {"error": "No portfolio snapshot found"}
    except Exception as exc:
        logger.warning(f"[registry] get_portfolio_snapshot failed: {exc}")
        return {"error": str(exc)}


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
    "get_portfolio_status":    get_portfolio_status_core,
    "get_positions_summary":   get_positions_summary_core,
    "check_portfolio_health":  check_portfolio_health_core,
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
    "get_latest_eod":          _get_latest_eod,
    "get_recent_eods":         _get_recent_eods,
    "get_analyst_symbols":     _get_analyst_symbols,
    # ── StrategyDAO ───────────────────────────────────────────────────────────
    "get_latest_signal":       _get_latest_signal,
    "get_recent_signals":      _get_recent_signals,
    "get_actionable_signals":  _get_actionable_signals,
    "get_strategy_performance": _get_strategy_performance,
    # ── BacktestDAO ───────────────────────────────────────────────────────────
    "get_backtest_run":        _get_backtest_run,
    "get_recent_backtest_runs": _get_recent_backtest_runs,
    "get_backtest_trades":     _get_backtest_trades,
    "get_backtest_performance": _get_backtest_performance,
    "get_backtest_returns":    _get_backtest_returns,
    # ── PortfolioDAO ──────────────────────────────────────────────────────────
    "get_portfolio_snapshot":  _get_portfolio_snapshot,
    "get_portfolio_snapshot_history": _get_portfolio_snapshot_history,
    "get_risk_parameters":     _get_risk_parameters,
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
                "timeframe": "str — default '1Day'",
                "lookback_days": "int — default 90",
            },
        },
        "calc_volatility_bands": {
            "description": "Compute Bollinger Bands (upper, middle, lower, bandwidth).",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Day'",
                "lookback_days": "int — default 90",
            },
        },
        "calc_volume_flow": {
            "description": "Compute OBV and volume trend indicators.",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Day'",
                "lookback_days": "int — default 90",
            },
        },
        "analyze_candle_structure": {
            "description": "Detect candlestick patterns (engulfing, doji, hammer, etc.).",
            "params": {
                "symbol": "str",
                "timeframe": "str — default '1Day'",
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
            "params": {"symbol": "str", "start_date": "str — YYYY-MM-DD", "end_date": "str — YYYY-MM-DD", "timeframe": "str — default '1Day'"},
        },
        "get_latest_price": {
            "description": "Get the most recent bar for a symbol (open/high/low/close/volume).",
            "params": {"symbol": "str", "timeframe": "str — default '1Day'"},
        },
        "get_precomputed_indicators": {
            "description": "Retrieve pre-computed technical indicators stored in DB.",
            "params": {"symbol": "str", "start_date": "str — YYYY-MM-DD", "end_date": "str — YYYY-MM-DD", "timeframe": "str — default '1Day'"},
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
        "get_latest_eod": {
            "description": "Get the most recent EOD analyst summary for a symbol.",
            "params": {"symbol": "str"},
        },
        "get_recent_eods": {
            "description": "Get the N most recent EOD analyst summaries for a symbol.",
            "params": {"symbol": "str", "count": "int — default 5"},
        },
        "get_analyst_symbols": {
            "description": "Get all symbols that have EOD analyst summaries.",
            "params": {},
        },
        # ── StrategyDAO ───────────────────────────────────────────────────────
        "get_latest_signal": {
            "description": "Get the most recent strategy signal (buy/sell/hold + confidence) for a symbol.",
            "params": {"symbol": "str", "strategy_name": "str"},
        },
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
        "get_backtest_returns": {
            "description": "Get daily returns series for a backtest run.",
            "params": {"run_id": "str"},
        },
        # ── PortfolioDAO ──────────────────────────────────────────────────────
        "get_portfolio_snapshot": {
            "description": "Get the most recent portfolio snapshot (equity, positions, unrealized P&L).",
            "params": {},
        },
        "get_portfolio_snapshot_history": {
            "description": "Get historical portfolio value snapshots for a date range.",
            "params": {"start_date": "str — YYYY-MM-DD", "end_date": "str — YYYY-MM-DD"},
        },
        "get_risk_parameters": {
            "description": "Get current portfolio risk parameters and thresholds.",
            "params": {},
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

    assert len(FUNCTION_REGISTRY) == 41, f"Expected 41 functions, got {len(FUNCTION_REGISTRY)}"
    print("\n[OK] All 41 functions registered")

    schema = get_registry_schema()
    assert len(schema) == 41, f"Expected 41 schema entries, got {len(schema)}"
    print("[OK] Registry schema returned")

    print("\n[ALL OK] registry/functions.py smoke test passed")
