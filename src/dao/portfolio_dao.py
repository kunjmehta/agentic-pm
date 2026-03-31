"""DAO for portfolio management operations.

Handles portfolio snapshots, agent interactions (observability),
risk parameters, and thread cleanup.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import json
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
import pandas as pd

from src.dao.base_dao import BaseDAO
from src.utils import get_logger

logger = get_logger(__name__)


class PortfolioDAO(BaseDAO):
    """Data access layer for portfolio management and observability."""

    def __init__(self, db_path: str = "data/portfolio.duckdb"):
        """Initialize PortfolioDAO.

        Args:
            db_path: Path to DuckDB database file
        """
        super().__init__(db_path)
        self._initialize_schema()

    def _initialize_schema(self):
        """Initialize portfolio schema from schema file."""
        schema_path = Path("config/schema/portfolio_schema.sql")
        if schema_path.exists():
            self.execute_schema_file(str(schema_path))
            logger.info("Portfolio schema initialized")
        else:
            logger.warning(f"Schema file not found: {schema_path}")

    # =========================================================================
    # Portfolio Snapshots
    # =========================================================================

    def save_snapshot(
        self,
        timestamp: datetime,
        equity: float,
        cash: float,
        buying_power: float,
        daily_pnl: Optional[float] = None,
        total_pnl: Optional[float] = None,
        daily_pnl_percent: Optional[float] = None,
        long_positions: int = 0,
        short_positions: int = 0,
        snapshot_source: str = "alpaca"
    ) -> int:
        """Save end-of-day portfolio snapshot.

        Args:
            timestamp: Snapshot timestamp
            equity: Total portfolio value
            cash: Available cash
            buying_power: Margin buying power
            daily_pnl: Today's profit/loss
            total_pnl: All-time P&L
            daily_pnl_percent: Daily % return
            long_positions: Number of long positions
            short_positions: Number of short positions
            snapshot_source: Data source (default: 'alpaca')

        Returns:
            Number of rows inserted/updated
        """
        data = pd.DataFrame([{
            'timestamp': timestamp,
            'date_only': timestamp.date(),
            'equity': equity,
            'cash': cash,
            'buying_power': buying_power,
            'daily_pnl': daily_pnl,
            'total_pnl': total_pnl,
            'daily_pnl_percent': daily_pnl_percent,
            'long_positions': long_positions,
            'short_positions': short_positions,
            'snapshot_source': snapshot_source
        }])

        rows = self.upsert_df('portfolio_snapshots', data, key_columns=['date_only'])
        logger.info(f"Saved portfolio snapshot for {timestamp.date()}: equity=${equity:,.2f}")
        return rows

    def get_latest_snapshot(self) -> Optional[Dict]:
        """Get most recent portfolio snapshot.

        Returns:
            Dict with snapshot data or None if no snapshots exist
        """
        query = "SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1"
        result = self.fetch_one(query)

        if result:
            logger.info(f"Latest snapshot: {result['date_only']}, equity=${result['equity']:,.2f}")

        return result

    def get_snapshot_history(
        self,
        start_date: date,
        end_date: date
    ) -> pd.DataFrame:
        """Get historical portfolio snapshots for date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            DataFrame with snapshot history
        """
        query = """
            SELECT * FROM portfolio_snapshots
            WHERE date_only >= ? AND date_only <= ?
            ORDER BY date_only DESC
        """
        df = self.fetch_df(query, (start_date, end_date))
        logger.info(f"Retrieved {len(df)} snapshots from {start_date} to {end_date}")
        return df

    # =========================================================================
    # Agent Interactions (Observability with Performance Tracking)
    # =========================================================================

    def save_interaction(
        self,
        thread_id: str,
        agent_name: str,
        user_query: str,
        tool_sequence: List[Dict],
        agent_response: str,
        model_used: str,
        token_count: Optional[int] = None,
        execution_time_ms: Optional[int] = None,
        tool_timings: Optional[List[Dict]] = None,
        delegated_to: Optional[str] = None,
        delegation_result: Optional[str] = None
    ) -> int:
        """Log agent interaction for observability.

        Args:
            thread_id: Conversation thread ID
            agent_name: Name of the agent (e.g., 'portfolio_manager')
            user_query: User's query text
            tool_sequence: List of tools executed
            agent_response: Agent's response text
            model_used: LLM model identifier
            token_count: Number of tokens consumed
            execution_time_ms: Total execution time in milliseconds
            tool_timings: Performance tracking for each tool (Improvement #2)
            delegated_to: Agent delegated to (if any)
            delegation_result: Result from delegated agent

        Returns:
            Number of rows inserted
        """
        now = datetime.now()
        expires_at = now + timedelta(days=30)  # Auto-expire after 30 days

        # Use explicit INSERT with column names to allow auto-generation of interaction_id and created_at
        query = """
            INSERT INTO agent_interactions (
                timestamp, thread_id, agent_name, user_query, tool_sequence,
                agent_response, model_used, token_count, execution_time_ms,
                tool_timings, delegated_to, delegation_result, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            now,
            thread_id,
            agent_name,
            user_query,
            json.dumps(tool_sequence),
            agent_response,
            model_used,
            token_count,
            execution_time_ms,
            json.dumps(tool_timings) if tool_timings else None,
            delegated_to,
            delegation_result,
            expires_at
        )

        self.execute(query, params)
        logger.info(f"Logged interaction: agent={agent_name}, thread={thread_id}, "
                   f"execution_time={execution_time_ms}ms")
        return 1  # One row inserted

    def get_interaction_history(
        self,
        thread_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """Get interaction history.

        Args:
            thread_id: Filter by conversation thread (optional)
            agent_name: Filter by agent name (optional)
            limit: Maximum number of interactions to return

        Returns:
            List of interaction dicts
        """
        if thread_id:
            query = """
                SELECT * FROM agent_interactions
                WHERE thread_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            results = self.fetch_all(query, (thread_id, limit))
        elif agent_name:
            query = """
                SELECT * FROM agent_interactions
                WHERE agent_name = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            results = self.fetch_all(query, (agent_name, limit))
        else:
            query = "SELECT * FROM agent_interactions ORDER BY timestamp DESC LIMIT ?"
            results = self.fetch_all(query, (limit,))

        logger.info(f"Retrieved {len(results)} interactions (thread={thread_id}, agent={agent_name})")
        return results

    def get_performance_stats(
        self,
        agent_name: str,
        days: int = 7
    ) -> Optional[Dict]:
        """Get performance metrics for an agent (Improvement #2).

        Args:
            agent_name: Name of the agent
            days: Number of days to look back

        Returns:
            Dict with performance stats or None if no data
        """
        # DuckDB doesn't support ? in INTERVAL, so use f-string for days
        query = f"""
            SELECT
                agent_name,
                COUNT(*) as total_interactions,
                AVG(execution_time_ms) as avg_execution_time,
                MAX(execution_time_ms) as max_execution_time,
                MIN(execution_time_ms) as min_execution_time,
                AVG(token_count) as avg_tokens,
                COUNT(CASE WHEN delegated_to IS NOT NULL THEN 1 END) as delegation_count
            FROM agent_interactions
            WHERE agent_name = ?
              AND created_at >= CURRENT_TIMESTAMP - INTERVAL {days} DAY
            GROUP BY agent_name
        """

        result = self.fetch_one(query, (agent_name,))

        if result:
            logger.info(f"Performance stats for {agent_name}: "
                       f"{result['total_interactions']} interactions, "
                       f"avg {result['avg_execution_time']:.0f}ms")

        return result

    # =========================================================================
    # Risk Parameters
    # =========================================================================

    def get_risk_parameters(self) -> Dict[str, Any]:
        """Load all risk parameters as dict.

        Returns:
            Dict mapping parameter keys to their values
        """
        query = "SELECT parameter_key, parameter_value FROM portfolio_parameters"
        rows = self.fetch_all(query)

        params = {}
        for row in rows:
            try:
                params[row['parameter_key']] = json.loads(row['parameter_value'])
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Failed to parse parameter: {row['parameter_key']}")
                params[row['parameter_key']] = row['parameter_value']

        logger.info(f"Loaded {len(params)} risk parameters")
        return params

    def update_risk_parameter(self, key: str, value: Dict) -> None:
        """Update a risk parameter.

        Args:
            key: Parameter key
            value: Parameter value (will be JSON serialized)
        """
        now = datetime.now()
        query = """
            INSERT INTO portfolio_parameters (parameter_key, parameter_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (parameter_key)
            DO UPDATE SET
                parameter_value = excluded.parameter_value,
                updated_at = excluded.updated_at
        """

        self.execute(query, (key, json.dumps(value), now))
        logger.info(f"Updated risk parameter: {key} = {value}")

    # =========================================================================
    # Thread Cleanup (Improvement #10)
    # =========================================================================

    def cleanup_expired_threads(self, dry_run: bool = False) -> Dict:
        """Delete expired agent interactions.

        Args:
            dry_run: If True, only report what would be deleted

        Returns:
            Dict with cleanup stats
        """
        # Count expired threads
        count_query = """
            SELECT COUNT(*) as count
            FROM agent_interactions
            WHERE expires_at < CURRENT_TIMESTAMP
        """
        result = self.fetch_one(count_query)
        expired_count = result["count"] if result else 0

        if dry_run:
            logger.info(f"[DRY RUN] Would delete {expired_count} expired interactions")
            return {"dry_run": True, "would_delete": expired_count}

        # Delete expired
        if expired_count > 0:
            delete_query = """
                DELETE FROM agent_interactions
                WHERE expires_at < CURRENT_TIMESTAMP
            """
            self.execute(delete_query)
            logger.info(f"Deleted {expired_count} expired interactions")

        return {
            "deleted": expired_count,
            "timestamp": datetime.now().isoformat()
        }

    def extend_thread_expiry(self, thread_id: str, days: int = 30) -> int:
        """Extend expiration date for a thread.

        Args:
            thread_id: Thread ID to extend
            days: Number of days to extend from now

        Returns:
            Number of rows updated
        """
        new_expiry = datetime.now() + timedelta(days=days)

        query = """
            UPDATE agent_interactions
            SET expires_at = ?
            WHERE thread_id = ?
        """

        conn = self.connect()
        result = conn.execute(query, (new_expiry, thread_id))
        rows_updated = result.fetchall()[0][0] if result else 0

        logger.info(f"Extended expiry for thread {thread_id}: +{days} days ({rows_updated} rows)")
        return rows_updated


# =============================================================================
# Main Block for Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Functional tests for Portfolio DAO."""
    import argparse

    parser = argparse.ArgumentParser(description="Test Portfolio DAO")
    parser.add_argument("--test", choices=["snapshot", "interaction", "params", "cleanup", "all"],
                        default="all", help="Which test to run")

    args = parser.parse_args()

    print("=" * 60)
    print("Portfolio DAO Functional Tests")
    print("=" * 60)

    dao = PortfolioDAO()

    if args.test in ["snapshot", "all"]:
        print("\n[TEST 1] save_snapshot() and get_latest_snapshot()")
        print("-" * 60)

        # Save a snapshot
        now = datetime.now()
        rows = dao.save_snapshot(
            timestamp=now,
            equity=105000.50,
            cash=52500.25,
            buying_power=105000.00,
            daily_pnl=5000.50,
            total_pnl=5000.50,
            daily_pnl_percent=0.05,
            long_positions=3,
            short_positions=0
        )
        print(f"Saved {rows} snapshot row(s)")

        # Get latest
        latest = dao.get_latest_snapshot()
        if latest:
            print(f"Latest: {latest['date_only']}, Equity: ${latest['equity']:,.2f}")

        # Get history
        print(f"\n[TEST 1b] get_snapshot_history()")
        start = date.today() - timedelta(days=7)
        end = date.today()
        history = dao.get_snapshot_history(start, end)
        print(f"History: {len(history)} snapshots from {start} to {end}")

    if args.test in ["interaction", "all"]:
        print("\n[TEST 2] save_interaction() and get_interaction_history()")
        print("-" * 60)

        # Save an interaction
        tool_sequence = [
            {"tool": "get_portfolio_status", "executed": True},
            {"tool": "check_portfolio_health", "executed": True}
        ]
        tool_timings = [
            {"tool": "get_portfolio_status", "duration_ms": 150, "status": "success"},
            {"tool": "check_portfolio_health", "duration_ms": 75, "status": "success"}
        ]

        rows = dao.save_interaction(
            thread_id="test-thread-001",
            agent_name="portfolio_manager",
            user_query="What's my portfolio status?",
            tool_sequence=tool_sequence,
            agent_response="Your portfolio is healthy.",
            model_used="gpt-4o-mini",
            token_count=450,
            execution_time_ms=225,
            tool_timings=tool_timings
        )
        print(f"Saved {rows} interaction row(s)")

        # Get history
        history = dao.get_interaction_history(thread_id="test-thread-001", limit=5)
        print(f"History: {len(history)} interactions for thread test-thread-001")

        # Get performance stats
        print(f"\n[TEST 2b] get_performance_stats()")
        stats = dao.get_performance_stats("portfolio_manager", days=7)
        if stats:
            print(f"Stats: {stats['total_interactions']} interactions, "
                  f"avg {stats['avg_execution_time']:.0f}ms")

    if args.test in ["params", "all"]:
        print("\n[TEST 3] get_risk_parameters() and update_risk_parameter()")
        print("-" * 60)

        # Get all parameters
        params = dao.get_risk_parameters()
        print(f"Risk parameters ({len(params)}):")
        for key, value in params.items():
            print(f"  {key}: {value}")

        # Update a parameter
        dao.update_risk_parameter("max_position_size", {"value": 1500, "unit": "shares"})
        print("Updated max_position_size to 1500")

        # Verify update
        params = dao.get_risk_parameters()
        print(f"Updated value: {params['max_position_size']}")

    if args.test in ["cleanup", "all"]:
        print("\n[TEST 4] cleanup_expired_threads()")
        print("-" * 60)

        # Dry run
        result = dao.cleanup_expired_threads(dry_run=True)
        print(f"Dry run: Would delete {result['would_delete']} expired interactions")

        # Actual cleanup
        result = dao.cleanup_expired_threads(dry_run=False)
        print(f"Cleanup: Deleted {result['deleted']} expired interactions")

    dao.close()

    print("\n" + "=" * 60)
    print("Tests Complete")
    print("=" * 60)
