"""Tests for database-backed stream handlers."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import asyncio
import os
from datetime import datetime
from unittest.mock import patch
from src.dao import AlpacaDAO


class MockTrade:
    """Mock Alpaca trade object."""
    def __init__(self):
        self.symbol = "TEST"
        self.timestamp = datetime.now()
        self.id = 123456789
        self.price = 150.50
        self.size = 100
        self.exchange = "Q"
        self.conditions = ["@"]
        self.tape = "C"


class MockBar:
    """Mock Alpaca bar object."""
    def __init__(self):
        self.symbol = "TEST"
        self.timestamp = datetime.now()
        self.open = 150.00
        self.high = 151.50
        self.low = 149.50
        self.close = 150.50
        self.volume = 1000000
        self.trade_count = 500
        self.vwap = 150.25


@pytest.fixture
def test_db(tmp_path):
    """Provide test database path and cleanup."""
    db_path = tmp_path / "test_stream_handlers.duckdb"

    yield str(db_path)

    # Cleanup handled by tmp_path fixture


@pytest.fixture
def mock_dao(test_db):
    """Create mock DAO with test database."""
    # Import handlers module
    import src.data_gatherer.db_stream_handlers as handlers

    # Create test DAO
    dao = AlpacaDAO(db_path=test_db)

    # Patch the module-level DAO getter using unittest.mock
    with patch.object(handlers, 'get_dao', return_value=dao):
        with patch.object(handlers, '_dao', dao):
            yield dao

    dao.close()


@pytest.mark.asyncio
async def test_get_dao():
    """Test DAO singleton creation."""
    from src.data_gatherer.db_stream_handlers import get_dao

    dao1 = get_dao()
    dao2 = get_dao()

    # Should return the same instance
    assert dao1 is dao2
    assert isinstance(dao1, AlpacaDAO)


@pytest.mark.asyncio
async def test_save_trade_to_db(test_db):
    """Test saving trade to database."""
    from src.data_gatherer.db_stream_handlers import save_trade_to_db
    import src.data_gatherer.db_stream_handlers as handlers

    mock_trade = MockTrade()

    # Create DAO for the handler to use
    save_dao = AlpacaDAO(db_path=test_db)
    
    # Patch the handler to use our test DAO
    with patch.object(handlers, 'get_dao', return_value=save_dao):
        # Save trade
        await save_trade_to_db(mock_trade)
    
    save_dao.close()

    # Verify it was saved by creating a NEW DAO instance to read from the DB
    verify_dao = AlpacaDAO(db_path=test_db)
    start = mock_trade.timestamp.replace(hour=0, minute=0, second=0)
    end = mock_trade.timestamp.replace(hour=23, minute=59, second=59)
    trades = verify_dao.get_trades("TEST", start=start, end=end)
    verify_dao.close()

    assert len(trades) >= 1
    assert trades.iloc[0]['trade_id'] == mock_trade.id


@pytest.mark.asyncio
async def test_save_bar_to_db(test_db):
    """Test saving bar to database."""
    from src.data_gatherer.db_stream_handlers import save_bar_to_db
    import src.data_gatherer.db_stream_handlers as handlers

    mock_bar = MockBar()

    # Create DAO for the handler to use
    save_dao = AlpacaDAO(db_path=test_db)
    
    # Patch the handler to use our test DAO
    with patch.object(handlers, 'get_dao', return_value=save_dao):
        # Save bar
        await save_bar_to_db(mock_bar, timeframe='1Min')
    
    save_dao.close()

    # Verify it was saved by creating a NEW DAO instance to read from the DB
    verify_dao = AlpacaDAO(db_path=test_db)
    start = mock_bar.timestamp.replace(hour=0, minute=0, second=0)
    end = mock_bar.timestamp.replace(hour=23, minute=59, second=59)
    bars = verify_dao.get_bars("TEST", start=start, end=end, timeframe='1Min')
    verify_dao.close()

    assert len(bars) >= 1
    assert bars.iloc[0]['open'] == mock_bar.open


@pytest.mark.asyncio
async def test_combined_trade_handler(test_db, caplog):
    """Test combined trade handler (print + save)."""
    from src.data_gatherer.db_stream_handlers import combined_trade_handler
    import src.data_gatherer.db_stream_handlers as handlers
    import logging

    # Set log level to capture INFO messages
    caplog.set_level(logging.INFO)

    mock_trade = MockTrade()

    # Create DAO for the handler to use
    save_dao = AlpacaDAO(db_path=test_db)
    
    # Patch the handler to use our test DAO
    with patch.object(handlers, 'get_dao', return_value=save_dao):
        # Call combined handler
        await combined_trade_handler(mock_trade)
    
    save_dao.close()

    # Check output was logged
    assert "[TRADE]" in caplog.text
    assert "TEST" in caplog.text

    # Verify it was saved by creating a NEW DAO instance
    verify_dao = AlpacaDAO(db_path=test_db)
    start = mock_trade.timestamp.replace(hour=0, minute=0, second=0)
    end = mock_trade.timestamp.replace(hour=23, minute=59, second=59)
    trades = verify_dao.get_trades("TEST", start=start, end=end)
    verify_dao.close()
    
    assert trades is not None, "get_trades returned None"
    assert len(trades) >= 1


@pytest.mark.asyncio
async def test_combined_bar_handler(test_db, caplog):
    """Test combined bar handler (print + save)."""
    from src.data_gatherer.db_stream_handlers import combined_bar_handler
    import src.data_gatherer.db_stream_handlers as handlers
    import logging

    # Set log level to capture INFO messages
    caplog.set_level(logging.INFO)

    mock_bar = MockBar()

    # Create DAO for the handler to use
    save_dao = AlpacaDAO(db_path=test_db)
    
    # Patch the handler to use our test DAO
    with patch.object(handlers, 'get_dao', return_value=save_dao):
        # Call combined handler
        await combined_bar_handler(mock_bar, timeframe='1Min')
    
    save_dao.close()

    # Check output was logged
    assert "[BAR]" in caplog.text
    assert "TEST" in caplog.text

    # Verify it was saved by creating a NEW DAO instance
    verify_dao = AlpacaDAO(db_path=test_db)
    start = mock_bar.timestamp.replace(hour=0, minute=0, second=0)
    end = mock_bar.timestamp.replace(hour=23, minute=59, second=59)
    bars = verify_dao.get_bars("TEST", start=start, end=end, timeframe='1Min')
    verify_dao.close()
    
    assert len(bars) >= 1
