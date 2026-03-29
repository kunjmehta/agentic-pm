"""Portfolio snapshot forward valuation skill.

Calculates what a portfolio snapshot would be worth at a future date
if positions were held unchanged (buy-and-hold from snapshot date).
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Dict
from datetime import date, datetime, timedelta
import json
import pandas as pd

from src.common.dao.portfolio_dao import PortfolioDAO
from src.common.dao.alpaca_dao import AlpacaDAO
from src.agentic.agents.backtester.core.controller import run_snapshot_forward_simulation
from src.common.utils import get_logger

logger = get_logger(__name__)


def snapshot_worth_core(
    snapshot_date: str,
    end_date: str
) -> Dict:
    """Calculate portfolio snapshot worth at future date (no swaps).

    Retrieves a portfolio snapshot from the given date and calculates
    what it would be worth at end_date if positions were held unchanged.

    Args:
        snapshot_date: Date of portfolio snapshot (YYYY-MM-DD)
        end_date: Future date to calculate worth (YYYY-MM-DD)

    Returns:
        Dict with:
            - snapshot_date: Original snapshot date
            - end_date: Target end date
            - initial_worth: Portfolio value at snapshot_date
            - final_worth: Portfolio value at end_date
            - return_pct: Return percentage
            - return_dollars: Return in dollars
            - positions_at_end: Position details at end_date
            - metrics: Performance metrics
    """
    logger.info(f"[SKILL] snapshot_worth_core: {snapshot_date} -> {end_date}")

    try:
        # Parse dates
        snap_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

        # Validate dates
        if end_dt <= snap_date:
            return {
                "error": f"end_date ({end_date}) must be after snapshot_date ({snapshot_date})"
            }

        # Fetch portfolio snapshot
        portfolio_dao = PortfolioDAO()

        # Get snapshot for the date (or closest before)
        snapshot_history = portfolio_dao.get_snapshot_history(
            start_date=snap_date - timedelta(days=7),
            end_date=snap_date
        )

        if snapshot_history.empty:
            portfolio_dao.close()
            return {
                "error": f"No portfolio snapshot found near {snapshot_date}",
                "suggestion": "Create a portfolio snapshot first or try a different date"
            }

        # Get the closest snapshot (last one in the range)
        snapshot_row = snapshot_history.iloc[0]  # Most recent
        actual_snapshot_date = snapshot_row['date_only']

        logger.info(f"Found snapshot from {actual_snapshot_date}")

        # Parse positions from JSON
        positions_json = snapshot_row.get('positions_json')
        if not positions_json:
            portfolio_dao.close()
            return {
                "error": f"Snapshot from {actual_snapshot_date} has no position details",
                "suggestion": "Snapshot was created without positions_json. Use newer snapshots with position data."
            }

        positions_list = json.loads(positions_json) if isinstance(positions_json, str) else positions_json

        # Convert positions list to dict keyed by symbol
        positions = {}
        for pos in positions_list:
            symbol = pos.get('symbol')
            if symbol:
                positions[symbol] = pos

        # Create PortfolioSnapshot object
        portfolio_snapshot = {
            "date": actual_snapshot_date,
            "timestamp": snapshot_row['timestamp'],
            "cash": float(snapshot_row['cash']),
            "equity": float(snapshot_row['equity']),
            "buying_power": float(snapshot_row.get('buying_power', 0)),
            "positions": positions,
            "long_positions": snapshot_row.get('long_positions', 0),
            "short_positions": snapshot_row.get('short_positions', 0)
        }

        portfolio_dao.close()

        # Get symbols from positions
        symbols = list(positions.keys())
        if not symbols:
            return {
                "snapshot_date": str(actual_snapshot_date),
                "end_date": str(end_dt),
                "initial_worth": float(snapshot_row['equity']),
                "final_worth": float(snapshot_row['cash']),
                "return_pct": 0.0,
                "return_dollars": 0.0,
                "positions": {},
                "message": "No positions in snapshot - only cash"
            }

        # Fetch historical bars for all symbols
        alpaca_dao = AlpacaDAO()

        # Convert dates to datetime for AlpacaDAO
        start_datetime = datetime.combine(snap_date, datetime.min.time())
        end_datetime = datetime.combine(end_dt, datetime.max.time())

        bars_list = []
        for symbol in symbols:
            symbol_bars = alpaca_dao.get_bars(
                symbol=symbol,
                start=start_datetime,
                end=end_datetime,
                timeframe="1Day"  # Daily bars for forward simulation
            )

            if not symbol_bars.empty:
                symbol_bars['symbol'] = symbol
                bars_list.append(symbol_bars)

        alpaca_dao.close()

        if not bars_list:
            return {
                "error": f"No historical data available for symbols {symbols} from {snapshot_date} to {end_date}",
                "suggestion": "Ingest market data for these symbols first"
            }

        # Combine all bars
        bars_df = pd.concat(bars_list, ignore_index=True)

        logger.info(f"Fetched {len(bars_df)} bars for {len(symbols)} symbols")

        # Run forward simulation
        result = run_snapshot_forward_simulation(
            snapshot=portfolio_snapshot,
            end_date=end_dt,
            bars_df=bars_df
        )

        logger.info(f"Forward simulation complete: {result.get('return_pct', 0):.2f}% return")

        return result

    except Exception as e:
        logger.error(f"Error in snapshot_worth_core: {e}", exc_info=True)
        return {
            "error": f"Failed to calculate snapshot worth: {str(e)}"
        }


# =============================================================================
# CLI Entry Point (used by deepagents bash skill execution)
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description="snapshot_worth skill — calculate portfolio worth at a future date"
    )
    parser.add_argument("--snapshot_date", required=True, help="Portfolio snapshot date YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="Target valuation date YYYY-MM-DD")

    args = parser.parse_args()

    result = snapshot_worth_core(
        snapshot_date=args.snapshot_date,
        end_date=args.end_date
    )

    print(_json.dumps(result, default=str))
