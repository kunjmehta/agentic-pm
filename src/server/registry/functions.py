"""Function registry for the semi-auto executor node.

Maps string function names (as output by LLM reasoning agents) to Python callables.

Implementation is split across focused sub-modules:
  _fn_helpers.py    — shared utilities (retry, bar fetching, output validation)
  _fn_quant.py      — quant indicators, day-trading and swing strategy wrappers, backtester
  _fn_portfolio.py  — portfolio core, backtester workflow, order execution wrappers
  _fn_data.py       — market data and DAO query wrappers (AlpacaDAO, AlphaVantage, Analyst, Strategy, Backtest, Portfolio)
  registry_schema.py — get_registry_schema for GET /v1/registry endpoint
"""

import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.utils import get_logger

# ── Sub-module imports ────────────────────────────────────────────────────────

from src.server.registry._fn_quant import (
    _calc_momentum_wrapped,
    _calc_volatility_wrapped,
    _calc_volume_wrapped,
    _analyze_candles_wrapped,
    _mean_reversion_analyze,
    _vwap_reversion_wrapped,
    _opening_range_breakout_wrapped,
    _rsi_divergence_wrapped,
    _momentum_burst_wrapped,
    _golden_cross_wrapped,
    _breakout_52w_wrapped,
    _mean_reversion_daily_wrapped,
    _earnings_drift_wrapped,
    _backtest_strategy,
)
from src.server.registry._fn_portfolio import (
    _check_data_availability_wrapped,
    _get_portfolio_status_wrapped,
    _get_positions_summary_wrapped,
    _check_portfolio_health_wrapped,
    _save_eod_snapshot_wrapped,
    _snapshot_worth_wrapped,
    _swap_positions_wrapped,
    _execute_order_wrapped,
    _close_position_wrapped,
    _scale_position_wrapped,
    _execute_strategy_signal_wrapped,
    _fetch_orders_wrapped,
    _place_market_order_wrapped,
    _place_limit_order_wrapped,
    _place_stop_order_wrapped,
    _place_stop_limit_order_wrapped,
    _cancel_order_wrapped,
    _cancel_all_orders_wrapped,
    _close_all_positions_wrapped,
)
from src.server.registry._fn_data import (
    _get_market_bars,
    _get_latest_price,
    _get_precomputed_indicators,
    _get_tick_trades,
    _get_trade_count,
    _get_intraday_stats,
    _get_watchlist,
    _get_company_fundamentals,
    _get_dividends,
    _get_earnings_history,
    _get_income_statement,
    _get_balance_sheet,
    _get_cash_flow,
    _get_all_fundamentals,
    _get_eod_summaries,
    _get_recent_signals,
    _get_actionable_signals,
    _get_strategy_performance,
    _get_backtest_run,
    _get_recent_backtest_runs,
    _get_backtest_trades,
    _get_backtest_performance,
    _get_portfolio_snapshot_history,
    _get_risk_parameters,
)
from src.server.registry.registry_schema import get_registry_schema  # noqa: F401 — re-exported

logger = get_logger(__name__)


# ── Registry ──────────────────────────────────────────────────────────────────

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
    "place_stop_order":        _place_stop_order_wrapped,
    "place_stop_limit_order":  _place_stop_limit_order_wrapped,
    "cancel_order":            _cancel_order_wrapped,
    "cancel_all_orders":       _cancel_all_orders_wrapped,
    "close_all_positions":     _close_all_positions_wrapped,
}

# Filter out None entries at load time so executor can detect unavailable functions
AVAILABLE_FUNCTIONS = {k: v for k, v in FUNCTION_REGISTRY.items() if v is not None}

# Maps each registered function to its access level for executor thread-pool routing.
# "read"  → safe to run in parallel read pool (no side effects)
# "write" → must run in serial write pool (mutates orders/positions/DB)
# Functions not listed default to "write" (conservative).
FUNCTION_ACCESS: Dict[str, str] = {
    # ── Read-only — portfolio ──────────────────────────────────────────────
    "get_portfolio_status":              "read",
    "get_positions_summary":             "read",
    "check_portfolio_health":            "read",
    "check_data_availability":           "read",
    # ── Read-only — quant indicators ──────────────────────────────────────
    "calc_momentum":                     "read",
    "calc_volatility_bands":             "read",
    "calc_volume_flow":                  "read",
    "analyze_candle_structure":          "read",
    "mean_reversion_analyze":            "read",
    # ── Read-only — strategy signal analysis (no DB writes) ───────────────
    "vwap_reversion_analyze":            "read",
    "opening_range_breakout_analyze":    "read",
    "rsi_divergence_analyze":            "read",
    "momentum_burst_analyze":            "read",
    "golden_cross_analyze":              "read",
    "breakout_52w_analyze":              "read",
    "mean_reversion_daily_analyze":      "read",
    "earnings_drift_analyze":            "read",
    # ── Read-only — backtester ────────────────────────────────────────────
    "backtest_strategy":                 "read",
    "snapshot_worth":                    "read",
    # ── Read-only — data queries ──────────────────────────────────────────
    "get_latest_price":                  "read",
    "get_precomputed_indicators":        "read",
    "get_tick_trades":                   "read",
    "get_trade_count":                   "read",
    "get_intraday_stats":                "read",
    "get_watchlist":                     "read",
    "get_company_fundamentals":          "read",
    "get_dividends":                     "read",
    "get_earnings_history":              "read",
    "get_income_statement":              "read",
    "get_balance_sheet":                 "read",
    "get_cash_flow":                     "read",
    "get_all_fundamentals":              "read",
    "get_eod_summaries":                 "read",
    "get_recent_signals":                "read",
    "get_actionable_signals":            "read",
    "get_strategy_performance":          "read",
    "get_backtest_run":                  "read",
    "get_recent_backtest_runs":          "read",
    "get_backtest_trades":               "read",
    "get_backtest_performance":          "read",
    "get_portfolio_snapshot_history":    "read",
    "get_risk_parameters":               "read",
    "fetch_orders":                      "read",
    # ── Write — DB writes and order execution ─────────────────────────────
    "get_market_bars":                   "write",  # fetches + writes bars to DB
    "fetch_historical_data":             "write",  # alias of get_market_bars
    "save_eod_snapshot":                 "write",
    "swap_positions":                    "write",
    "execute_order":                     "write",
    "close_position":                    "write",
    "scale_position":                    "write",
    "execute_strategy_signal":           "write",
    "place_market_order":                "write",
    "place_limit_order":                 "write",
    "place_stop_order":                  "write",
    "place_stop_limit_order":            "write",
    "cancel_order":                      "write",
    "cancel_all_orders":                 "write",
    "close_all_positions":               "write",
}


if __name__ == "__main__":
    """Smoke test: verify registry loads and all functions are callable."""
    print("=" * 60)
    print("functions.py Smoke Test")
    print("=" * 60)

    print(f"\nFUNCTION_REGISTRY: {len(FUNCTION_REGISTRY)} entries")
    print(f"AVAILABLE_FUNCTIONS: {len(AVAILABLE_FUNCTIONS)} available")
    print(f"FUNCTION_ACCESS: {len(FUNCTION_ACCESS)} access-level entries")

    schema = get_registry_schema()
    print(f"get_registry_schema: {len(schema)} functions documented")

    missing_access = [k for k in AVAILABLE_FUNCTIONS if k not in FUNCTION_ACCESS]
    if missing_access:
        print(f"\n[WARN] Functions missing from FUNCTION_ACCESS: {missing_access}")
    else:
        print("\n[OK] All available functions have access-level entries")

    print("\n[OK] functions.py smoke test complete")
