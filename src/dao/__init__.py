"""Data Access Objects for the Agentic Portfolio Manager.

This module provides DAO classes for database operations:
- BaseDAO: Base class with common database operations
- AlphaVantageDAO: Fundamental data from Alpha Vantage API
- AlpacaDAO: Market data from Alpaca API

Usage:
    from src.dao import AlphaVantageDAO, AlpacaDAO

    # Alpha Vantage fundamentals
    av_dao = AlphaVantageDAO()
    av_dao.save_company_overview('AAPL', overview_data)
    av_dao.save_dividends('AAPL', dividends_df)

    # Alpaca market data
    alpaca_dao = AlpacaDAO()
    alpaca_dao.add_to_watchlist('AAPL')
    alpaca_dao.save_bars(bars_df, timeframe='1Min')
"""

from .base_dao import BaseDAO
from .alpha_vantage_dao import AlphaVantageDAO
from .alpaca_dao import AlpacaDAO

__all__ = [
    'BaseDAO',
    'AlphaVantageDAO',
    'AlpacaDAO',
]
