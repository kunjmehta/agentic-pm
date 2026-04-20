"""Registry schema for the GET /v1/registry API endpoint.

Returns a human-readable / LLM-readable description of every registered
function: what it does, what parameters it accepts, and any important notes
(e.g. REQUIRES HUMAN APPROVAL for write operations).
"""

import sys
from pathlib import Path
from typing import Any, Dict

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


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
                "snapshot_date": "str — YYYY-MM-DD",
                "end_date": "str — YYYY-MM-DD",
                "tickers": "dict — {symbol: {swap_to: str, quantity: int}}",
            },
        },
        # ── Order execution & strategy scaling ────────────────────────────────
        "execute_order": {
            "description": "Place a market or limit order via Alpaca. Preferred for direct single-symbol execution.",
            "params": {
                "symbol": "str",
                "qty": "float — number of shares (> 0)",
                "side": "str — 'buy' or 'sell'",
                "order_type": "str — 'market' (default) or 'limit'",
                "limit_price": "float — required for limit orders",
            },
            "note": "REQUIRES HUMAN APPROVAL — always present to the user before executing",
        },
        "close_position": {
            "description": "Liquidate the full open position for a symbol at market price.",
            "params": {"symbol": "str"},
            "note": "REQUIRES HUMAN APPROVAL — always present to the user before executing",
        },
        "scale_position": {
            "description": (
                "Resize an open (or new) position to a target percentage of total equity. "
                "Use target_pct=0.0 to fully close the position. "
                "Computes the buy/sell delta automatically."
            ),
            "params": {
                "symbol": "str",
                "target_pct": "float — target allocation as fraction of equity (e.g. 0.05 = 5%)",
                "order_type": "str — 'market' (default) or 'limit'",
                "limit_price": "float — required for limit orders",
            },
            "note": "REQUIRES HUMAN APPROVAL — always present to the user before executing",
        },
        "execute_strategy_signal": {
            "description": (
                "Translate a quant strategy signal (buy/sell/hold) into a live Alpaca order. "
                "Confidence score scales the position size relative to base_position_pct."
            ),
            "params": {
                "symbol": "str",
                "signal": "str — 'buy' | 'sell' | 'hold'",
                "confidence": "float — conviction score 0–1, default 1.0",
                "base_position_pct": "float — max allocation per position, default 0.05",
                "order_type": "str — 'market' (default) or 'limit'",
            },
            "note": "REQUIRES HUMAN APPROVAL — always present to the user before executing",
        },
        # ── Raw Alpaca order operations ────────────────────────────────────────
        "fetch_orders": {
            "description": "List orders from Alpaca with optional status and limit filters.",
            "params": {
                "status": "str — 'open' | 'closed' | 'all' (default 'all')",
                "limit": "int — max orders to return (default 100)",
            },
        },
        "place_market_order": {
            "description": "Place a market order for immediate execution at the best available price.",
            "params": {
                "symbol": "str",
                "qty": "float — number of shares (> 0)",
                "side": "str — 'buy' or 'sell'",
            },
            "note": "REQUIRES HUMAN APPROVAL",
        },
        "place_limit_order": {
            "description": "Place a limit order that executes only at the specified price or better.",
            "params": {
                "symbol": "str",
                "qty": "float — number of shares (> 0)",
                "side": "str — 'buy' or 'sell'",
                "limit_price": "float — price cap (buy) or floor (sell)",
                "time_in_force": "str — 'day' | 'gtc' | 'ioc' | 'fok' (default 'day')",
            },
            "note": "REQUIRES HUMAN APPROVAL",
        },
        "cancel_order": {
            "description": "Cancel a specific open order by its Alpaca UUID.",
            "params": {"order_id": "str — Alpaca order UUID"},
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
                "cancel_orders_first": "bool — cancel open orders before closing (default True)",
            },
            "note": "REQUIRES HUMAN APPROVAL",
        },
    }
