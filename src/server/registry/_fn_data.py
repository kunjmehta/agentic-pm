"""Market data and DAO query registry functions.

Covers:
  - AlpacaDAO: market bars, latest price, indicators, tick trades, trade count, intraday stats, watchlist
  - AlphaVantageDAO: fundamentals, dividends, earnings, income statement, balance sheet, cash flow
  - AnalysisDAO: EOD summaries, recent signals, actionable signals, strategy performance
  - BacktestDAO: backtest runs, trades, performance history
  - PortfolioDAO: snapshot history, risk parameters
"""

import sys
from pathlib import Path
from typing import Dict, Optional

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.utils.container import (
    get_alpaca_dao,
    get_alpha_vantage_dao,
    get_analysis_dao,
    get_backtest_dao,
    get_portfolio_dao,
)
from src.common.utils import get_logger
from src.server.registry._fn_helpers import _to_native, _df_to_records

logger = get_logger(__name__)


# ── AlpacaDAO: bars and market data ───────────────────────────────────────────


def _get_market_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1Min",
    **kwargs,
) -> list:
    """Fetch OHLCV bars for a symbol; auto-fetches from Alpaca API if not in DB.

    A single call covers both ensuring data is present and returning the actual
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

        _TF_MAP = {"1d": "1Day", "1day": "1Day", "1h": "1Hour", "1hour": "1Hour",
                   "1m": "1Min", "1min": "1Min"}
        tf = _TF_MAP.get(timeframe.lower(), timeframe)

        df = get_alpaca_dao().get_bars(
            symbol, _dt.fromisoformat(start_date), _dt.fromisoformat(end_date), tf
        )

        if df.empty:
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

        symbol = symbol.strip().upper()
        dao = get_alpaca_dao()

        try:
            now = _dt.now()
            df_live = dao.get_recent_trades(
                symbol, start=now - _td(hours=1), end=now, limit=None
            )
            if not df_live.empty:
                last = df_live.iloc[-1]
                return {
                    "symbol": symbol,
                    "close": float(last["price"]),
                    "source": "live_trades",
                    "timestamp": str(last["timestamp"]),
                }
        except Exception:
            pass

        result = dao.get_latest_bar(symbol, timeframe)
        if result:
            result = _to_native(result)
            result.setdefault("source", "bar")
            return result
        return {"error": f"No price data found for {symbol}"}
    except Exception as exc:
        logger.warning(f"[registry] get_latest_price failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_precomputed_indicators(
    symbol: str, start_date: str, end_date: str, timeframe: str = "1Min"
) -> list:
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
        df = get_alpaca_dao().get_computed_indicators(
            symbol, _dt.fromisoformat(start_date), _dt.fromisoformat(end_date), timeframe
        )
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_precomputed_indicators failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_tick_trades(
    symbol: str, start_date: str, end_date: str, limit: int = 1000
) -> list:
    """Retrieve tick-level trades for a symbol across live and historical tables.

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
        df = get_alpaca_dao().get_recent_trades(
            symbol, _dt.fromisoformat(start_date), _dt.fromisoformat(end_date), limit=limit
        )
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_tick_trades failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_trade_count(symbol: str, start_date: str, end_date: str) -> dict:
    """Get deduplicated trade count for a symbol across live and historical tables.

    Args:
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".

    Returns:
        Dict with trade_count key.
    """
    try:
        from datetime import datetime as _dt
        count = get_alpaca_dao().get_recent_trade_count(
            symbol, _dt.fromisoformat(start_date), _dt.fromisoformat(end_date)
        )
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
        result = get_alpaca_dao().calculate_intraday_stats(symbol, _date.fromisoformat(date))
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
        result = get_alpaca_dao().get_watchlist(active_only=True)
        return result or []
    except Exception as exc:
        logger.warning(f"[registry] get_watchlist failed: {exc}")
        return {"error": str(exc)}


# ── AlphaVantageDAO ────────────────────────────────────────────────────────────


def _get_company_fundamentals(symbol: str) -> dict:
    """Retrieve company overview: PE ratio, market cap, sector, EPS, 52-week range.

    Args:
        symbol: Stock ticker.

    Returns:
        Company overview dict or error dict.
    """
    try:
        result = get_alpha_vantage_dao().get_company_overview(symbol)
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
        df = get_alpha_vantage_dao().get_dividends(symbol, limit=limit)
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
        df = get_alpha_vantage_dao().get_earnings(symbol, quarterly=quarterly, limit=limit)
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
        df = get_alpha_vantage_dao().get_income_statement(symbol, quarterly=quarterly, limit=limit)
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
        df = get_alpha_vantage_dao().get_balance_sheet(symbol, quarterly=quarterly, limit=limit)
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
        df = get_alpha_vantage_dao().get_cash_flow(symbol, quarterly=quarterly, limit=limit)
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
        df = get_alpha_vantage_dao().get_all_fundamentals()
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_all_fundamentals failed: {exc}")
        return {"error": str(exc)}


# ── AnalysisDAO ────────────────────────────────────────────────────────────────


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
        df = get_analysis_dao().get_eod_summaries(
            symbol, _date.fromisoformat(start_date), _date.fromisoformat(end_date)
        )
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_eod_summaries failed for {symbol}: {exc}")
        return {"error": str(exc)}


# ── AnalysisDAO ───────────────────────────────────────────────────────────────


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
        df = get_analysis_dao().get_recent_signals(symbol, strategy_name, limit=limit)
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_recent_signals failed for {symbol}: {exc}")
        return {"error": str(exc)}


def _get_actionable_signals(
    min_confidence: float = 0.7, action_filter: str = None
) -> list:
    """Get high-confidence actionable buy/sell signals from active strategies.

    Args:
        min_confidence: Minimum confidence threshold (0.0-1.0).
        action_filter: Optional filter: "buy", "sell", or None for all.

    Returns:
        List of actionable signal dicts.
    """
    try:
        df = get_analysis_dao().get_actionable_signals(
            min_confidence=min_confidence, action_filter=action_filter
        )
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
        result = get_analysis_dao().get_strategy_performance(strategy_name, days=days)
        return _to_native(result) if result else {"error": f"No performance data for {strategy_name}"}
    except Exception as exc:
        logger.warning(f"[registry] get_strategy_performance failed for {strategy_name}: {exc}")
        return {"error": str(exc)}


# ── BacktestDAO ───────────────────────────────────────────────────────────────


def _get_backtest_run(run_id: str) -> dict:
    """Get details of a specific backtest run.

    Args:
        run_id: Backtest run UUID.

    Returns:
        Run details dict or error dict.
    """
    try:
        result = get_backtest_dao().get_run(run_id)
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
        result = get_backtest_dao().get_recent_runs(strategy_name=strategy_name, limit=limit)
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
        df = get_backtest_dao().get_trades_for_run(run_id)
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
        df = get_backtest_dao().get_performance_history(run_id)
        return _df_to_records(df)
    except Exception as exc:
        logger.warning(f"[registry] get_backtest_performance failed for {run_id}: {exc}")
        return {"error": str(exc)}


# ── PortfolioDAO ──────────────────────────────────────────────────────────────


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
        df = get_portfolio_dao().get_snapshot_history(
            _date.fromisoformat(start_date), _date.fromisoformat(end_date)
        )
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
        result = get_portfolio_dao().get_risk_parameters()
        return _to_native(result) if result else {}
    except Exception as exc:
        logger.warning(f"[registry] get_risk_parameters failed: {exc}")
        return {"error": str(exc)}
