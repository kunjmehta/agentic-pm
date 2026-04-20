"""Reports Data Access Object.

Manages the three reporting tables in the analysis database:
  - signal_performance_tracking
  - hypothetical_portfolios
  - strategy_performance_summary

These tables are derived views of signal history and are populated by the
reporting endpoints and the daily reconciliation job.
"""

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.dao.base_dao import BaseDAO
from src.common.utils import get_logger

logger = get_logger(__name__)

_SCHEMA_FILE = (
    Path(__file__).parent.parent.parent.parent
    / "config"
    / "schema"
    / "reports_schema.sql"
)


class ReportsDAO(BaseDAO):
    """DAO for the three reporting tables in ``analysis.duckdb``.

    Inherits all DuckDB helpers from ``BaseDAO`` and targets the
    ``analysis`` database (``data/analysis.duckdb``).
    """

    def __init__(self) -> None:
        """Initialize with the analysis database and ensure schema exists."""
        super().__init__(db_type="analysis")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create reporting tables if they do not already exist."""
        self.execute_schema_file(
            str(_SCHEMA_FILE),
            check_table="signal_performance_tracking",
        )

    # ------------------------------------------------------------------
    # signal_performance_tracking
    # ------------------------------------------------------------------

    def save_signal_tracking(
        self,
        signal_id: int,
        symbol: str,
        strategy_name: str,
        signal_action: str,
        signal_confidence: float,
        signal_timestamp: datetime,
        was_taken: bool,
        entry_price: Optional[float] = None,
    ) -> str:
        """Insert a new signal tracking row when a signal is approved or rejected.

        Args:
            signal_id: FK to ``strategy_results.id``.
            symbol: Stock ticker.
            strategy_name: Strategy that generated the signal.
            signal_action: "buy" | "sell" | "hold".
            signal_confidence: Confidence score 0–1.
            signal_timestamp: Timestamp of the original signal.
            was_taken: True if approved (order placed), False if rejected/expired.
            entry_price: Fill price if taken.

        Returns:
            UUID primary key of the inserted row.
        """
        tracking_status = "open" if was_taken else "missed"
        row = self.fetch_one(
            """
            INSERT INTO signal_performance_tracking
                (signal_id, symbol, strategy_name, signal_action, signal_confidence,
                 signal_timestamp, was_taken, entry_price, tracking_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (
                signal_id, symbol.upper(), strategy_name, signal_action,
                signal_confidence, signal_timestamp, was_taken, entry_price,
                tracking_status,
            ),
        )
        return row["id"] if row else None

    def close_tracking_row(
        self,
        signal_id: int,
        exit_price: float,
        realized_pnl: float,
    ) -> None:
        """Mark a taken signal as closed with realized P&L.

        Args:
            signal_id: FK to ``strategy_results.id``.
            exit_price: Price at which the position was closed.
            realized_pnl: Realized profit or loss for the trade.
        """
        self.execute(
            """
            UPDATE signal_performance_tracking
               SET exit_price = ?,
                   realized_pnl = ?,
                   tracking_status = 'closed',
                   evaluated_at = CURRENT_TIMESTAMP
             WHERE signal_id = ?
               AND was_taken = TRUE
               AND tracking_status = 'open'
            """,
            (exit_price, realized_pnl, signal_id),
        )

    def set_hypothetical_pnl(self, signal_id: int, hypothetical_pnl: float) -> None:
        """Set hypothetical P&L for a missed signal.

        Args:
            signal_id: FK to ``strategy_results.id``.
            hypothetical_pnl: What the trade would have returned if taken.
        """
        self.execute(
            """
            UPDATE signal_performance_tracking
               SET hypothetical_pnl = ?,
                   tracking_status = 'expired',
                   evaluated_at = CURRENT_TIMESTAMP
             WHERE signal_id = ?
               AND was_taken = FALSE
               AND tracking_status = 'missed'
            """,
            (hypothetical_pnl, signal_id),
        )

    def get_signal_performance(
        self,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict]:
        """Retrieve signal performance tracking records with optional filters.

        Args:
            strategy: Filter by strategy_name.
            symbol: Filter by symbol.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            limit: Maximum rows to return.

        Returns:
            List of row dicts.
        """
        clauses = []
        params: list = []
        if strategy:
            clauses.append("strategy_name = ?")
            params.append(strategy)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if start_date:
            clauses.append("signal_timestamp >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("signal_timestamp <= ?")
            params.append(end_date)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        df = self.fetch_df(
            f"SELECT * FROM signal_performance_tracking {where} "
            "ORDER BY signal_timestamp DESC LIMIT ?",
            tuple(params),
        )
        return [] if df.empty else df.to_dict(orient="records")

    # ------------------------------------------------------------------
    # hypothetical_portfolios
    # ------------------------------------------------------------------

    def upsert_hypothetical(
        self,
        snapshot_date: date,
        strategy_name: str,
        symbol: str,
        hypothetical_value: float,
        actual_value: float,
        signals_taken: int,
        signals_missed: int,
        opportunity_pnl: float,
    ) -> None:
        """Insert or replace a hypothetical portfolio row for a given date.

        Args:
            snapshot_date: Date of the snapshot.
            strategy_name: Strategy name.
            symbol: Ticker.
            hypothetical_value: Portfolio value if all signals were taken.
            actual_value: Actual portfolio value.
            signals_taken: Count of signals that were approved.
            signals_missed: Count of signals that were rejected/expired.
            opportunity_pnl: PnL difference (hypothetical - actual).
        """
        self.execute(
            """
            INSERT OR REPLACE INTO hypothetical_portfolios
                (snapshot_date, strategy_name, symbol, hypothetical_value, actual_value,
                 signals_taken, signals_missed, opportunity_pnl, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                snapshot_date, strategy_name, symbol.upper(),
                hypothetical_value, actual_value,
                signals_taken, signals_missed, opportunity_pnl,
            ),
        )

    def get_hypothetical_vs_actual(self, snapshot_date: str) -> List[Dict]:
        """Retrieve hypothetical vs actual comparison for a given date.

        Args:
            snapshot_date: Date string (YYYY-MM-DD).

        Returns:
            List of row dicts.
        """
        df = self.fetch_df(
            "SELECT * FROM hypothetical_portfolios WHERE snapshot_date = ? "
            "ORDER BY strategy_name, symbol",
            (snapshot_date,),
        )
        return [] if df.empty else df.to_dict(orient="records")

    # ------------------------------------------------------------------
    # strategy_performance_summary
    # ------------------------------------------------------------------

    def upsert_strategy_summary(
        self,
        strategy_name: str,
        symbol: str,
        period_start: date,
        period_end: date,
        total_signals: int,
        signals_taken: int,
        win_rate: Optional[float],
        avg_return_per_trade: Optional[float],
        total_pnl: Optional[float],
        sharpe_ratio: Optional[float],
        max_drawdown_pct: Optional[float],
        best_trade_pnl: Optional[float],
        worst_trade_pnl: Optional[float],
    ) -> None:
        """Insert or replace a strategy performance summary row.

        Args:
            strategy_name: Strategy slug.
            symbol: Ticker.
            period_start: Start of the aggregation window.
            period_end: End of the aggregation window.
            total_signals: Total signals generated in the period.
            signals_taken: Signals that were approved and executed.
            win_rate: Fraction of taken trades that were profitable.
            avg_return_per_trade: Mean return per trade.
            total_pnl: Sum of realized P&L for the period.
            sharpe_ratio: Risk-adjusted return.
            max_drawdown_pct: Maximum drawdown as a percentage.
            best_trade_pnl: Largest single-trade gain.
            worst_trade_pnl: Largest single-trade loss.
        """
        self.execute(
            """
            INSERT OR REPLACE INTO strategy_performance_summary
                (strategy_name, symbol, period_start, period_end, total_signals,
                 signals_taken, win_rate, avg_return_per_trade, total_pnl,
                 sharpe_ratio, max_drawdown_pct, best_trade_pnl, worst_trade_pnl,
                 updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                strategy_name, symbol.upper(), period_start, period_end,
                total_signals, signals_taken, win_rate, avg_return_per_trade,
                total_pnl, sharpe_ratio, max_drawdown_pct,
                best_trade_pnl, worst_trade_pnl,
            ),
        )

    def get_strategy_breakdown(
        self,
        strategy: Optional[str] = None,
        period: str = "all",
    ) -> List[Dict]:
        """Retrieve strategy performance summaries.

        Args:
            strategy: Filter by strategy_name. None returns all.
            period: "weekly" | "monthly" | "all" — filters rows whose
                period_end is within the last 7/30 days or all time.

        Returns:
            List of row dicts ordered by period_end DESC.
        """
        clauses = []
        params: list = []

        if strategy:
            clauses.append("strategy_name = ?")
            params.append(strategy)

        if period == "weekly":
            clauses.append("period_end >= CURRENT_DATE - INTERVAL '7 days'")
        elif period == "monthly":
            clauses.append("period_end >= CURRENT_DATE - INTERVAL '30 days'")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        df = self.fetch_df(
            f"SELECT * FROM strategy_performance_summary {where} "
            "ORDER BY period_end DESC, strategy_name, symbol",
            tuple(params),
        )
        return [] if df.empty else df.to_dict(orient="records")
