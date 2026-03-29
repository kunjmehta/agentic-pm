"""Tests for BacktestDAO."""

import pytest
from datetime import date, datetime
from src.common.dao.backtest_dao import BacktestDAO


@pytest.fixture
def dao():
    """Create BacktestDAO instance with in-memory database for testing."""
    return BacktestDAO(db_path=":memory:")


def test_create_run(dao):
    """Test creating a backtest run."""
    run_id = dao.create_run(
        strategy_name="test-strategy",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        initial_capital=100000.0,
        symbol="AAPL",
        parameters={"window": 20}
    )
    assert run_id is not None
    assert len(run_id) > 0


def test_get_run(dao):
    """Test retrieving a backtest run."""
    # Create run first
    run_id = dao.create_run(
        strategy_name="test-strategy",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        initial_capital=100000.0
    )

    # Retrieve it
    run = dao.get_run(run_id)
    assert run is not None
    assert run['strategy_name'] == 'test-strategy'
    assert run['status'] == 'running'


def test_save_and_close_trade(dao):
    """Test saving and closing a trade."""
    # Create run first
    run_id = dao.create_run(
        strategy_name="test",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 1),
        initial_capital=100000.0
    )

    # Save trade
    trade_id = dao.save_trade(
        run_id=run_id,
        symbol="AAPL",
        entry_date=date(2024, 1, 1),
        entry_time=datetime(2024, 1, 1, 10, 0),
        entry_price=150.0,
        quantity=100,
        side="long",
        entry_signal={"rsi": 30}
    )

    assert trade_id is not None

    # Close trade
    dao.close_trade(
        trade_id=trade_id,
        exit_date=date(2024, 1, 1),
        exit_time=datetime(2024, 1, 1, 15, 0),
        exit_price=155.0,
        exit_reason="take_profit"
    )

    # Verify P&L calculated
    trades = dao.get_trades_for_run(run_id)
    assert len(trades) == 1
    assert trades.iloc[0]['pnl'] == 500.0  # (155-150) * 100


def test_save_daily_performance(dao):
    """Test saving daily performance."""
    run_id = dao.create_run(
        strategy_name="test",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 1),
        initial_capital=100000.0
    )

    rows = dao.save_daily_performance(
        run_id=run_id,
        date=date(2024, 1, 1),
        equity=101000.0,
        cash=50000.0,
        positions_value=51000.0,
        daily_pnl=1000.0,
        daily_return_pct=1.0
    )

    assert rows == 1

    # Retrieve performance
    perf = dao.get_performance_history(run_id)
    assert len(perf) == 1
    assert perf.iloc[0]['equity'] == 101000.0


def test_mark_run_completed(dao):
    """Test marking run as completed."""
    run_id = dao.create_run(
        strategy_name="test",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 1),
        initial_capital=100000.0
    )

    dao.mark_run_completed(run_id)

    run = dao.get_run(run_id)
    assert run['status'] == 'completed'
    assert run['completed_at'] is not None
