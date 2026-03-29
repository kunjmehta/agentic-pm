"""Position swap simulation skill.

Simulates instantaneous position swaps at a snapshot date and calculates
the resulting portfolio worth at a future date.
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
from src.agentic.agents.backtester.core.controller import run_swap_simulation
from src.common.utils import get_logger

logger = get_logger(__name__)


def swap_positions_core(
    snapshot_date: str,
    end_date: str,
    tickers: Dict[str, Dict]
) -> Dict:
    """Calculate portfolio worth after instantaneous position swaps.

    Swaps are instantaneous replacements on snapshot_date (NOT buy/sell trades).
    Example: Replace 50 shares of AAPL with 50 shares of TSLA at snapshot_date,
    then hold until end_date.

    Args:
        snapshot_date: Date of portfolio snapshot (YYYY-MM-DD)
        end_date: Future date to calculate worth (YYYY-MM-DD)
        tickers: Dict mapping symbol -> {"swap_to": "NEW_SYMBOL", "quantity": N}
            Example: {"AAPL": {"swap_to": "TSLA", "quantity": 50}}

    Returns:
        Dict with:
            - snapshot_date: Original snapshot date
            - end_date: Target end date
            - swaps_applied: List of swaps performed
            - initial_worth_before_swap: Portfolio value before swaps
            - initial_worth: Portfolio value after swaps (at snapshot_date)
            - final_worth: Portfolio value at end_date
            - return_pct: Return percentage from snapshot_date to end_date
            - return_dollars: Return in dollars
            - positions_at_end: Position details at end_date
            - metrics: Performance metrics
    """
    logger.info(f"[SKILL] swap_positions_core: {snapshot_date} -> {end_date}")
    logger.info(f"[SKILL] Swaps: {tickers}")

    try:
        # Parse dates
        snap_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

        # Validate dates
        if end_dt <= snap_date:
            return {
                "error": f"end_date ({end_date}) must be after snapshot_date ({snapshot_date})"
            }

        # Validate tickers format
        for symbol, swap_info in tickers.items():
            if "swap_to" not in swap_info:
                return {
                    "error": f"Invalid swap format for {symbol}: missing 'swap_to' field",
                    "expected_format": '{"AAPL": {"swap_to": "TSLA", "quantity": 50}}'
                }
            if "quantity" not in swap_info:
                return {
                    "error": f"Invalid swap format for {symbol}: missing 'quantity' field",
                    "expected_format": '{"AAPL": {"swap_to": "TSLA", "quantity": 50}}'
                }

        # Fetch portfolio snapshot
        portfolio_dao = PortfolioDAO()

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

        # Get the closest snapshot
        snapshot_row = snapshot_history.iloc[0]
        actual_snapshot_date = snapshot_row['date_only']

        logger.info(f"Found snapshot from {actual_snapshot_date}")

        # Parse positions from JSON
        positions_json = snapshot_row.get('positions_json')
        if not positions_json:
            portfolio_dao.close()
            return {
                "error": f"Snapshot from {actual_snapshot_date} has no position details",
                "suggestion": "Use newer snapshots with position data"
            }

        positions_list = json.loads(positions_json) if isinstance(positions_json, str) else positions_json

        # Convert positions list to dict keyed by symbol
        positions = {}
        for pos in positions_list:
            symbol = pos.get('symbol')
            if symbol:
                positions[symbol] = pos

        # Validate that positions to swap exist
        for symbol in tickers.keys():
            if symbol not in positions:
                portfolio_dao.close()
                return {
                    "error": f"Cannot swap {symbol} - position does not exist in snapshot",
                    "available_positions": list(positions.keys())
                }

            swap_qty = tickers[symbol].get("quantity", 0)
            current_qty = positions[symbol].get("quantity", 0)

            if swap_qty > current_qty:
                portfolio_dao.close()
                return {
                    "error": f"Cannot swap {swap_qty} shares of {symbol} - only {current_qty} available in snapshot"
                }

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

        # Get all symbols involved (old and new)
        all_symbols = list(positions.keys())
        for swap_info in tickers.values():
            new_symbol = swap_info["swap_to"]
            if new_symbol not in all_symbols:
                all_symbols.append(new_symbol)

        # Fetch historical bars for all symbols
        alpaca_dao = AlpacaDAO()

        # Convert dates to datetime for AlpacaDAO
        start_datetime = datetime.combine(snap_date, datetime.min.time())
        end_datetime = datetime.combine(end_dt, datetime.max.time())

        bars_list = []
        for symbol in all_symbols:
            symbol_bars = alpaca_dao.get_bars(
                symbol=symbol,
                start=start_datetime,
                end=end_datetime,
                timeframe="1Day"  # Daily bars for swap simulation
            )

            if not symbol_bars.empty:
                symbol_bars['symbol'] = symbol
                bars_list.append(symbol_bars)

        alpaca_dao.close()

        if not bars_list:
            return {
                "error": f"No historical data available for symbols {all_symbols} from {snapshot_date} to {end_date}",
                "suggestion": "Ingest market data for these symbols first"
            }

        # Combine all bars
        bars_df = pd.concat(bars_list, ignore_index=True)

        logger.info(f"Fetched {len(bars_df)} bars for {len(all_symbols)} symbols")

        # Run swap simulation
        result = run_swap_simulation(
            snapshot=portfolio_snapshot,
            end_date=end_dt,
            bars_df=bars_df,
            swaps=tickers
        )

        logger.info(f"Swap simulation complete")
        logger.info(f"Swaps applied: {len(result.get('swaps_applied', []))}")
        logger.info(f"Return: {result.get('return_pct', 0):.2f}%")

        return result

    except Exception as e:
        logger.error(f"Error in swap_positions_core: {e}", exc_info=True)
        return {
            "error": f"Failed to simulate position swaps: {str(e)}"
        }


# =============================================================================
# CLI Entry Point (used by deepagents bash skill execution)
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description="swap_positions skill — simulate position swaps and calculate future worth"
    )
    parser.add_argument("--snapshot_date", required=True, help="Portfolio snapshot date YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="Target valuation date YYYY-MM-DD")
    parser.add_argument(
        "--tickers",
        required=True,
        help='JSON string of swap specs, e.g. \'{"AAPL": {"swap_to": "TSLA", "quantity": 50}}\''
    )

    args = parser.parse_args()

    tickers = _json.loads(args.tickers)

    result = swap_positions_core(
        snapshot_date=args.snapshot_date,
        end_date=args.end_date,
        tickers=tickers
    )

    print(_json.dumps(result, default=str))
