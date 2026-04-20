"""DAO for backtest simulation operations.

Handles backtest runs, simulated trades, and performance tracking.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import uuid
from datetime import datetime, date
from typing import Dict, List, Optional, Any
import pandas as pd

from src.common.dao.base_dao import BaseDAO
from src.common.utils import get_logger

logger = get_logger(__name__)


class BacktestDAO(BaseDAO):
    """Data access layer for backtest simulation data."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize BacktestDAO.

        Args:
            db_path: Path to DuckDB database file. If None, uses backtest.duckdb.
        """
        super().__init__(db_path=db_path, db_type='backtest')
        self._initialize_schema()

    def _initialize_schema(self):
        """Initialize backtest schema from schema file."""
        schema_path = Path("config/schema/backtest_schema.sql")
        if schema_path.exists():
            # Only execute if backtest_runs table doesn't exist
            self.execute_schema_file(str(schema_path), check_table="backtest_runs")
            logger.debug("Backtest schema check completed")
        else:
            logger.warning(f"Schema file not found: {schema_path}")

    # =========================================================================
    # Run Management
    # =========================================================================

    def create_run(
        self,
        strategy_name: str,
        start_date: date,
        end_date: date,
        initial_capital: float,
        symbol: Optional[str] = None,
        parameters: Optional[Dict] = None,
        run_id: Optional[str] = None
    ) -> str:
        """Create a new backtest run.

        Args:
            strategy_name: Name of strategy being tested (e.g., 'mean-reversion')
            start_date: Start date of backtest period
            end_date: End date of backtest period
            initial_capital: Starting capital for simulation
            symbol: Stock symbol (None for multi-symbol runs)
            parameters: Strategy parameters as dict
            run_id: Optional run ID (generates UUID if not provided)

        Returns:
            run_id: Unique identifier for the backtest run
        """
        if run_id is None:
            run_id = str(uuid.uuid4())

        # Use explicit INSERT to avoid column mismatch issues with defaults
        query = """
            INSERT INTO backtest_runs (
                run_id, strategy_name, symbol, start_date, end_date,
                initial_capital, strategy_parameters, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            run_id,
            strategy_name,
            symbol,
            start_date,
            end_date,
            initial_capital,
            json.dumps(parameters) if parameters else None,
            'running',
            datetime.now()
        )

        self.execute(query, params)
        logger.info(f"Created backtest run {run_id}: {strategy_name} on {symbol} from {start_date} to {end_date}")
        return run_id

    def update_run_performance(
        self,
        run_id: str,
        metrics: Dict[str, Any]
    ) -> None:
        """Update performance metrics for a backtest run.

        Args:
            run_id: Backtest run identifier
            metrics: Dict with performance metrics (final_capital, total_return_pct,
                     sharpe_ratio, max_drawdown_pct, win_rate, profit_factor,
                     total_trades, winning_trades, losing_trades, avg_win, avg_loss)
        """
        def _sanitize(v):
            """Replace non-finite floats (inf, -inf, nan) with None so DuckDB
            DECIMAL columns never receive an uncastable value."""
            if v is None:
                return None
            try:
                import math
                if isinstance(v, float) and not math.isfinite(v):
                    return None
            except Exception:
                pass
            return v

        set_clauses = []
        params = []

        for key, value in metrics.items():
            set_clauses.append(f"{key} = ?")
            params.append(_sanitize(value))

        if set_clauses:
            query = f"""
                UPDATE backtest_runs
                SET {', '.join(set_clauses)}
                WHERE run_id = ?
            """
            params.append(run_id)
            self.execute(query, tuple(params))
            logger.info(f"Updated performance metrics for run {run_id}")

    def mark_run_completed(self, run_id: str) -> None:
        """Mark a backtest run as completed.

        Args:
            run_id: Backtest run identifier
        """
        query = """
            UPDATE backtest_runs
            SET status = 'completed', completed_at = ?
            WHERE run_id = ?
        """
        self.execute(query, (datetime.now(), run_id))
        logger.info(f"Marked run {run_id} as completed")

    def mark_run_failed(self, run_id: str, error_msg: str) -> None:
        """Mark a backtest run as failed with error message.

        Args:
            run_id: Backtest run identifier
            error_msg: Error message describing failure
        """
        query = """
            UPDATE backtest_runs
            SET status = 'failed', error_message = ?, completed_at = ?
            WHERE run_id = ?
        """
        self.execute(query, (error_msg, datetime.now(), run_id))
        logger.error(f"Marked run {run_id} as failed: {error_msg}")

    def get_run(self, run_id: str) -> Optional[Dict]:
        """Get backtest run details.

        Args:
            run_id: Backtest run identifier

        Returns:
            Dict with run details or None if not found
        """
        query = "SELECT * FROM backtest_runs WHERE run_id = ?"
        result = self.fetch_one(query, (run_id,))

        if result and result.get('strategy_parameters'):
            # Parse JSON parameters
            result['strategy_parameters'] = json.loads(result['strategy_parameters'])

        return result

    def get_recent_runs(
        self,
        strategy_name: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """Get recent backtest runs.

        Args:
            strategy_name: Filter by strategy name (optional)
            limit: Maximum number of runs to return

        Returns:
            List of dicts with run details
        """
        if strategy_name:
            query = """
                SELECT * FROM backtest_runs
                WHERE strategy_name = ?
                ORDER BY created_at DESC
                LIMIT ?
            """
            params = (strategy_name, limit)
        else:
            query = """
                SELECT * FROM backtest_runs
                ORDER BY created_at DESC
                LIMIT ?
            """
            params = (limit,)

        results = self.fetch_all(query, params)

        # Parse JSON parameters
        for result in results:
            if result.get('strategy_parameters'):
                result['strategy_parameters'] = json.loads(result['strategy_parameters'])

        return results

    # =========================================================================
    # Trade Management
    # =========================================================================

    def save_trade(
        self,
        run_id: str,
        symbol: str,
        entry_date: date,
        entry_time: datetime,
        entry_price: float,
        quantity: int,
        side: str,
        entry_signal: Dict,
        action: str = "buy",
    ) -> int:
        """Save a simulated trade entry.

        Args:
            run_id: Backtest run identifier
            symbol: Stock symbol
            entry_date: Entry date
            entry_time: Entry timestamp
            entry_price: Entry price
            quantity: Number of shares
            side: Position direction — 'long' or 'short'
            entry_signal: Dict with signal indicators that triggered entry
            action: Trade action — 'buy', 'sell', 'short', or 'cover'.
                Defaults to ``'buy'``.

        Returns:
            trade_id: Database row ID for the trade
        """
        # Use explicit INSERT
        query = """
            INSERT INTO backtest_trades (
                run_id, symbol, entry_date, entry_time, entry_price,
                quantity, side, action, entry_signal, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            run_id,
            symbol,
            entry_date,
            entry_time,
            entry_price,
            quantity,
            side,
            action,
            json.dumps(entry_signal),
            datetime.now()
        )

        self.execute(query, params)

        # Get the trade_id of the just-inserted row
        query_id = """
            SELECT trade_id FROM backtest_trades
            WHERE run_id = ? AND entry_time = ?
            ORDER BY created_at DESC
            LIMIT 1
        """
        result = self.fetch_one(query_id, (run_id, entry_time))
        trade_id = result['trade_id'] if result else None

        logger.info(f"Saved trade entry: {symbol} {side} {quantity} @ ${entry_price}")
        return trade_id

    def close_trade(
        self,
        trade_id: int,
        exit_date: date,
        exit_time: datetime,
        exit_price: float,
        exit_reason: str
    ) -> None:
        """Close a simulated trade.

        Args:
            trade_id: Trade identifier
            exit_date: Exit date
            exit_time: Exit timestamp
            exit_price: Exit price
            exit_reason: Reason for exit (stop_loss, take_profit, signal_reversal, eod)
        """
        # First get the trade to calculate P&L
        query = "SELECT entry_price, quantity, side FROM backtest_trades WHERE trade_id = ?"
        trade = self.fetch_one(query, (trade_id,))

        if not trade:
            logger.warning(f"Trade {trade_id} not found")
            return

        # Convert Decimal to float for calculations
        entry_price = float(trade['entry_price'])
        quantity = int(trade['quantity'])
        side = trade['side']

        # Calculate P&L
        if side == 'long':
            pnl = (exit_price - entry_price) * quantity
        else:  # short
            pnl = (entry_price - exit_price) * quantity

        pnl_pct = (pnl / (entry_price * quantity)) * 100

        # Update trade
        update_query = """
            UPDATE backtest_trades
            SET exit_date = ?, exit_time = ?, exit_price = ?,
                pnl = ?, pnl_pct = ?, exit_reason = ?
            WHERE trade_id = ?
        """
        self.execute(update_query, (exit_date, exit_time, exit_price, pnl, pnl_pct, exit_reason, trade_id))
        logger.info(f"Closed trade {trade_id}: P&L ${pnl:.2f} ({pnl_pct:.2f}%)")

    def get_trades_for_run(self, run_id: str) -> pd.DataFrame:
        """Get all trades for a backtest run.

        Args:
            run_id: Backtest run identifier

        Returns:
            DataFrame with trade details
        """
        query = """
            SELECT * FROM backtest_trades
            WHERE run_id = ?
            ORDER BY entry_time
        """
        df = self.fetch_df(query, (run_id,))

        # Parse JSON entry signals
        if not df.empty and 'entry_signal' in df.columns:
            df['entry_signal'] = df['entry_signal'].apply(
                lambda x: json.loads(x) if x else None
            )

        return df

    # =========================================================================
    # Performance Data
    # =========================================================================

    def save_daily_performance(
        self,
        run_id: str,
        date: date,
        equity: float,
        cash: float,
        positions_value: float,
        daily_pnl: Optional[float] = None,
        daily_return_pct: Optional[float] = None,
        cumulative_return_pct: Optional[float] = None,
        drawdown_pct: Optional[float] = None,
        open_positions: int = 0
    ) -> int:
        """Save daily performance snapshot for a backtest run.

        Args:
            run_id: Backtest run identifier
            date: Date of snapshot
            equity: Total portfolio value
            cash: Available cash
            positions_value: Market value of open positions
            daily_pnl: Daily profit/loss
            daily_return_pct: Daily return percentage
            cumulative_return_pct: Cumulative return from start
            drawdown_pct: Drawdown from peak
            open_positions: Number of open positions

        Returns:
            Number of rows inserted/updated (always 1)
        """
        # Check if record exists
        check_query = "SELECT id FROM backtest_performance WHERE run_id = ? AND date = ?"
        existing = self.fetch_one(check_query, (run_id, date))

        if existing:
            # Update existing record
            query = """
                UPDATE backtest_performance
                SET equity = ?, cash = ?, positions_value = ?,
                    daily_pnl = ?, daily_return_pct = ?, cumulative_return_pct = ?,
                    drawdown_pct = ?, open_positions = ?
                WHERE run_id = ? AND date = ?
            """
            params = (
                equity, cash, positions_value, daily_pnl, daily_return_pct,
                cumulative_return_pct, drawdown_pct, open_positions, run_id, date
            )
        else:
            # Insert new record
            query = """
                INSERT INTO backtest_performance (
                    run_id, date, equity, cash, positions_value,
                    daily_pnl, daily_return_pct, cumulative_return_pct,
                    drawdown_pct, open_positions, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                run_id, date, equity, cash, positions_value, daily_pnl,
                daily_return_pct, cumulative_return_pct, drawdown_pct,
                open_positions, datetime.now()
            )

        self.execute(query, params)
        logger.debug(f"Saved performance for {run_id} on {date}: equity=${equity:,.2f}")
        return 1

    def get_performance_history(self, run_id: str) -> pd.DataFrame:
        """Get daily performance history for a backtest run.

        Args:
            run_id: Backtest run identifier

        Returns:
            DataFrame with daily performance snapshots
        """
        query = """
            SELECT * FROM backtest_performance
            WHERE run_id = ?
            ORDER BY date
        """
        return self.fetch_df(query, (run_id,))

    def get_daily_returns(self, run_id: str) -> pd.Series:
        """Get daily returns series for a backtest run.

        Args:
            run_id: Backtest run identifier

        Returns:
            Series with daily return percentages (as decimals, not percentages)
        """
        query = """
            SELECT date, daily_return_pct
            FROM backtest_performance
            WHERE run_id = ?
            ORDER BY date
        """
        df = self.fetch_df(query, (run_id,))

        if df.empty:
            return pd.Series(dtype=float)

        # Convert percentages to decimals
        df['daily_return_pct'] = df['daily_return_pct'] / 100.0
        return pd.Series(df['daily_return_pct'].values, index=pd.to_datetime(df['date']))