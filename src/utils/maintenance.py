"""Database maintenance utilities for the agentic trader system.

Provides functions for:
- Thread cleanup (Improvement #10): Delete expired agent interactions
- Database statistics: Track database size and table row counts

These utilities help manage database bloat and provide observability.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import os
import json
from datetime import datetime
from typing import Dict

from src.dao import PortfolioDAO
from src.utils import get_logger

logger = get_logger(__name__)


def cleanup_expired_threads(dry_run: bool = False) -> Dict:
    """Delete expired agent interactions (Improvement #10).

    Removes interactions from agent_interactions table where expires_at < now.
    This prevents database bloat and helps with GDPR compliance by automatically
    cleaning up old conversation data.

    Args:
        dry_run: If True, only report what would be deleted without actually deleting

    Returns:
        Dict with cleanup statistics:
            - deleted: Number of interactions deleted (if not dry_run)
            - dry_run: True if dry_run mode
            - would_delete: Number that would be deleted (if dry_run)
            - timestamp: ISO timestamp of cleanup

    Example:
        >>> cleanup_expired_threads(dry_run=True)
        {'dry_run': True, 'would_delete': 42, 'timestamp': '2026-02-25T...'}

        >>> cleanup_expired_threads(dry_run=False)
        {'deleted': 42, 'timestamp': '2026-02-25T...'}
    """
    dao = PortfolioDAO()

    try:
        # Count expired threads
        count_query = """
            SELECT COUNT(*) as count
            FROM agent_interactions
            WHERE expires_at < CURRENT_TIMESTAMP
        """
        result = dao.fetch_one(count_query)
        expired_count = result["count"] if result else 0

        if dry_run:
            logger.info(f"[DRY RUN] Would delete {expired_count} expired interactions")
            return {
                "dry_run": True,
                "would_delete": expired_count,
                "timestamp": datetime.now().isoformat()
            }

        # Delete expired interactions
        if expired_count > 0:
            delete_query = """
                DELETE FROM agent_interactions
                WHERE expires_at < CURRENT_TIMESTAMP
            """
            dao.execute(delete_query)
            logger.info(f"Deleted {expired_count} expired interactions")
        else:
            logger.info("No expired interactions to delete")

        return {
            "deleted": expired_count,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        raise
    finally:
        dao.close()


def get_database_stats() -> Dict:
    """Get database size and table statistics.

    Returns comprehensive database metrics including file size and row counts
    for all major tables. Useful for monitoring database growth and planning
    maintenance windows.

    Returns:
        Dict with database statistics:
            - database_size_mb: Database file size in megabytes
            - database_path: Full path to database file
            - tables: Dict of table names to row counts
            - timestamp: ISO timestamp of stats collection

    Example:
        >>> stats = get_database_stats()
        >>> print(f"DB Size: {stats['database_size_mb']} MB")
        >>> print(f"Agent interactions: {stats['tables']['agent_interactions']} rows")
    """
    dao = PortfolioDAO()

    try:
        # Database file size
        db_path = dao.db_path
        if os.path.exists(db_path):
            db_size_bytes = os.path.getsize(db_path)
            db_size_mb = db_size_bytes / (1024 * 1024)
        else:
            db_size_mb = 0.0
            logger.warning(f"Database file not found at {db_path}")

        # Table row counts
        tables = [
            "portfolio_snapshots",
            "agent_interactions",
            "portfolio_parameters",
            "market_bars",
            "historical_trades",
            "analyst_summaries",
            "strategy_results"
        ]

        table_stats = {}
        for table in tables:
            try:
                result = dao.fetch_one(f"SELECT COUNT(*) as count FROM {table}")
                table_stats[table] = result["count"] if result else 0
            except Exception as e:
                # Table might not exist (e.g., quant-specific tables)
                logger.debug(f"Could not get stats for table {table}: {e}")
                table_stats[table] = f"error: {str(e)}"

        return {
            "database_size_mb": round(db_size_mb, 2),
            "database_path": db_path,
            "tables": table_stats,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Stats retrieval failed: {e}", exc_info=True)
        raise
    finally:
        dao.close()


def optimize_database() -> Dict:
    """Optimize database by running VACUUM and ANALYZE.

    VACUUM reclaims space from deleted rows and defragments the database.
    ANALYZE updates query planner statistics for better query performance.

    This should be run periodically (e.g., weekly) or after large cleanups.

    Returns:
        Dict with optimization results:
            - vacuum_completed: True if VACUUM succeeded
            - analyze_completed: True if ANALYZE succeeded
            - size_before_mb: Database size before optimization
            - size_after_mb: Database size after optimization
            - space_reclaimed_mb: Space freed by optimization
            - timestamp: ISO timestamp of optimization

    Example:
        >>> result = optimize_database()
        >>> print(f"Reclaimed {result['space_reclaimed_mb']} MB")
    """
    dao = PortfolioDAO()

    try:
        # Get size before optimization
        stats_before = get_database_stats()
        size_before = stats_before["database_size_mb"]

        logger.info("Running VACUUM to reclaim space...")
        dao.execute("VACUUM")
        vacuum_completed = True

        logger.info("Running ANALYZE to update statistics...")
        dao.execute("ANALYZE")
        analyze_completed = True

        # Get size after optimization
        stats_after = get_database_stats()
        size_after = stats_after["database_size_mb"]

        space_reclaimed = size_before - size_after

        logger.info(f"Optimization complete. Reclaimed {space_reclaimed:.2f} MB")

        return {
            "vacuum_completed": vacuum_completed,
            "analyze_completed": analyze_completed,
            "size_before_mb": size_before,
            "size_after_mb": size_after,
            "space_reclaimed_mb": round(space_reclaimed, 2),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Optimization failed: {e}", exc_info=True)
        raise
    finally:
        dao.close()


# =============================================================================
# Main Block for CLI Usage
# =============================================================================

if __name__ == "__main__":
    """Command-line interface for maintenance utilities."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Database maintenance utilities for agentic trader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run cleanup (see what would be deleted)
  python src/utils/maintenance.py cleanup --dry-run

  # Actually delete expired threads
  python src/utils/maintenance.py cleanup

  # Get database statistics
  python src/utils/maintenance.py stats

  # Optimize database (VACUUM + ANALYZE)
  python src/utils/maintenance.py optimize
        """
    )

    parser.add_argument(
        "command",
        choices=["cleanup", "stats", "optimize"],
        help="Command to run"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode (cleanup only) - shows what would be deleted"
    )

    args = parser.parse_args()

    print("="*70)
    print("Agentic Trader - Database Maintenance")
    print("="*70)
    print()

    try:
        if args.command == "cleanup":
            print(f"Running thread cleanup (dry_run={args.dry_run})...")
            result = cleanup_expired_threads(dry_run=args.dry_run)
            print()
            print(json.dumps(result, indent=2))

        elif args.command == "stats":
            print("Collecting database statistics...")
            result = get_database_stats()
            print()
            print(json.dumps(result, indent=2))

        elif args.command == "optimize":
            print("Optimizing database (VACUUM + ANALYZE)...")
            print("WARNING: This may take several minutes for large databases.")
            print()
            result = optimize_database()
            print()
            print(json.dumps(result, indent=2))

        print()
        print("="*70)
        print("Maintenance complete")
        print("="*70)

    except Exception as e:
        print()
        print(f"ERROR: {e}")
        print("="*70)
        sys.exit(1)
