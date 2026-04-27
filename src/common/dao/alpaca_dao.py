"""Data Access Object for Alpaca market data.

This module provides specialized DAO operations for storing and retrieving
Alpaca market data including historical bars (OHLCV) and trades.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import List, Optional
from datetime import datetime, date
import pandas as pd
from src.common.dao.base_dao import BaseDAO
from src.common.utils import get_logger


# Initialize logger
logger = get_logger(__name__)


class AlpacaDAO(BaseDAO):
    """DAO for Alpaca market data operations.

    Handles storage and retrieval of:
    - Watchlist (symbols being tracked)
    - Market bars (OHLCV data at various timeframes)
    - Historical trades (tick-level data)
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize AlpacaDAO.

        Args:
            db_path: Path to DuckDB database. If None, uses market_data.duckdb.
        """
        super().__init__(db_path=db_path, db_type='market')
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Ensure Alpaca schema exists in database."""
        schema_file = "config/schema/alpaca_schema.sql"
        try:
            # Only execute if market_bars table doesn't exist
            self.execute_schema_file(schema_file, check_table="market_bars")
            logger.debug("Alpaca schema check completed")
        except Exception as e:
            logger.warning(f"Schema initialization skipped: {str(e)}")

    # ========================================================================
    # Watchlist Operations
    # ========================================================================

    def add_to_watchlist(self, symbol: str, notes: Optional[str] = None) -> None:
        """Add symbol to watchlist.

        Args:
            symbol: Stock ticker symbol
            notes: Optional notes about why symbol is being tracked

        Raises:
            Exception: If addition fails
        """
        logger.info(f"Adding {symbol} to watchlist")

        try:
            query = """
                INSERT INTO watchlist (symbol, notes, active, added_date)
                VALUES (?, ?, TRUE, CURRENT_TIMESTAMP)
                ON CONFLICT (symbol) DO UPDATE SET
                    active = TRUE,
                    notes = COALESCE(excluded.notes, watchlist.notes)
            """
            self.execute(query, (symbol, notes))
            logger.info(f"Successfully added {symbol} to watchlist")

        except Exception as e:
            error_msg = f"Failed to add {symbol} to watchlist: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def remove_from_watchlist(self, symbol: str) -> None:
        """Remove symbol from watchlist (mark as inactive).

        Args:
            symbol: Stock ticker symbol
        """
        logger.info(f"Removing {symbol} from watchlist")
        query = "UPDATE watchlist SET active = FALSE WHERE symbol = ?"
        self.execute(query, (symbol,))

    def get_watchlist(self, active_only: bool = True) -> List[str]:
        """Get list of symbols in watchlist.

        Args:
            active_only: If True, return only active symbols

        Returns:
            List of ticker symbols
        """
        if active_only:
            query = "SELECT symbol FROM watchlist WHERE active = TRUE ORDER BY added_date DESC"
        else:
            query = "SELECT symbol FROM watchlist ORDER BY added_date DESC"

        results = self.fetch_all(query)
        return [r['symbol'] for r in results]

    def is_in_watchlist(self, symbol: str) -> bool:
        """Check if symbol is in active watchlist.

        Args:
            symbol: Stock ticker symbol

        Returns:
            True if symbol is in active watchlist
        """
        query = "SELECT COUNT(*) as count FROM watchlist WHERE symbol = ? AND active = TRUE"
        result = self.fetch_one(query, (symbol,))
        return result['count'] > 0 if result else False

    # ========================================================================
    # Market Bars Operations
    # ========================================================================

    def save_bars(self, df: pd.DataFrame, timeframe: str) -> int:
        """Save market bars data.

        Args:
            df: DataFrame with columns: symbol, timestamp, open, high, low,
                close, volume, trade_count, vwap
            timeframe: Timeframe string ('1Min', '5Min', '1Hour', '1Day')

        Returns:
            Number of rows saved

        Raises:
            Exception: If save fails
        """
        if df.empty:
            logger.info(f"No bars data to save for timeframe {timeframe}")
            return 0

        logger.info(f"Saving {len(df)} bars for timeframe {timeframe}")

        try:
            # Ensure timeframe column exists
            df = df.copy()
            if 'timeframe' not in df.columns:
                df['timeframe'] = timeframe

            # Ensure required columns exist
            required_cols = ['symbol', 'timestamp', 'timeframe', 'open', 'high',
                           'low', 'close', 'volume']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                raise ValueError(f"Missing required columns: {missing_cols}")

            # Convert timestamp to datetime if needed
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])

            # Select only columns that exist in the table
            table_cols = ['symbol', 'timestamp', 'timeframe', 'open', 'high', 'low',
                         'close', 'volume', 'trade_count', 'vwap']
            df = df[[col for col in table_cols if col in df.columns]]

            rows = self.upsert_df('market_bars', df,
                                 key_columns=['symbol', 'timestamp', 'timeframe'])
            logger.info(f"Successfully saved {rows} bars for timeframe {timeframe}")
            return rows

        except Exception as e:
            error_msg = f"Failed to save bars: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min"
    ) -> pd.DataFrame:
        """Retrieve market bars.

        Args:
            symbol: Stock ticker symbol
            start: Start timestamp
            end: End timestamp
            timeframe: Timeframe string

        Returns:
            DataFrame with market bars
        """
        query = """
            SELECT * FROM market_bars
            WHERE symbol = ?
              AND timeframe = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp ASC
        """
        return self.fetch_df(query, (symbol, timeframe, start, end))

    def get_latest_bar(self, symbol: str, timeframe: str = "1Day") -> Optional[dict]:
        """Get the most recent bar for a symbol.

        Args:
            symbol: Stock ticker symbol
            timeframe: Timeframe string

        Returns:
            Dictionary with bar data, or None if not found
        """
        query = """
            SELECT * FROM market_bars
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """
        return self.fetch_one(query, (symbol, timeframe))

    def delete_bars(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None
    ) -> None:
        """Delete bars for a symbol within a date range.

        Args:
            symbol: Stock ticker symbol
            start: Optional start timestamp
            end: Optional end timestamp
            timeframe: Optional timeframe filter
        """
        logger.info(f"Deleting bars for {symbol}")

        query = "DELETE FROM market_bars WHERE symbol = ?"
        params = [symbol]

        if timeframe:
            query += " AND timeframe = ?"
            params.append(timeframe)

        if start:
            query += " AND timestamp >= ?"
            params.append(start)

        if end:
            query += " AND timestamp <= ?"
            params.append(end)

        self.execute(query, tuple(params))

    # ========================================================================
    # Historical Trades Operations
    # ========================================================================

    def save_trades(self, df: pd.DataFrame) -> int:
        """Save historical trades data.

        Args:
            df: DataFrame with columns: symbol, timestamp, trade_id, price,
                size, exchange, conditions, tape

        Returns:
            Number of rows saved

        Raises:
            Exception: If save fails
        """
        if df.empty:
            logger.info("No trades data to save")
            return 0

        logger.info(f"Saving {len(df)} trades")

        try:
            # Ensure required columns exist
            required_cols = ['symbol', 'timestamp', 'price', 'size']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                raise ValueError(f"Missing required columns: {missing_cols}")

            # Convert timestamp to datetime if needed
            df = df.copy()
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])

            # Rename 'id' column to 'trade_id' if it exists
            if 'id' in df.columns and 'trade_id' not in df.columns:
                df = df.rename(columns={'id': 'trade_id'})

            # Select only columns that exist in the table
            table_cols = ['symbol', 'timestamp', 'trade_id', 'price', 'size',
                         'exchange', 'conditions', 'tape']
            df = df[[col for col in table_cols if col in df.columns]]

            rows = self.upsert_df('historical_trades', df,
                                 key_columns=['symbol', 'timestamp', 'trade_id'])
            logger.info(f"Successfully saved {rows} trades")
            return rows

        except Exception as e:
            error_msg = f"Failed to save trades: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def get_trades(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """Retrieve historical trades.

        Args:
            symbol: Stock ticker symbol
            start: Start timestamp
            end: End timestamp
            limit: Optional maximum number of trades to return

        Returns:
            DataFrame with trade data
        """
        query = """
            SELECT * FROM historical_trades
            WHERE symbol = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp ASC
        """

        if limit is not None:
            try:
                limit_int = int(limit)
            except (TypeError, ValueError):
                raise ValueError("limit must be an integer")  # Prevent SQL injection via LIMIT clause

            # Only apply LIMIT for positive integers; for zero/negative, behave like no limit.
            if limit_int > 0:
                query += f" LIMIT {limit_int}"

        return self.fetch_df(query, (symbol, start, end))

    def get_trade_count(self, symbol: str, start: datetime, end: datetime) -> int:
        """Get count of trades for a symbol in a time range.

        Args:
            symbol: Stock ticker symbol
            start: Start timestamp
            end: End timestamp

        Returns:
            Number of trades
        """
        query = """
            SELECT COUNT(*) as count FROM historical_trades
            WHERE symbol = ?
              AND timestamp >= ?
              AND timestamp <= ?
        """
        result = self.fetch_one(query, (symbol, start, end))
        return result['count'] if result else 0

    # ========================================================================
    # Recent Trades (live_trades ∪ historical_trades)
    # ========================================================================

    def get_recent_trades(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """Retrieve trades from both live_trades and historical_trades.

        Unions in-flight trade data (live_trades staging table) with the
        persistent historical archive for the given time window. Deduplicates
        on (symbol, timestamp, trade_id) so archived rows are not double-counted
        after an archival run.

        Args:
            symbol: Stock ticker symbol
            start: Start timestamp
            end: End timestamp
            limit: Optional maximum number of trades to return (applied after sort)

        Returns:
            DataFrame with trade data ordered by timestamp ASC
        """
        base_query = """
            SELECT symbol, timestamp, trade_id, price, size,
                   exchange, conditions, tape
            FROM (
                SELECT symbol, timestamp, trade_id, price, size,
                       exchange, conditions, tape
                FROM live_trades
                WHERE symbol = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                UNION ALL
                SELECT symbol, timestamp, trade_id, price, size,
                       exchange, conditions, tape
                FROM historical_trades
                WHERE symbol = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
            ) combined
            GROUP BY symbol, timestamp, trade_id, price, size, exchange, conditions, tape
            ORDER BY timestamp ASC
        """
        params = (symbol, start, end, symbol, start, end)

        if limit is not None:
            try:
                limit_int = int(limit)
            except (TypeError, ValueError):
                raise ValueError("limit must be an integer")
            if limit_int > 0:
                base_query += f" LIMIT {limit_int}"

        return self.fetch_df(base_query, params)

    def get_recent_trade_count(self, symbol: str, start: datetime, end: datetime) -> int:
        """Get deduplicated trade count across live_trades and historical_trades.

        Args:
            symbol: Stock ticker symbol
            start: Start timestamp
            end: End timestamp

        Returns:
            Number of distinct trades in the time range
        """
        query = """
            SELECT COUNT(*) as count FROM (
                SELECT trade_id FROM live_trades
                WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?
                UNION
                SELECT trade_id FROM historical_trades
                WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?
            ) deduped
        """
        result = self.fetch_one(query, (symbol, start, end, symbol, start, end))
        return result['count'] if result else 0

    def calculate_intraday_stats(self, symbol: str, date: date) -> dict:
        """Calculate intraday statistics from 1-minute bars.

        Args:
            symbol: Stock ticker symbol
            date: Trading date

        Returns:
            Dictionary with intraday stats
        """
        query = """
            SELECT
                symbol,
                COUNT(*) as bar_count,
                SUM(volume) as total_volume,
                SUM(trade_count) as total_trades,
                MAX(high) as day_high,
                MIN(low) as day_low,
                FIRST_VALUE(open) OVER (ORDER BY timestamp ASC) as day_open,
                LAST_VALUE(close) OVER (ORDER BY timestamp ASC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as day_close,
                SUM(vwap * volume) / SUM(volume) as avg_vwap
            FROM market_bars
            WHERE symbol = ?
              AND timeframe = '1Min'
              AND DATE(timestamp) = ?
            GROUP BY symbol
        """
        return self.fetch_one(query, (symbol, date))

    # ========================================================================
    # Live Trades Operations (Staging Table)
    # ========================================================================

    def save_live_trades(self, df: pd.DataFrame) -> int:
        """Save live trades to staging table.

        Args:
            df: DataFrame with columns: symbol, timestamp, trade_id, price,
                size, exchange, conditions, tape

        Returns:
            Number of rows saved

        Raises:
            Exception: If save fails
        """
        if df.empty:
            logger.info("No live trades to save")
            return 0

        logger.info(f"Saving {len(df)} live trades to staging table")

        try:
            # Ensure required columns exist
            required_cols = ['symbol', 'timestamp', 'price', 'size']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                raise ValueError(f"Missing required columns: {missing_cols}")

            # Convert timestamp to datetime if needed
            df = df.copy()
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])

            # Rename 'id' column to 'trade_id' if it exists
            if 'id' in df.columns and 'trade_id' not in df.columns:
                df = df.rename(columns={'id': 'trade_id'})

            # Select only columns that exist in the table
            table_cols = ['symbol', 'timestamp', 'trade_id', 'price', 'size',
                         'exchange', 'conditions', 'tape']
            df = df[[col for col in table_cols if col in df.columns]]

            rows = self.upsert_df('live_trades', df,
                                 key_columns=['symbol', 'timestamp', 'trade_id'])
            logger.info(f"Successfully saved {rows} live trades")
            return rows

        except Exception as e:
            error_msg = f"Failed to save live trades: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def archive_live_trades(self, cutoff_time: datetime) -> int:
        """Archive live trades to historical_trades table.

        Moves trades older than cutoff_time from live_trades to historical_trades,
        then deletes them from live_trades.

        Args:
            cutoff_time: Timestamp threshold - trades ingested before this are archived

        Returns:
            Number of trades archived

        Raises:
            Exception: If archive operation fails
        """
        logger.info(f"Archiving live trades older than {cutoff_time}")

        try:
            with self.transaction():
                # Count rows to be archived
                count_query = "SELECT COUNT(*) as count FROM live_trades WHERE ingested_at < ?"
                result = self.fetch_one(count_query, (cutoff_time,))
                count = result['count'] if result else 0

                # Insert into historical_trades
                insert_query = """
                    INSERT INTO historical_trades
                    (symbol, timestamp, trade_id, price, size, exchange,
                     conditions, tape, source, archived_at)
                    SELECT symbol, timestamp, trade_id, price, size, exchange,
                           conditions, tape, 'stream' as source, CURRENT_TIMESTAMP
                    FROM live_trades
                    WHERE ingested_at < ?
                """
                self.execute(insert_query, (cutoff_time,))

                # Delete from live_trades
                delete_query = "DELETE FROM live_trades WHERE ingested_at < ?"
                self.execute(delete_query, (cutoff_time,))

                logger.info(f"Successfully archived {count} live trades")
                return count

        except Exception as e:
            error_msg = f"Failed to archive live trades: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    # ========================================================================
    # Computed Indicators Operations
    # ========================================================================

    def save_computed_indicators(self, df: pd.DataFrame) -> int:
        """Save pre-computed technical indicators.

        Args:
            df: DataFrame with columns: symbol, timestamp, timeframe, and indicator columns
                (macd_value, macd_signal, rsi, bb_upper, bb_middle, bb_lower, etc.)

        Returns:
            Number of rows saved

        Raises:
            Exception: If save fails
        """
        if df.empty:
            logger.info("No computed indicators to save")
            return 0

        logger.info(f"Saving {len(df)} computed indicator rows")

        try:
            # Ensure required columns exist
            required_cols = ['symbol', 'timestamp', 'timeframe']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                raise ValueError(f"Missing required columns: {missing_cols}")

            # Convert timestamp to datetime if needed
            df = df.copy()
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])

            rows = self.upsert_df('computed_indicators', df,
                                 key_columns=['symbol', 'timestamp', 'timeframe'])
            logger.info(f"Successfully saved {rows} computed indicator rows")
            return rows

        except Exception as e:
            error_msg = f"Failed to save computed indicators: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def get_computed_indicators(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1Min"
    ) -> pd.DataFrame:
        """Retrieve pre-computed technical indicators.

        Args:
            symbol: Stock ticker symbol
            start: Start timestamp
            end: End timestamp
            timeframe: Timeframe string ('1Min', '1Hour', '1Day')

        Returns:
            DataFrame with indicator data
        """
        query = """
            SELECT * FROM computed_indicators
            WHERE symbol = ?
              AND timeframe = ?
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp ASC
        """

        return self.fetch_df(query, (symbol, timeframe, start, end))


if __name__ == "__main__":
    """Test AlpacaDAO functionality."""
    print("=" * 60)
    print("Testing AlpacaDAO")
    print("=" * 60)

    # Create test DAO
    dao = AlpacaDAO(db_path="data/test_alpaca.duckdb")

    # Test 1: Add to watchlist
    print("\n1. Adding symbols to watchlist...")
    try:
        dao.add_to_watchlist('AAPL', 'Tech leader')
        dao.add_to_watchlist('MSFT', 'Software giant')
        dao.add_to_watchlist('GOOGL')
        print("   [OK] Added symbols to watchlist")
    except Exception as e:
        print(f"   [FAIL] {e}")

    # Test 2: Get watchlist
    print("\n2. Retrieving watchlist...")
    try:
        watchlist = dao.get_watchlist()
        print(f"   [OK] Watchlist: {watchlist}")
    except Exception as e:
        print(f"   [FAIL] {e}")

    # Test 3: Save bars
    print("\n3. Saving market bars...")
    try:
        test_bars = pd.DataFrame([
            {
                'symbol': 'AAPL',
                'timestamp': '2024-02-17 09:30:00',
                'open': 180.0,
                'high': 181.5,
                'low': 179.5,
                'close': 180.5,
                'volume': 1000000,
                'trade_count': 500,
                'vwap': 180.2
            },
            {
                'symbol': 'AAPL',
                'timestamp': '2024-02-17 09:31:00',
                'open': 180.5,
                'high': 181.0,
                'low': 180.0,
                'close': 180.8,
                'volume': 800000,
                'trade_count': 450,
                'vwap': 180.6
            }
        ])
        rows = dao.save_bars(test_bars, timeframe='1Min')
        print(f"   [OK] Saved {rows} bars")
    except Exception as e:
        print(f"   [FAIL] {e}")

    # Test 4: Get bars
    print("\n4. Retrieving market bars...")
    try:
        start = datetime(2024, 2, 17, 9, 0)
        end = datetime(2024, 2, 17, 10, 0)
        bars = dao.get_bars('AAPL', start, end, timeframe='1Min')
        print(f"   [OK] Retrieved {len(bars)} bars")
        print(f"\n{bars}")
    except Exception as e:
        print(f"   [FAIL] {e}")

    # Test 5: Save trades
    print("\n5. Saving historical trades...")
    try:
        test_trades = pd.DataFrame([
            {
                'symbol': 'AAPL',
                'timestamp': '2024-02-17 09:30:15',
                'trade_id': 123456,
                'price': 180.25,
                'size': 100,
                'exchange': 'Q',
                'conditions': '@',
                'tape': 'C'
            }
        ])
        rows = dao.save_trades(test_trades)
        print(f"   [OK] Saved {rows} trades")
    except Exception as e:
        print(f"   [FAIL] {e}")

    # Cleanup
    print("\n6. Cleaning up...")
    dao.close()
    import os
    if os.path.exists("data/test_alpaca.duckdb"):
        os.remove("data/test_alpaca.duckdb")
    print("   [OK] Test complete")

    print("\n" + "=" * 60)
