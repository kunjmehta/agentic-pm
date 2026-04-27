"""Data Access Object for Alpha Vantage fundamental data.

This module provides specialized DAO operations for storing and retrieving
Alpha Vantage fundamental data including company overviews, dividends,
earnings, and financial statements.
"""

import sys
from pathlib import Path

from sympy import limit
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Dict, List, Optional
from datetime import date, datetime
import pandas as pd
import json
from src.common.dao.base_dao import BaseDAO
from src.common.utils import get_logger


# Initialize logger
logger = get_logger(__name__)


class AlphaVantageDAO(BaseDAO):
    """DAO for Alpha Vantage fundamental data operations.

    Handles storage and retrieval of:
    - Company fundamentals (overview)
    - Dividend history
    - Earnings history
    - Income statements
    - Balance sheets
    - Cash flow statements
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize AlphaVantageDAO.

        Args:
            db_path: Path to DuckDB database. If None, uses market_data.duckdb.
        """
        super().__init__(db_path=db_path, db_type='market')
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Ensure Alpha Vantage schema exists in database."""
        schema_file = "config/schema/alpha_vantage_schema.sql"
        try:
            # Only execute if company_overview table doesn't exist
            self.execute_schema_file(schema_file, check_table="company_overview")
            logger.debug("Alpha Vantage schema check completed")
        except Exception as e:
            logger.warning(f"Schema initialization skipped: {str(e)}")

    # ========================================================================
    # Company Fundamentals
    # ========================================================================

    def save_company_overview(self, symbol: str, data: Dict) -> None:
        """Save or update company overview data.

        Args:
            symbol: Stock ticker symbol
            data: Company overview dictionary from Alpha Vantage API

        Raises:
            Exception: If save fails
        """
        logger.info(f"Saving company overview for {symbol}")

        try:
            # Extract key fields
            record = {
                'symbol': symbol,
                'name': data.get('Name'),
                'description': data.get('Description'),
                'sector': data.get('Sector'),
                'industry': data.get('Industry'),
                'market_cap': self._to_int(data.get('MarketCapitalization')),
                'pe_ratio': self._to_float(data.get('PERatio')),
                'dividend_yield': self._to_float(data.get('DividendYield')),
                'profit_margin': self._to_float(data.get('ProfitMargin')),
                'eps': self._to_float(data.get('EPS')),
                'beta': self._to_float(data.get('Beta')),
                'full_data': json.dumps(data),
                'updated_at': datetime.now()
            }

            df = pd.DataFrame([record])
            self.upsert_df('fundamentals', df, key_columns=['symbol'])

            logger.info(f"Successfully saved company overview for {symbol}")

        except Exception as e:
            error_msg = f"Failed to save company overview for {symbol}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def get_company_overview(self, symbol: str) -> Optional[Dict]:
        """Retrieve company overview data.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Dictionary with company overview data, or None if not found
        """
        query = "SELECT * FROM fundamentals WHERE symbol = ?"
        return self.fetch_one(query, (symbol,))

    def get_all_fundamentals(self) -> pd.DataFrame:
        """Retrieve all company fundamentals.

        Returns:
            DataFrame with all company fundamentals
        """
        query = "SELECT * FROM latest_fundamentals"
        return self.fetch_df(query)

    # ========================================================================
    # Dividend History
    # ========================================================================

    def save_dividends(self, symbol: str, df: pd.DataFrame) -> int:
        """Save dividend history data.

        Args:
            symbol: Stock ticker symbol
            df: DataFrame with columns: ex_dividend_date, declaration_date,
                record_date, payment_date, amount

        Returns:
            Number of rows saved

        Raises:
            Exception: If save fails
        """
        if df.empty:
            logger.info(f"No dividend data to save for {symbol}")
            return 0

        logger.info(f"Saving {len(df)} dividend records for {symbol}")

        try:
            # Ensure symbol column exists
            if 'symbol' not in df.columns:
                df = df.copy()
                df.insert(0, 'symbol', symbol)

            # Convert date columns to proper format
            date_cols = ['ex_dividend_date', 'declaration_date', 'record_date', 'payment_date']
            for col in date_cols:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors='coerce')

            # Select only required columns
            required_cols = ['symbol'] + date_cols + ['amount']
            df = df[[col for col in required_cols if col in df.columns]]

            rows = self.upsert_df('dividend_history', df, key_columns=['symbol', 'ex_dividend_date'])
            logger.info(f"Successfully saved {rows} dividend records for {symbol}")
            return rows

        except Exception as e:
            error_msg = f"Failed to save dividends for {symbol}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def get_dividends(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """Retrieve dividend history.

        Args:
            symbol: Stock ticker symbol
            start_date: Optional start date filter
            end_date: Optional end date filter
            limit: Optional maximum number of records to return

        Returns:
            DataFrame with dividend history
        """
        query = "SELECT * FROM dividend_history WHERE symbol = ?"
        params = [symbol]

        if start_date:
            query += " AND ex_dividend_date >= ?"
            params.append(start_date)

        if end_date:
            query += " AND ex_dividend_date <= ?"
            params.append(end_date)

        query += " ORDER BY ex_dividend_date DESC"

        if limit is not None:  
            try:  
                limit_int = int(limit)  
            except (TypeError, ValueError):  
                raise ValueError("limit must be an integer")  # Prevent SQL injection via LIMIT clause  

            # Only apply LIMIT for positive integers; for zero/negative, behave like no limit.  
            if limit_int > 0:  
                query += f" LIMIT {limit_int}"  

        return self.fetch_df(query, tuple(params))

    # ========================================================================
    # Earnings History
    # ========================================================================

    def save_earnings(self, symbol: str, df: pd.DataFrame, quarterly: bool = True) -> int:
        """Save earnings history data.

        Args:
            symbol: Stock ticker symbol
            df: DataFrame with earnings data
            quarterly: True for quarterly data, False for annual

        Returns:
            Number of rows saved

        Raises:
            Exception: If save fails
        """
        if df.empty:
            logger.info(f"No earnings data to save for {symbol}")
            return 0

        logger.info(f"Saving {len(df)} {'quarterly' if quarterly else 'annual'} earnings records for {symbol}")

        try:
            # Ensure required columns
            if 'symbol' not in df.columns:
                df = df.copy()
                df.insert(0, 'symbol', symbol)

            df['is_quarterly'] = quarterly

            # Map column names from API to DB schema
            column_mapping = {
                'fiscalDateEnding': 'fiscal_date_ending',
                'reportedDate': 'reported_date',
                'reportedEPS': 'reported_eps',
                'estimatedEPS': 'estimated_eps',
                'surprise': 'surprise',
                'surprisePercentage': 'surprise_percentage'
            }

            df = df.rename(columns=column_mapping)

            # Convert date columns
            if 'fiscal_date_ending' in df.columns:
                df['fiscal_date_ending'] = pd.to_datetime(df['fiscal_date_ending'], errors='coerce')
            if 'reported_date' in df.columns:
                df['reported_date'] = pd.to_datetime(df['reported_date'], errors='coerce')

            rows = self.upsert_df('earnings_history', df,
                                 key_columns=['symbol', 'fiscal_date_ending', 'is_quarterly'])
            logger.info(f"Successfully saved {rows} earnings records for {symbol}")
            return rows

        except Exception as e:
            error_msg = f"Failed to save earnings for {symbol}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def get_earnings(
        self,
        symbol: str,
        quarterly: bool = True,
        limit: int = 4
    ) -> pd.DataFrame:
        """Retrieve earnings history.

        Args:
            symbol: Stock ticker symbol
            quarterly: True for quarterly data, False for annual
            limit: Maximum number of records to return

        Returns:
            DataFrame with earnings history
        """
        query = """
            SELECT * FROM earnings_history
            WHERE symbol = ? AND is_quarterly = ?
            ORDER BY fiscal_date_ending DESC
            LIMIT ?
        """
        return self.fetch_df(query, (symbol, quarterly, limit))

    # ========================================================================
    # Financial Statements
    # ========================================================================

    def save_income_statement(self, symbol: str, df: pd.DataFrame, quarterly: bool = False) -> int:
        """Save income statement data.

        Args:
            symbol: Stock ticker symbol
            df: DataFrame with income statement data
            quarterly: True for quarterly data, False for annual

        Returns:
            Number of rows saved
        """
        return self._save_financial_statement('income_statements', symbol, df, quarterly)

    def save_balance_sheet(self, symbol: str, df: pd.DataFrame, quarterly: bool = False) -> int:
        """Save balance sheet data.

        Args:
            symbol: Stock ticker symbol
            df: DataFrame with balance sheet data
            quarterly: True for quarterly data, False for annual

        Returns:
            Number of rows saved
        """
        return self._save_financial_statement('balance_sheets', symbol, df, quarterly)

    def save_cash_flow(self, symbol: str, df: pd.DataFrame, quarterly: bool = False) -> int:
        """Save cash flow statement data.

        Args:
            symbol: Stock ticker symbol
            df: DataFrame with cash flow data
            quarterly: True for quarterly data, False for annual

        Returns:
            Number of rows saved
        """
        return self._save_financial_statement('cash_flows', symbol, df, quarterly)

    def _save_financial_statement(
        self,
        table: str,
        symbol: str,
        df: pd.DataFrame,
        quarterly: bool
    ) -> int:
        """Generic method to save financial statement data.

        Args:
            table: Table name (income_statements, balance_sheets, cash_flows)
            symbol: Stock ticker symbol
            df: DataFrame with financial data
            quarterly: True for quarterly data, False for annual

        Returns:
            Number of rows saved
        """
        if df.empty:
            logger.info(f"No {table} data to save for {symbol}")
            return 0

        logger.info(f"Saving {len(df)} {'quarterly' if quarterly else 'annual'} {table} records for {symbol}")

        try:
            # Ensure required columns
            if 'symbol' not in df.columns:
                df = df.copy()
                df.insert(0, 'symbol', symbol)

            df['is_quarterly'] = quarterly

            # Convert fiscal_date_ending to date
            if 'fiscal_date_ending' in df.columns:
                df['fiscal_date_ending'] = pd.to_datetime(df['fiscal_date_ending'], errors='coerce')

            # Convert full_data dict to JSON string
            if 'full_data' in df.columns:
                df['full_data'] = df['full_data'].apply(lambda x: json.dumps(x) if isinstance(x, dict) else x)

            rows = self.upsert_df(table, df, key_columns=['symbol', 'fiscal_date_ending', 'is_quarterly'])
            logger.info(f"Successfully saved {rows} {table} records for {symbol}")
            return rows

        except Exception as e:
            error_msg = f"Failed to save {table} for {symbol}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def get_income_statement(self, symbol: str, quarterly: bool = False, limit: int = 4) -> pd.DataFrame:
        """Retrieve income statement data."""
        return self._get_financial_statement('income_statements', symbol, quarterly, limit)

    def get_balance_sheet(self, symbol: str, quarterly: bool = False, limit: int = 4) -> pd.DataFrame:
        """Retrieve balance sheet data."""
        return self._get_financial_statement('balance_sheets', symbol, quarterly, limit)

    def get_cash_flow(self, symbol: str, quarterly: bool = False, limit: int = 4) -> pd.DataFrame:
        """Retrieve cash flow data."""
        return self._get_financial_statement('cash_flows', symbol, quarterly, limit)

    def _get_financial_statement(
        self,
        table: str,
        symbol: str,
        quarterly: bool,
        limit: int
    ) -> pd.DataFrame:
        """Generic method to retrieve financial statement data."""
        query = f"""
            SELECT * FROM {table}
            WHERE symbol = ? AND is_quarterly = ?
            ORDER BY fiscal_date_ending DESC
            LIMIT ?
        """
        return self.fetch_df(query, (symbol, quarterly, limit))

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def _to_float(self, value) -> Optional[float]:
        """Safely convert value to float."""
        if value is None or value == '' or value == 'None':
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _to_int(self, value) -> Optional[int]:
        """Safely convert value to int."""
        if value is None or value == '' or value == 'None':
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None