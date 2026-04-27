"""SwapPositionsSkill — simulate position swaps and forward-value the result (Workflow C)."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)


class SwapPositionsSkill:
    """Simulate instantaneous position swaps and forward-value the result.

    A "swap" replaces a quantity of one symbol with an equal quantity of
    another at the snapshot date, then holds to end_date — no buy/sell
    transaction costs are modelled.
    """

    def simulate(
        self,
        snapshot_date: str,
        end_date: str,
        tickers: Dict[str, Dict],
    ) -> Dict:
        """Apply position swaps to a snapshot and calculate portfolio worth.

        Args:
            snapshot_date: Date of the portfolio snapshot (YYYY-MM-DD).
            end_date: Future date to value the swapped portfolio (YYYY-MM-DD).
            tickers: Mapping of ``{symbol: {"swap_to": "NEW_SYM", "quantity": N}}``.
                Example: ``{"AAPL": {"swap_to": "TSLA", "quantity": 50}}``.

        Returns:
            Dict with swaps_applied, initial_worth_before_swap, initial_worth,
            final_worth, return_pct, return_dollars, positions_at_end, metrics.
        """
        logger.info(f"[SwapPositionsSkill.simulate] {snapshot_date} → {end_date}, swaps={tickers}")

        try:
            from src.common.dao.portfolio_dao import PortfolioDAO
            from src.common.dao.alpaca_dao import AlpacaDAO
            from src.server.skills.backtester.core.controller import run_swap_simulation

            snap_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

            if end_dt <= snap_date:
                return {"error": f"end_date ({end_date}) must be after snapshot_date ({snapshot_date})"}

            # Validate tickers format
            for symbol, swap_info in tickers.items():
                if "swap_to" not in swap_info:
                    return {
                        "error": f"Invalid swap format for {symbol}: missing 'swap_to'",
                        "expected_format": '{"AAPL": {"swap_to": "TSLA", "quantity": 50}}',
                    }
                if "quantity" not in swap_info:
                    return {
                        "error": f"Invalid swap format for {symbol}: missing 'quantity'",
                        "expected_format": '{"AAPL": {"swap_to": "TSLA", "quantity": 50}}',
                    }

            portfolio_dao = PortfolioDAO()
            snapshot_history = portfolio_dao.get_snapshot_history(
                start_date=snap_date - timedelta(days=7), end_date=snap_date
            )
            if snapshot_history.empty:
                portfolio_dao.close()
                return {
                    "error": f"No portfolio snapshot found near {snapshot_date}",
                    "suggestion": "Create a portfolio snapshot first or try a different date",
                }

            snapshot_row = snapshot_history.iloc[0]
            actual_snapshot_date = snapshot_row["date_only"]
            positions_json = snapshot_row.get("positions_json")
            if not positions_json:
                portfolio_dao.close()
                return {
                    "error": f"Snapshot from {actual_snapshot_date} has no position details",
                    "suggestion": "Use newer snapshots with position data",
                }

            positions_list = (
                json.loads(positions_json) if isinstance(positions_json, str) else positions_json
            )
            positions = {p["symbol"]: p for p in positions_list if p.get("symbol")}

            # Validate positions to be swapped exist and have sufficient quantity
            for symbol, swap_info in tickers.items():
                if symbol not in positions:
                    portfolio_dao.close()
                    return {
                        "error": f"Cannot swap {symbol} — not in snapshot",
                        "available_positions": list(positions.keys()),
                    }
                swap_qty = swap_info.get("quantity", 0)
                current_qty = positions[symbol].get("quantity", 0)
                if swap_qty > current_qty:
                    portfolio_dao.close()
                    return {
                        "error": (
                            f"Cannot swap {swap_qty} shares of {symbol} — "
                            f"only {current_qty} available in snapshot"
                        )
                    }

            portfolio_snapshot = {
                "date": actual_snapshot_date,
                "timestamp": snapshot_row["timestamp"],
                "cash": float(snapshot_row["cash"]),
                "equity": float(snapshot_row["equity"]),
                "buying_power": float(snapshot_row.get("buying_power", 0)),
                "positions": positions,
                "long_positions": snapshot_row.get("long_positions", 0),
                "short_positions": snapshot_row.get("short_positions", 0),
            }
            portfolio_dao.close()

            # Collect all symbols (old + new)
            all_symbols = list(positions.keys())
            for swap_info in tickers.values():
                new_sym = swap_info["swap_to"]
                if new_sym not in all_symbols:
                    all_symbols.append(new_sym)

            start_dt_ts = datetime.combine(snap_date, datetime.min.time())
            end_dt_ts = datetime.combine(end_dt, datetime.max.time())

            alpaca_dao = AlpacaDAO()
            bars_list = []
            for sym in all_symbols:
                sym_bars = alpaca_dao.get_bars(
                    symbol=sym, start=start_dt_ts, end=end_dt_ts, timeframe="1Day"
                )
                if not sym_bars.empty:
                    sym_bars["symbol"] = sym
                    bars_list.append(sym_bars)
            alpaca_dao.close()

            if not bars_list:
                return {
                    "error": f"No historical data for {all_symbols} from {snapshot_date} to {end_date}",
                    "suggestion": "Ingest market data for these symbols first",
                }

            bars_df = pd.concat(bars_list, ignore_index=True)
            result = run_swap_simulation(
                snapshot=portfolio_snapshot,
                end_date=end_dt,
                bars_df=bars_df,
                swaps=tickers,
            )
            logger.info(f"[SwapPositionsSkill.simulate] {result.get('return_pct', 0):.2f}% return")
            return result

        except Exception as exc:
            logger.error(f"[SwapPositionsSkill.simulate] Error: {exc}", exc_info=True)
            return {"error": f"Swap simulation failed: {exc}"}


# Singleton
swap_skill = SwapPositionsSkill()

# Legacy function alias
swap_positions_core = swap_skill.simulate

__all__ = ["SwapPositionsSkill", "swap_skill", "swap_positions_core"]
