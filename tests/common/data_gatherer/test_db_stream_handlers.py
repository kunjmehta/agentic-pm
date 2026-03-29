"""Tests for database-backed stream handlers."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import asyncio
import os
from datetime import datetime
from unittest.mock import patch
from src.common.dao import AlpacaDAO


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
def test_db():
    """Provide test database path and cleanup."""
    db_path = "data/test_stream_handlers.duckdb"

    yield db_path

    # Cleanup
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass  # File may be locked


@pytest.fixture
def mock_dao(test_db):
    """Create mock DAO with test database."""
    # Import handlers module
    import src.common.data_gatherer.db_stream_handlers as handlers

    # Create test DAO
    dao = AlpacaDAO(db_path=test_db)

    # Patch the module-level DAO getter
    original_get_dao = handlers.get_dao
    handlers._dao = dao
    handlers.get_dao = lambda: dao

    yield dao

    # Restore
    handlers.get_dao = original_get_dao
    handlers._dao = None
    dao.close()


@pytest.mark.asyncio
async def test_get_dao():
    """Test DAO singleton creation."""
    from src.common.data_gatherer.db_stream_handlers import get_dao

    dao1 = get_dao()
    dao2 = get_dao()

    # Should return the same instance
    assert dao1 is dao2
    assert isinstance(dao1, AlpacaDAO)


@pytest.mark.asyncio
async def test_save_trade_to_db(mock_dao):
    """Test saving trade to database."""
    from src.common.data_gatherer.db_stream_handlers import save_trade_to_db

    mock_trade = MockTrade()

    # Save trade
    await save_trade_to_db(mock_trade)

    # Verify it was saved
    start = mock_trade.timestamp.replace(hour=0, minute=0, second=0)
    end = mock_trade.timestamp.replace(hour=23, minute=59, second=59)
    trades = mock_dao.get_trades("TEST", start=start, end=end)

    assert len(trades) >= 1
    assert trades.iloc[0]['trade_id'] == mock_trade.id


@pytest.mark.asyncio
async def test_save_bar_to_db(mock_dao):
    """Test saving bar to database."""
    from src.common.data_gatherer.db_stream_handlers import save_bar_to_db

    mock_bar = MockBar()

    # Save bar
    await save_bar_to_db(mock_bar, timeframe='1Min')

    # Verify it was saved
    start = mock_bar.timestamp.replace(hour=0, minute=0, second=0)
    end = mock_bar.timestamp.replace(hour=23, minute=59, second=59)
    bars = mock_dao.get_bars("TEST", start=start, end=end, timeframe='1Min')

    assert len(bars) >= 1
    assert bars.iloc[0]['open'] == mock_bar.open


@pytest.mark.asyncio
async def test_combined_trade_handler(mock_dao, capsys):
    """Test combined trade handler (print + save)."""
    from src.common.data_gatherer.db_stream_handlers import combined_trade_handler

    mock_trade = MockTrade()

    # Call combined handler
    await combined_trade_handler(mock_trade)

    # Check output was printed
    captured = capsys.readouterr()
    assert "[TRADE]" in captured.out
    assert "TEST" in captured.out

    # Verify it was saved to DB
    start = mock_trade.timestamp.replace(hour=0, minute=0, second=0)
    end = mock_trade.timestamp.replace(hour=23, minute=59, second=59)
    trades = mock_dao.get_trades("TEST", start=start, end=end)
    assert len(trades) >= 1


@pytest.mark.asyncio
async def test_combined_bar_handler(mock_dao, capsys):
    """Test combined bar handler (print + save)."""
    from src.common.data_gatherer.db_stream_handlers import combined_bar_handler

    mock_bar = MockBar()

    # Call combined handler
    await combined_bar_handler(mock_bar, timeframe='1Min')

    # Check output was printed
    captured = capsys.readouterr()
    assert "[BAR]" in captured.out
    assert "TEST" in captured.out

    # Verify it was saved to DB
    start = mock_bar.timestamp.replace(hour=0, minute=0, second=0)
    end = mock_bar.timestamp.replace(hour=23, minute=59, second=59)
    bars = mock_dao.get_bars("TEST", start=start, end=end, timeframe='1Min')
    assert len(bars) >= 1
