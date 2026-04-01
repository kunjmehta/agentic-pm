"""Data Access Objects for the Agentic Portfolio Manager.

This module provides DAO classes for database operations:
- BaseDAO: Base class with common database operations
- AlphaVantageDAO: Fundamental data from Alpha Vantage API
- AlpacaDAO: Market data from Alpaca API
- AnalystDAO: Quant Analyst EOD summaries (Phase 2)
- StrategyDAO: Trading strategy results and signals (Phase 2)
- PortfolioDAO: Portfolio snapshots, agent interactions, risk parameters (Phase 3)
- BacktestDAO: Backtest simulation runs, trades, performance (Phase 4)

Usage:
    from src.common.dao import AlphaVantageDAO, AlpacaDAO, AnalystDAO, StrategyDAO, PortfolioDAO, BacktestDAO


    # Alpha Vantage fundamentals
    av_dao = AlphaVantageDAO()
    av_dao.save_company_overview('AAPL', overview_data)
    av_dao.save_dividends('AAPL', dividends_df)

    # Alpaca market data
    alpaca_dao = AlpacaDAO()
    alpaca_dao.add_to_watchlist('AAPL')
    alpaca_dao.save_bars(bars_df, timeframe='1Min')

    # Analyst summaries
    analyst_dao = AnalystDAO()
    analyst_dao.save_eod_summary('AAPL', timestamp, indicators, summary, signals)

    # Strategy results
    strategy_dao = StrategyDAO()
    strategy_dao.save_strategy_result('AAPL', 'mean-reversion', price, stats, ...)

    # Backtest simulations
    backtest_dao = BacktestDAO()
    run_id = backtest_dao.create_run('mean-reversion', start_date, end_date, 100000.0)
    backtest_dao.save_trade(run_id, 'AAPL', entry_date, entry_time, 150.0, 100, 'long', {...})
"""

from .base_dao import BaseDAO
from .alpha_vantage_dao import AlphaVantageDAO
from .alpaca_dao import AlpacaDAO
from .analyst_dao import AnalystDAO
from .strategy_dao import StrategyDAO
from .portfolio_dao import PortfolioDAO
from .backtest_dao import BacktestDAO
from .orders_dao import OrdersDAO
from .reports_dao import ReportsDAO

__all__ = [
    'BaseDAO',
    'AlphaVantageDAO',
    'AlpacaDAO',
    'AnalystDAO',
    'StrategyDAO',
    'PortfolioDAO',
    'BacktestDAO',
    'OrdersDAO',
    'ReportsDAO',
]
