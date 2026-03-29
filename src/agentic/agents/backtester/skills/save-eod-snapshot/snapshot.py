"""Save end-of-day portfolio snapshot skill.

Saves portfolio state with position details for later analysis,
swap simulations, and forward valuations.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Dict, List, Optional
from datetime import datetime

from src.common.dao.portfolio_dao import PortfolioDAO
from src.common.utils import get_logger

logger = get_logger(__name__)


def save_eod_snapshot_core(
    timestamp: str,
    equity: float,
    cash: float,
    buying_power: float,
    positions: List[Dict],
    daily_pnl: Optional[float] = None,
    total_pnl: Optional[float] = None,
    daily_pnl_percent: Optional[float] = None,
    snapshot_source: str = "manual"
) -> Dict:
    """Save end-of-day portfolio snapshot with position details.

    Can be called manually or automatically by backtesting engine after
    each trading day. Stores complete position details for later analysis.

    Args:
        timestamp: Snapshot timestamp (ISO format or YYYY-MM-DD HH:MM:SS)
        equity: Total portfolio value
        cash: Available cash balance
        buying_power: Margin buying power
        positions: List of position dicts with symbol, quantity, cost_basis, etc.
        daily_pnl: Today's profit/loss (optional)
        total_pnl: All-time P&L (optional)
        daily_pnl_percent: Daily % return (optional)
        snapshot_source: Source identifier (default: "manual")

    Returns:
        Dict with:
            - status: "success" or "error"
            - message: Confirmation message
            - snapshot_id: Database snapshot ID
            - date: Snapshot date
            - positions_count: Number of positions saved
            - error: Error message if failed
    """
    logger.info(f"[SKILL] save_eod_snapshot_core: Saving snapshot for {timestamp}")
    logger.info(f"[SKILL] Equity: ${equity:,.2f}, Cash: ${cash:,.2f}")
    logger.info(f"[SKILL] Positions: {len(positions)}")

    try:
        # Parse timestamp
        if isinstance(timestamp, str):
            try:
                # Try ISO format first
                ts = datetime.fromisoformat(timestamp)
            except:
                # Try common format
                ts = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        else:
            ts = timestamp

        # Validate positions
        if not isinstance(positions, list):
            return {
                "status": "error",
                "error": "positions must be a list of position dicts"
            }

        # Validate position structure
        for pos in positions:
            if not isinstance(pos, dict):
                return {
                    "status": "error",
                    "error": "Each position must be a dict"
                }
            if "symbol" not in pos:
                return {
                    "status": "error",
                    "error": "Each position must have 'symbol' field"
                }

        # Count long and short positions
        long_positions = sum(1 for p in positions if p.get("side", "long") == "long" and p.get("quantity", 0) > 0)
        short_positions = sum(1 for p in positions if p.get("side", "long") == "short" and p.get("quantity", 0) != 0)

        # Save snapshot
        portfolio_dao = PortfolioDAO()

        rows = portfolio_dao.save_snapshot(
            timestamp=ts,
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            daily_pnl=daily_pnl,
            total_pnl=total_pnl,
            daily_pnl_percent=daily_pnl_percent,
            long_positions=long_positions,
            short_positions=short_positions,
            snapshot_source=snapshot_source,
            positions=positions
        )

        # Get the saved snapshot to return snapshot_id
        latest = portfolio_dao.get_latest_snapshot()
        snapshot_id = latest.get('snapshot_id') if latest else None

        portfolio_dao.close()

        logger.info(f"[SKILL] Snapshot saved successfully: ID {snapshot_id}")

        return {
            "status": "success",
            "message": f"Portfolio snapshot saved for {ts.date()}",
            "snapshot_id": snapshot_id,
            "date": str(ts.date()),
            "positions_count": len(positions),
            "long_positions": long_positions,
            "short_positions": short_positions
        }

    except Exception as e:
        logger.error(f"Error in save_eod_snapshot_core: {e}", exc_info=True)
        return {
            "status": "error",
            "error": f"Failed to save snapshot: {str(e)}"
        }


# =============================================================================
# CLI Entry Point (used by deepagents bash skill execution)
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description="save_eod_snapshot skill — persist end-of-day portfolio state"
    )
    parser.add_argument("--timestamp", required=True, help="ISO timestamp of snapshot")
    parser.add_argument("--equity", type=float, required=True, help="Total portfolio equity")
    parser.add_argument("--cash", type=float, required=True, help="Available cash")
    parser.add_argument("--buying_power", type=float, required=True, help="Buying power")
    parser.add_argument(
        "--positions",
        required=True,
        help="JSON array of position dicts"
    )
    parser.add_argument("--daily_pnl", type=float, default=None)
    parser.add_argument("--total_pnl", type=float, default=None)
    parser.add_argument("--daily_pnl_percent", type=float, default=None)
    parser.add_argument("--snapshot_source", default="agent")

    args = parser.parse_args()

    result = save_eod_snapshot_core(
        timestamp=args.timestamp,
        equity=args.equity,
        cash=args.cash,
        buying_power=args.buying_power,
        positions=_json.loads(args.positions),
        daily_pnl=args.daily_pnl,
        total_pnl=args.total_pnl,
        daily_pnl_percent=args.daily_pnl_percent,
        snapshot_source=args.snapshot_source
    )

    print(_json.dumps(result, default=str))
