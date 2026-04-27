"""External API integrations for trading operations and market data.

This package contains API integration functions for:
- Alpaca: Historical and real-time market data (alpaca.py)
- Alpha Vantage: Fundamental data and financial statements (alpha_vantage.py)
- Alpaca Portfolio: Account, positions, orders (alpaca_portfolio.py)
"""

from src.common.external.alpaca import (
    fetch_historical_bars,
    fetch_historical_trades,
    fetch_all as fetch_all_alpaca,
)

from src.common.external.alpha_vantage import (
    fetch_company_overview,
    fetch_dividend_history,
    fetch_earnings_history,
    fetch_income_statement,
    fetch_balance_sheet,
    fetch_cash_flow,
    fetch_all as fetch_all_alpha_vantage,
)

__all__ = [
    # Alpaca market data
    "fetch_historical_bars",
    "fetch_historical_trades",
    "fetch_all_alpaca",
    # Alpha Vantage fundamentals
    "fetch_company_overview",
    "fetch_dividend_history",
    "fetch_earnings_history",
    "fetch_income_statement",
    "fetch_balance_sheet",
    "fetch_cash_flow",
    "fetch_all_alpha_vantage",
]
