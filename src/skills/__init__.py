"""Skills for trading operations and market data.

This package contains API integration functions for:
- Alpaca: Historical and real-time market data
- Alpha Vantage: Fundamental data and financial statements
"""

from .alpaca_skills import (
    fetch_historical_bars,
    fetch_historical_trades,
    subscribe_to_bars,
    fetch_all as fetch_all_alpaca,
)

from .alpha_vantage_skills import (
    fetch_company_overview,
    fetch_dividend_history,
    fetch_earnings_history,
    fetch_income_statement,
    fetch_balance_sheet,
    fetch_cash_flow,
    fetch_all as fetch_all_alpha_vantage,
)

__all__ = [
    # Alpaca functions
    "fetch_historical_bars",
    "fetch_historical_trades",
    "subscribe_to_bars",
    "fetch_all_alpaca",
    # Alpha Vantage functions
    "fetch_company_overview",
    "fetch_dividend_history",
    "fetch_earnings_history",
    "fetch_income_statement",
    "fetch_balance_sheet",
    "fetch_cash_flow",
    "fetch_all_alpha_vantage",
]
