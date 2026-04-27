"""Data Access Objects for the Agentic Portfolio Manager.

This module provides DAO classes for database operations:
- BaseDAO: Base class with common database operations
- AlphaVantageDAO: Fundamental data from Alpha Vantage API
- AlpacaDAO: Market data from Alpaca API
- AnalysisDAO: EOD analyst summaries + strategy signal results (analysis.duckdb)
- PortfolioDAO: Portfolio snapshots, agent interactions, risk parameters
- BacktestDAO: Backtest simulation runs, trades, performance
- OrdersDAO: Live order submissions and fill tracking
"""

from .base_dao import BaseDAO
from .alpha_vantage_dao import AlphaVantageDAO
from .alpaca_dao import AlpacaDAO
from .analysis_dao import AnalysisDAO
from .portfolio_dao import PortfolioDAO
from .backtest_dao import BacktestDAO
from .orders_dao import OrdersDAO

__all__ = [
    'BaseDAO',
    'AlphaVantageDAO',
    'AlpacaDAO',
    'AnalysisDAO',
    'PortfolioDAO',
    'BacktestDAO',
    'OrdersDAO',
]
