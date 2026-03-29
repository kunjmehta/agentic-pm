"""Portfolio Status Skill - Fetch current portfolio status and positions.

This skill provides standalone functions for retrieving portfolio information
from Alpaca API. Can be called directly or used as a skill by Portfolio Manager.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import argparse
from datetime import datetime
from typing import Dict

from src.common.skills.alpaca_portfolio_skills import fetch_account_info, fetch_positions
from src.common.dao import PortfolioDAO
from src.common.utils import get_logger

logger = get_logger(__name__)


def get_portfolio_status_core() -> Dict:
    """Fetch current portfolio status from Alpaca.

    Returns:
        Dict with portfolio status including:
        - equity: Total portfolio value
        - cash: Available cash
        - buying_power: Margin buying power
        - long_positions: Number of long positions
        - short_positions: Number of short positions
    """
    # Fetch account info using alpaca_portfolio_skills
    account_data = fetch_account_info()

    # Fetch positions to count long/short
    positions_data = fetch_positions()
    long_count = sum(1 for p in positions_data if p["side"] == "long")
    short_count = sum(1 for p in positions_data if p["side"] == "short")

    result = {
        "equity": account_data["equity"],
        "cash": account_data["cash"],
        "buying_power": account_data["buying_power"],
        "long_positions": long_count,
        "short_positions": short_count,
        "portfolio_value": account_data["portfolio_value"],
        "last_equity": account_data["last_equity"],
        "timestamp": datetime.now().isoformat()
    }

    # Save snapshot to DAO for historical tracking
    try:
        dao = PortfolioDAO()
        dao.save_snapshot(
            timestamp=datetime.now(),
            equity=result["equity"],
            cash=result["cash"],
            buying_power=result["buying_power"],
            long_positions=long_count,
            short_positions=short_count,
            snapshot_source="alpaca"
        )
        dao.close()
    except Exception as dao_error:
        logger.warning(f"Failed to save snapshot to DAO: {dao_error}")

    return result


def get_positions_summary_core() -> Dict:
    """Fetch current positions with P&L breakdown.

    Returns:
        Dict with positions array and summary statistics
    """
    # Use Skills layer instead of direct API call
    positions_data = fetch_positions()

    total_market_value = 0.0
    total_unrealized_pl = 0.0

    # Calculate totals
    for pos in positions_data:
        total_market_value += pos["market_value"]
        total_unrealized_pl += pos["unrealized_pl"]

    result = {
        "positions": positions_data,
        "count": len(positions_data),
        "total_market_value": total_market_value,
        "total_unrealized_pl": total_unrealized_pl,
        "timestamp": datetime.now().isoformat()
    }

    return result


if __name__ == "__main__":
    """CLI interface for testing portfolio status skill."""
    parser = argparse.ArgumentParser(description="Get portfolio status from Alpaca")
    parser.add_argument(
        "--action",
        choices=["status", "positions"],
        default="status",
        help="Action to perform: status or positions"
    )
    parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="json",
        help="Output format"
    )
    args = parser.parse_args()

    try:
        if args.action == "status":
            result = get_portfolio_status_core()
        else:
            result = get_positions_summary_core()

        if args.format == "json":
            print(json.dumps(result, indent=2, default=str))
        else:
            # Simple table format
            for key, value in result.items():
                if key != "positions":  # Skip positions array for table view
                    print(f"{key:20}: {value}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
