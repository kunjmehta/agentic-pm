"""DAO for end-of-day analyst summaries.

30-minute summaries are stored on disk via deepagents file system.
Only EOD summaries are persisted to database for long-term storage.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
from datetime import datetime, date
from typing import Dict, List, Optional
import pandas as pd

from src.common.dao.base_dao import BaseDAO
from src.common.utils import get_logger

logger = get_logger(__name__)


class AnalystDAO(BaseDAO):
    """Data access layer for end-of-day analyst summaries."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize AnalystDAO.

        Args:
            db_path: Path to DuckDB database file. If None, uses analysis.duckdb.
        """
        super().__init__(db_path=db_path, db_type='analysis')
        self._initialize_schema()

    def _initialize_schema(self):
        """Initialize analyst_summaries table from schema file."""
        schema_path = project_root / "config" / "schema" / "analyst_schema.sql"
        if schema_path.exists():
            # Only execute if analyst_summaries table doesn't exist
            self.execute_schema_file(str(schema_path), check_table="analyst_summaries")
            logger.debug("Analyst schema check completed")
        else:
            logger.warning(f"Schema file not found: {schema_path}")

    def save_eod_summary(
        self,
        symbol: str,
        timestamp: datetime,
        indicators: Dict,
        summary_text: str,
        signals: Dict,
        thought_trace: Optional[str] = None,
        model_used: Optional[str] = "gpt-4",
        token_count: Optional[int] = None
    ) -> int:
        """Save end-of-day summary to database.

        Args:
            symbol: Stock ticker (e.g., 'AAPL')
            timestamp: EOD timestamp (should be 4:01 PM ET)
            indicators: Dict of final indicator values for the day
            summary_text: LLM-generated comprehensive daily analysis
            signals: Structured signals dict (momentum, volatility, volume_trend)
            thought_trace: Agent's reasoning and decision process
            model_used: LLM model identifier
            token_count: Number of tokens consumed

        Returns:
            Number of rows inserted/updated
        """
        data = pd.DataFrame([{
            'symbol': symbol,
            'timestamp': timestamp,
            'date_only': timestamp.date(),  # Extract date for uniqueness
            'indicators': json.dumps(indicators),
            'summary_text': summary_text,
            'signals': json.dumps(signals),
            'thought_trace': thought_trace,
            'model_used': model_used,
            'token_count': token_count
        }])

        rows = self.upsert_df(
            table="analyst_summaries",
            df=data,
            key_columns=['symbol', 'date_only']
        )

        logger.info(f"Saved EOD summary for {symbol} at {timestamp}")
        return rows

    def get_eod_summaries(
        self,
        symbol: str,
        start_date: date,
        end_date: date
    ) -> pd.DataFrame:
        """Get EOD summaries for a symbol and date range.

        Args:
            symbol: Stock ticker
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            DataFrame with EOD summaries, sorted by date descending
        """
        query = """
            SELECT *
            FROM analyst_summaries
            WHERE symbol = ?
              AND DATE(timestamp) >= ?
              AND DATE(timestamp) <= ?
            ORDER BY timestamp DESC
        """

        df = self.fetch_df(query, [symbol, start_date, end_date])

        # Parse JSON columns
        if not df.empty:
            df['indicators'] = df['indicators'].apply(json.loads)
            df['signals'] = df['signals'].apply(json.loads)

        return df

    def get_latest_eod(self, symbol: str) -> Optional[Dict]:
        """Get the most recent EOD summary for a symbol.

        Args:
            symbol: Stock ticker

        Returns:
            Dict with EOD summary data or None if no summary exists
        """
        query = """
            SELECT *
            FROM analyst_summaries
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """

        df = self.fetch_df(query, [symbol])

        if df.empty:
            logger.info(f"No EOD summary found for {symbol}")
            return None

        # Parse JSON and return as dict
        row = df.iloc[0].to_dict()
        row['indicators'] = json.loads(row['indicators'])
        row['signals'] = json.loads(row['signals'])

        logger.info(f"Retrieved latest EOD for {symbol}: {row['timestamp']}")
        return row

    def get_recent_eods(self, symbol: str, count: int = 5) -> List[Dict]:
        """Get the N most recent EOD summaries for a symbol.

        Args:
            symbol: Stock ticker
            count: Number of recent summaries to retrieve

        Returns:
            List of EOD summary dicts
        """
        query = """
            SELECT *
            FROM analyst_summaries
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """

        df = self.fetch_df(query, [symbol, count])

        if df.empty:
            return []

        # Parse JSON columns
        df['indicators'] = df['indicators'].apply(json.loads)
        df['signals'] = df['signals'].apply(json.loads)

        return df.to_dict('records')

    def get_all_symbols(self) -> List[str]:
        """Get list of all symbols with EOD summaries.

        Returns:
            List of unique stock ticker symbols
        """
        query = "SELECT DISTINCT symbol FROM analyst_summaries ORDER BY symbol"
        df = self.fetch_df(query)
        return df['symbol'].tolist() if not df.empty else []