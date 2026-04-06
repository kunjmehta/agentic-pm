"""SnapshotSkill — save EOD portfolio snapshots and calculate their future worth (Workflow B)."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)


class SnapshotSkill:
    """Save end-of-day portfolio snapshots and calculate their future worth.

    Two methods:
        save_eod   — persist a portfolio snapshot to PortfolioDAO.
        get_worth  — forward-simulate a snapshot to a future date.
    """

    def save_eod(
        self,
        timestamp: str,
        equity: float,
        cash: float,
        buying_power: float,
        positions: List[Dict],
        daily_pnl: Optional[float] = None,
        total_pnl: Optional[float] = None,
        daily_pnl_percent: Optional[float] = None,
        snapshot_source: str = "manual",
    ) -> Dict:
        """Save end-of-day portfolio snapshot with position details.

        Args:
            timestamp: Snapshot timestamp (ISO format or YYYY-MM-DD HH:MM:SS).
            equity: Total portfolio value.
            cash: Available cash balance.
            buying_power: Margin buying power.
            positions: List of position dicts — each must have a ``symbol`` key.
            daily_pnl: Today's profit/loss (optional).
            total_pnl: All-time P&L (optional).
            daily_pnl_percent: Daily % return (optional).
            snapshot_source: Source identifier. Defaults to ``"manual"``.

        Returns:
            Dict with status, message, snapshot_id, date, positions_count.
        """
        logger.info(f"[SnapshotSkill.save_eod] Saving snapshot for {timestamp}")

        try:
            from src.common.dao.portfolio_dao import PortfolioDAO

            if isinstance(timestamp, str):
                try:
                    ts = datetime.fromisoformat(timestamp)
                except ValueError:
                    ts = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            else:
                ts = timestamp

            if not isinstance(positions, list):
                return {"status": "error", "error": "positions must be a list of position dicts"}

            for pos in positions:
                if not isinstance(pos, dict):
                    return {"status": "error", "error": "Each position must be a dict"}
                if "symbol" not in pos:
                    return {"status": "error", "error": "Each position must have 'symbol' field"}

            long_positions = sum(
                1 for p in positions if p.get("side", "long") == "long" and p.get("quantity", 0) > 0
            )
            short_positions = sum(
                1 for p in positions if p.get("side", "long") == "short" and p.get("quantity", 0) != 0
            )

            portfolio_dao = PortfolioDAO()
            portfolio_dao.save_snapshot(
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
                positions=positions,
            )
            latest = portfolio_dao.get_latest_snapshot()
            snapshot_id = latest.get("snapshot_id") if latest else None
            portfolio_dao.close()

            logger.info(f"[SnapshotSkill.save_eod] Saved snapshot ID {snapshot_id}")
            return {
                "status": "success",
                "message": f"Portfolio snapshot saved for {ts.date()}",
                "snapshot_id": snapshot_id,
                "date": str(ts.date()),
                "positions_count": len(positions),
                "long_positions": long_positions,
                "short_positions": short_positions,
            }

        except Exception as exc:
            logger.error(f"[SnapshotSkill.save_eod] Error: {exc}", exc_info=True)
            return {"status": "error", "error": f"Failed to save snapshot: {exc}"}

    def get_worth(self, snapshot_date: str, end_date: str) -> Dict:
        """Calculate portfolio snapshot worth at a future date (no swaps).

        Retrieves the portfolio snapshot nearest to ``snapshot_date`` and
        forward-simulates a buy-and-hold hold to ``end_date``.

        Args:
            snapshot_date: Date of the portfolio snapshot (YYYY-MM-DD).
            end_date: Future date to value the portfolio at (YYYY-MM-DD).

        Returns:
            Dict with snapshot_date, end_date, initial_worth, final_worth,
            return_pct, return_dollars, positions_at_end, metrics.
        """
        logger.info(f"[SnapshotSkill.get_worth] {snapshot_date} → {end_date}")

        try:
            from src.common.dao.portfolio_dao import PortfolioDAO
            from src.common.dao.alpaca_dao import AlpacaDAO
            from src.agentic.agents.backtester.core.controller import run_snapshot_forward_simulation

            snap_date = datetime.strptime(snapshot_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

            if end_dt <= snap_date:
                return {"error": f"end_date ({end_date}) must be after snapshot_date ({snapshot_date})"}

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
                    "suggestion": "Use newer snapshots with position data.",
                }

            positions_list = (
                json.loads(positions_json) if isinstance(positions_json, str) else positions_json
            )
            positions = {p["symbol"]: p for p in positions_list if p.get("symbol")}

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

            symbols = list(positions.keys())
            if not symbols:
                return {
                    "snapshot_date": str(actual_snapshot_date),
                    "end_date": str(end_dt),
                    "initial_worth": float(snapshot_row["equity"]),
                    "final_worth": float(snapshot_row["cash"]),
                    "return_pct": 0.0,
                    "return_dollars": 0.0,
                    "positions": {},
                    "message": "No positions in snapshot — only cash",
                }

            start_dt_ts = datetime.combine(snap_date, datetime.min.time())
            end_dt_ts = datetime.combine(end_dt, datetime.max.time())

            alpaca_dao = AlpacaDAO()
            bars_list = []
            for sym in symbols:
                sym_bars = alpaca_dao.get_bars(
                    symbol=sym, start=start_dt_ts, end=end_dt_ts, timeframe="1Day"
                )
                if not sym_bars.empty:
                    sym_bars["symbol"] = sym
                    bars_list.append(sym_bars)
            alpaca_dao.close()

            if not bars_list:
                return {
                    "error": f"No historical data for {symbols} from {snapshot_date} to {end_date}",
                    "suggestion": "Ingest market data for these symbols first",
                }

            bars_df = pd.concat(bars_list, ignore_index=True)
            result = run_snapshot_forward_simulation(
                snapshot=portfolio_snapshot, end_date=end_dt, bars_df=bars_df
            )
            logger.info(f"[SnapshotSkill.get_worth] {result.get('return_pct', 0):.2f}% return")
            return result

        except Exception as exc:
            logger.error(f"[SnapshotSkill.get_worth] Error: {exc}", exc_info=True)
            return {"error": f"Failed to calculate snapshot worth: {exc}"}


# Singleton
snapshot_skill = SnapshotSkill()

# Legacy function aliases
save_eod_snapshot_core = snapshot_skill.save_eod
snapshot_worth_core = snapshot_skill.get_worth

__all__ = [
    "SnapshotSkill",
    "snapshot_skill",
    "save_eod_snapshot_core",
    "snapshot_worth_core",
]
