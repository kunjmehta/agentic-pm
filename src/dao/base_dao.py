"""Base Data Access Object for DuckDB operations.

This module provides the foundational DAO class with common database operations
that all specific DAOs inherit from.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Any, Dict, List, Optional, Union
import pandas as pd
import duckdb
from contextlib import contextmanager
from src.utils import config, get_logger


# Initialize logger
logger = get_logger(__name__)


class BaseDAO:
    """Base Data Access Object for DuckDB operations.

    Provides common database operations with connection management,
    transaction support, and error handling.

    Attributes:
        db_path: Path to the DuckDB database file
        _conn: DuckDB connection instance (singleton per DAO instance)
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize DAO with database path.

        Args:
            db_path: Path to DuckDB database file. If None, uses path from config.
        """
        if db_path is None:
            db_path = config.get("database.path", default="data/portfolio.duckdb")

        # Ensure path is absolute
        if not Path(db_path).is_absolute():
            db_path = str(project_root / db_path)

        self.db_path = db_path
        self._conn: Optional[duckdb.DuckDBPyConnection] = None

        # Ensure database directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"DAO initialized with database: {self.db_path}")

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Get or create database connection.

        Returns:
            DuckDB connection instance

        Raises:
            Exception: If connection fails
        """
        if self._conn is None:
            try:
                self._conn = duckdb.connect(self.db_path)
                logger.debug(f"Connected to database: {self.db_path}")
            except Exception as e:
                error_msg = f"Failed to connect to database: {str(e)}"
                logger.error(error_msg)
                raise Exception(error_msg)

        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
                self._conn = None
                logger.debug("Database connection closed")
            except Exception as e:
                logger.warning(f"Error closing connection: {str(e)}")

    @contextmanager
    def transaction(self):
        """Context manager for database transactions.

        Usage:
            with dao.transaction():
                dao.execute("INSERT ...")
                dao.execute("UPDATE ...")
                # Commits on success, rolls back on exception

        Yields:
            DuckDB connection
        """
        conn = self.connect()
        try:
            conn.begin()
            yield conn
            conn.commit()
            logger.debug("Transaction committed")
        except Exception as e:
            conn.rollback()
            logger.error(f"Transaction rolled back: {str(e)}")
            raise

    def execute(self, query: str, params: Union[tuple, Dict, None] = None) -> None:
        """Execute SQL query without returning results.

        Args:
            query: SQL query to execute
            params: Query parameters (tuple for ? placeholders, dict for :name)

        Raises:
            Exception: If query execution fails
        """
        conn = self.connect()
        try:
            if params:
                conn.execute(query, params)
            else:
                conn.execute(query)
            logger.debug(f"Executed query: {query[:100]}...")
        except Exception as e:
            error_msg = f"Query execution failed: {str(e)}\nQuery: {query}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def fetch_one(self, query: str, params: Union[tuple, Dict, None] = None) -> Optional[Dict]:
        """Execute query and return single result as dictionary.

        Args:
            query: SQL query to execute
            params: Query parameters

        Returns:
            Dictionary of column:value pairs, or None if no results

        Raises:
            Exception: If query execution fails
        """
        conn = self.connect()
        try:
            if params:
                result = conn.execute(query, params).fetchone()
            else:
                result = conn.execute(query).fetchone()

            if result is None:
                return None

            # Get column names
            columns = [desc[0] for desc in conn.description]
            return dict(zip(columns, result))

        except Exception as e:
            error_msg = f"Query failed: {str(e)}\nQuery: {query}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def fetch_all(self, query: str, params: Union[tuple, Dict, None] = None) -> List[Dict]:
        """Execute query and return all results as list of dictionaries.

        Args:
            query: SQL query to execute
            params: Query parameters

        Returns:
            List of dictionaries, one per row

        Raises:
            Exception: If query execution fails
        """
        conn = self.connect()
        try:
            if params:
                result = conn.execute(query, params).fetchall()
            else:
                result = conn.execute(query).fetchall()

            if not result:
                return []

            # Get column names
            columns = [desc[0] for desc in conn.description]
            return [dict(zip(columns, row)) for row in result]

        except Exception as e:
            error_msg = f"Query failed: {str(e)}\nQuery: {query}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def fetch_df(self, query: str, params: Union[tuple, Dict, None] = None) -> pd.DataFrame:
        """Execute query and return results as pandas DataFrame.

        Args:
            query: SQL query to execute
            params: Query parameters

        Returns:
            pandas DataFrame with query results

        Raises:
            Exception: If query execution fails
        """
        conn = self.connect()
        try:
            if params:
                df = conn.execute(query, params).df()
            else:
                df = conn.execute(query).df()

            logger.debug(f"Fetched {len(df)} rows")
            return df

        except Exception as e:
            error_msg = f"Query failed: {str(e)}\nQuery: {query}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def insert_df(self, table: str, df: pd.DataFrame, if_exists: str = "append") -> int:
        """Insert pandas DataFrame into table.

        Args:
            table: Table name
            df: DataFrame to insert
            if_exists: Action if table exists - 'append', 'replace', or 'fail'

        Returns:
            Number of rows inserted

        Raises:
            Exception: If insertion fails
        """
        if df.empty:
            logger.debug(f"Skipping insert to {table}: DataFrame is empty")
            return 0

        conn = self.connect()
        try:
            # Register DataFrame as temporary table
            conn.register('temp_df', df)

            if if_exists == "replace":
                conn.execute(f"DROP TABLE IF EXISTS {table}")
                conn.execute(f"CREATE TABLE {table} AS SELECT * FROM temp_df")
                rows_inserted = len(df)
            elif if_exists == "append":
                conn.execute(f"INSERT INTO {table} SELECT * FROM temp_df")
                rows_inserted = len(df)
            else:  # fail
                conn.execute(f"INSERT INTO {table} SELECT * FROM temp_df")
                rows_inserted = len(df)

            conn.unregister('temp_df')
            logger.info(f"Inserted {rows_inserted} rows into {table}")
            return rows_inserted

        except Exception as e:
            error_msg = f"Failed to insert DataFrame into {table}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def upsert_df(self, table: str, df: pd.DataFrame, key_columns: List[str]) -> int:
        """Upsert pandas DataFrame (insert or update on conflict).

        Args:
            table: Table name
            df: DataFrame to upsert
            key_columns: Columns that form the unique key

        Returns:
            Number of rows affected

        Raises:
            Exception: If upsert fails
        """
        if df.empty:
            logger.debug(f"Skipping upsert to {table}: DataFrame is empty")
            return 0

        conn = self.connect()
        try:
            # Register DataFrame as temporary table
            conn.register('temp_df', df)

            # Get all columns
            all_columns = list(df.columns)
            non_key_columns = [col for col in all_columns if col not in key_columns]

            # Build update clause
            update_clause = ", ".join([f"{col} = excluded.{col}" for col in non_key_columns])

            # Build upsert query
            columns_str = ", ".join(all_columns)
            query = f"""
                INSERT INTO {table} ({columns_str})
                SELECT {columns_str} FROM temp_df
                ON CONFLICT ({", ".join(key_columns)})
                DO UPDATE SET {update_clause}
            """

            conn.execute(query)
            conn.unregister('temp_df')

            rows_affected = len(df)
            logger.info(f"Upserted {rows_affected} rows into {table}")
            return rows_affected

        except Exception as e:
            error_msg = f"Failed to upsert DataFrame into {table}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def table_exists(self, table_name: str) -> bool:
        """Check if table exists in database.

        Args:
            table_name: Name of table to check

        Returns:
            True if table exists, False otherwise
        """
        query = """
            SELECT COUNT(*) as count
            FROM information_schema.tables
            WHERE table_name = ?
        """
        result = self.fetch_one(query, (table_name,))
        return result['count'] > 0 if result else False

    def execute_schema_file(self, schema_file: str) -> None:
        """Execute SQL commands from schema file.

        Args:
            schema_file: Path to SQL schema file

        Raises:
            Exception: If file not found or execution fails
        """
        schema_path = Path(schema_file)
        if not schema_path.is_absolute():
            schema_path = project_root / schema_file

        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        logger.info(f"Executing schema file: {schema_path}")

        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()

            conn = self.connect()
            conn.execute(sql_content)
            logger.info(f"Successfully executed schema file: {schema_path}")

        except Exception as e:
            error_msg = f"Failed to execute schema file: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


if __name__ == "__main__":
    """Test BaseDAO functionality."""
    print("=" * 60)
    print("Testing BaseDAO")
    print("=" * 60)

    # Create test DAO
    dao = BaseDAO(db_path="data/test.duckdb")

    # Test 1: Create table
    print("\n1. Creating test table...")
    try:
        dao.execute("""
            CREATE TABLE IF NOT EXISTS test_table (
                id INTEGER PRIMARY KEY,
                name VARCHAR,
                value DOUBLE
            )
        """)
        print("   [OK] Table created")
    except Exception as e:
        print(f"   [FAIL] {e}")

    # Test 2: Insert DataFrame
    print("\n2. Inserting test data...")
    try:
        test_df = pd.DataFrame({
            'id': [1, 2, 3],
            'name': ['Alice', 'Bob', 'Charlie'],
            'value': [10.5, 20.3, 15.7]
        })
        rows = dao.insert_df("test_table", test_df, if_exists="append")
        print(f"   [OK] Inserted {rows} rows")
    except Exception as e:
        print(f"   [FAIL] {e}")

    # Test 3: Query data
    print("\n3. Querying data...")
    try:
        result = dao.fetch_df("SELECT * FROM test_table ORDER BY id")
        print(f"   [OK] Retrieved {len(result)} rows")
        print(f"\n{result}")
    except Exception as e:
        print(f"   [FAIL] {e}")

    # Test 4: Check table exists
    print("\n4. Checking table exists...")
    exists = dao.table_exists("test_table")
    print(f"   [OK] Table exists: {exists}")

    # Cleanup
    print("\n5. Cleaning up...")
    dao.execute("DROP TABLE IF EXISTS test_table")
    dao.close()
    print("   [OK] Test complete")

    print("\n" + "=" * 60)
