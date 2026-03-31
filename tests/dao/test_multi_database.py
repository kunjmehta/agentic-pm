"""Unit tests for multi-database separation.

Tests that each DAO uses the correct database file and that databases
are properly isolated.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import tempfile
import shutil
from datetime import datetime
import pandas as pd

from src.dao.base_dao import BaseDAO
from src.dao.alpaca_dao import AlpacaDAO
from src.dao.alpha_vantage_dao import AlphaVantageDAO
from src.dao.portfolio_dao import PortfolioDAO
from src.dao.analyst_dao import AnalystDAO
from src.dao.strategy_dao import StrategyDAO
from src.dao.backtest_dao import BacktestDAO


class TestMultiDatabase:
    """Test suite for multi-database architecture."""

    @pytest.fixture(scope="function")
    def temp_dir(self):
        """Create temporary directory for test databases."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # Cleanup after test
        shutil.rmtree(temp_dir, ignore_errors=True)

    # ========================================================================
    # BaseDAO DB Type Mapping Tests
    # ========================================================================

    def test_base_dao_file_map(self):
        """Test that BaseDAO has correct file mappings."""
        assert 'market' in BaseDAO.DB_FILE_MAP
        assert 'portfolio' in BaseDAO.DB_FILE_MAP
        assert 'analysis' in BaseDAO.DB_FILE_MAP
        assert 'backtest' in BaseDAO.DB_FILE_MAP

        assert BaseDAO.DB_FILE_MAP['market'] == 'data/market_data.duckdb'
        assert BaseDAO.DB_FILE_MAP['portfolio'] == 'data/portfolio.duckdb'
        assert BaseDAO.DB_FILE_MAP['analysis'] == 'data/analysis.duckdb'
        assert BaseDAO.DB_FILE_MAP['backtest'] == 'data/backtest.duckdb'

    def test_base_dao_with_db_type(self, temp_dir):
        """Test BaseDAO initialization with db_type parameter."""
        dao = BaseDAO(db_type='market')

        # Should use market database path
        assert 'market_data.duckdb' in dao.db_path

        dao.close()

    def test_base_dao_with_explicit_path(self, temp_dir):
        """Test BaseDAO initialization with explicit path (overrides db_type)."""
        custom_path = f"{temp_dir}/custom.duckdb"
        dao = BaseDAO(db_path=custom_path, db_type='market')

        # Explicit path should override db_type
        assert custom_path in dao.db_path

        dao.close()

    def test_base_dao_priority_order(self, temp_dir):
        """Test priority order: explicit path > db_type > config > default."""
        # 1. Explicit path has highest priority
        custom_path = f"{temp_dir}/custom.duckdb"
        dao1 = BaseDAO(db_path=custom_path)
        assert custom_path in dao1.db_path
        dao1.close()

        # 2. db_type is second priority
        dao2 = BaseDAO(db_type='market')
        assert 'market_data.duckdb' in dao2.db_path
        dao2.close()

    # ========================================================================
    # DAO Database Assignment Tests
    # ========================================================================

    def test_alpaca_dao_uses_market_db(self):
        """Test that AlpacaDAO uses market_data.duckdb."""
        dao = AlpacaDAO()

        assert 'market_data.duckdb' in dao.db_path

        dao.close()

    def test_alpha_vantage_dao_uses_market_db(self):
        """Test that AlphaVantageDAO uses market_data.duckdb."""
        dao = AlphaVantageDAO()

        assert 'market_data.duckdb' in dao.db_path

        dao.close()

    def test_portfolio_dao_uses_portfolio_db(self):
        """Test that PortfolioDAO uses portfolio.duckdb."""
        dao = PortfolioDAO()

        assert 'portfolio.duckdb' in dao.db_path

        dao.close()

    def test_analyst_dao_uses_analysis_db(self):
        """Test that AnalystDAO uses analysis.duckdb."""
        dao = AnalystDAO()

        assert 'analysis.duckdb' in dao.db_path

        dao.close()

    def test_strategy_dao_uses_analysis_db(self):
        """Test that StrategyDAO uses analysis.duckdb."""
        dao = StrategyDAO()

        assert 'analysis.duckdb' in dao.db_path

        dao.close()

    def test_backtest_dao_uses_backtest_db(self):
        """Test that BacktestDAO uses backtest.duckdb."""
        dao = BacktestDAO()

        assert 'backtest.duckdb' in dao.db_path

        dao.close()

    # ========================================================================
    # Database Isolation Tests
    # ========================================================================

    def test_different_daos_use_different_files(self):
        """Test that different DAOs use different database files."""
        alpaca_dao = AlpacaDAO()
        portfolio_dao = PortfolioDAO()
        backtest_dao = BacktestDAO()

        # All should have different paths
        assert alpaca_dao.db_path != portfolio_dao.db_path
        assert alpaca_dao.db_path != backtest_dao.db_path
        assert portfolio_dao.db_path != backtest_dao.db_path

        alpaca_dao.close()
        portfolio_dao.close()
        backtest_dao.close()

    def test_database_isolation_writes(self, temp_dir):
        """Test that writes to different databases are isolated."""
        # Create DAOs with custom paths in temp directory
        market_path = f"{temp_dir}/market.duckdb"
        portfolio_path = f"{temp_dir}/portfolio.duckdb"

        market_dao = BaseDAO(db_path=market_path)
        portfolio_dao = BaseDAO(db_path=portfolio_path)

        # Create a test table in market database
        market_dao.execute("""
            CREATE TABLE test_market (
                id INTEGER,
                value VARCHAR
            )
        """)

        # Create a different table in portfolio database
        portfolio_dao.execute("""
            CREATE TABLE test_portfolio (
                id INTEGER,
                name VARCHAR
            )
        """)

        # Verify tables exist in correct databases
        market_tables = market_dao.fetch_df("SELECT name FROM sqlite_master WHERE type='table'")
        portfolio_tables = portfolio_dao.fetch_df("SELECT name FROM sqlite_master WHERE type='table'")

        # Market DB should have test_market, not test_portfolio
        assert 'test_market' in market_tables['name'].values
        assert 'test_portfolio' not in market_tables['name'].values

        # Portfolio DB should have test_portfolio, not test_market
        assert 'test_portfolio' in portfolio_tables['name'].values
        assert 'test_market' not in portfolio_tables['name'].values

        market_dao.close()
        portfolio_dao.close()

    # ========================================================================
    # Concurrent Access Tests
    # ========================================================================

    def test_concurrent_writes_to_different_databases(self, temp_dir):
        """Test that concurrent writes to different databases don't conflict."""
        import threading

        market_path = f"{temp_dir}/market.duckdb"
        portfolio_path = f"{temp_dir}/portfolio.duckdb"

        market_dao = BaseDAO(db_path=market_path)
        portfolio_dao = BaseDAO(db_path=portfolio_path)

        # Create test tables
        market_dao.execute("CREATE TABLE test (id INTEGER)")
        portfolio_dao.execute("CREATE TABLE test (id INTEGER)")

        errors = []

        def write_to_market(count):
            try:
                for i in range(count):
                    market_dao.execute(f"INSERT INTO test VALUES ({i})")
            except Exception as e:
                errors.append(('market', str(e)))

        def write_to_portfolio(count):
            try:
                for i in range(count):
                    portfolio_dao.execute(f"INSERT INTO test VALUES ({i + 1000})")
            except Exception as e:
                errors.append(('portfolio', str(e)))

        # Run concurrent writes
        thread1 = threading.Thread(target=write_to_market, args=(50,))
        thread2 = threading.Thread(target=write_to_portfolio, args=(50,))

        thread1.start()
        thread2.start()

        thread1.join()
        thread2.join()

        # No errors should occur
        assert len(errors) == 0

        # Verify data in each database
        market_count = market_dao.fetch_one("SELECT COUNT(*) as count FROM test")['count']
        portfolio_count = portfolio_dao.fetch_one("SELECT COUNT(*) as count FROM test")['count']

        assert market_count == 50
        assert portfolio_count == 50

        market_dao.close()
        portfolio_dao.close()

    # ========================================================================
    # Override Tests
    # ========================================================================

    def test_dao_can_override_default_path(self, temp_dir):
        """Test that DAOs can override default database path."""
        custom_path = f"{temp_dir}/custom_market.duckdb"

        dao = AlpacaDAO(db_path=custom_path)

        # Should use custom path, not default market_data.duckdb
        assert custom_path in dao.db_path

        dao.close()

    # ========================================================================
    # Schema Initialization Tests
    # ========================================================================

    def test_each_dao_initializes_own_schema(self):
        """Test that each DAO initializes its own schema correctly."""
        # AlpacaDAO should have market data tables
        alpaca_dao = AlpacaDAO()
        assert alpaca_dao.table_exists('market_bars')
        assert alpaca_dao.table_exists('watchlist')
        alpaca_dao.close()

        # PortfolioDAO should have portfolio tables
        portfolio_dao = PortfolioDAO()
        assert portfolio_dao.table_exists('portfolio_snapshots')
        portfolio_dao.close()

        # BacktestDAO should have backtest tables
        backtest_dao = BacktestDAO()
        assert backtest_dao.table_exists('backtest_runs')
        backtest_dao.close()

    def test_schemas_dont_interfere(self):
        """Test that schemas in different databases don't interfere."""
        alpaca_dao = AlpacaDAO()
        portfolio_dao = PortfolioDAO()

        # Market DB should not have portfolio tables
        assert not alpaca_dao.table_exists('portfolio_snapshots')

        # Portfolio DB should not have market tables
        assert not portfolio_dao.table_exists('market_bars')

        alpaca_dao.close()
        portfolio_dao.close()

    # ========================================================================
    # Error Handling Tests
    # ========================================================================

    def test_invalid_db_type(self):
        """Test handling of invalid db_type."""
        dao = BaseDAO(db_type='invalid_type')

        # Should fall back to default path
        assert 'portfolio.duckdb' in dao.db_path

        dao.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
