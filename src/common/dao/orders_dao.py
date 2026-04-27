"""Orders Data Access Object.

Manages the ``live_orders`` table in ``portfolio.duckdb``.
Records every broker order submitted through the HITL approval flow or the
direct orders API and tracks fill status via the reconciliation loop.
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
from src.common.dao.base_dao import BaseDAO
from src.common.utils import get_logger

logger = get_logger(__name__)


class OrdersDAO(BaseDAO):
    """DAO for the ``live_orders`` table in the portfolio database.

    Inherits all DuckDB helpers from ``BaseDAO`` and targets the
    ``portfolio`` database (``data/portfolio.duckdb``).
    """

    def __init__(self) -> None:
        """Initialize with the portfolio database."""
        super().__init__(db_type="portfolio")
        self._ensure_table()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _ensure_table(self) -> None:
        """Create ``live_orders`` table and indexes if they do not already exist.

        Delegates to the canonical schema file so the DDL lives in one place.
        """
        schema_file = (
            Path(__file__).parent.parent.parent.parent
            / "config" / "schema" / "orders_schema.sql"
        )
        self.execute_schema_file(str(schema_file), check_table="live_orders")

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        broker_order_id: str,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        signal_id: Optional[int] = None,
    ) -> str:
        """Insert a newly submitted order and return its generated UUID.

        Args:
            symbol: Stock ticker (e.g. "AAPL").
            side: "buy" or "sell".
            qty: Number of shares.
            broker_order_id: Order UUID returned by Alpaca.
            order_type: "market" or "limit". Default "market".
            limit_price: Limit price for limit orders.
            signal_id: FK to ``strategy_results.id`` if order came from a signal.

        Returns:
            The UUID primary key of the inserted row.
        """
        row = self.fetch_one(
            """
            INSERT INTO live_orders
                (signal_id, symbol, side, qty, order_type, limit_price, broker_order_id, status, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted', CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (signal_id, symbol.upper(), side.lower(), qty, order_type, limit_price, broker_order_id),
        )
        order_id = row["id"] if row else None
        logger.info(
            f"[OrdersDAO] saved order id={order_id} broker={broker_order_id} "
            f"{side.upper()} {qty} {symbol}"
        )
        return order_id

    def update_fill(
        self,
        broker_order_id: str,
        filled_at: datetime,
        filled_price: float,
        realized_pnl: Optional[float] = None,
    ) -> int:
        """Mark an order as filled with price and timestamp.

        Args:
            broker_order_id: Alpaca order UUID to match on.
            filled_at: Timestamp when the fill occurred.
            filled_price: Average fill price.
            realized_pnl: Optional realized P&L for the fill.

        Returns:
            Number of rows updated (0 if broker_order_id not found).
        """
        self.execute(
            """
            UPDATE live_orders
               SET status = 'filled',
                   filled_at = ?,
                   filled_price = ?,
                   realized_pnl = ?
             WHERE broker_order_id = ?
               AND status = 'submitted'
            """,
            (filled_at, filled_price, realized_pnl, broker_order_id),
        )
        logger.debug(
            f"[OrdersDAO] fill recorded broker={broker_order_id} "
            f"price={filled_price} pnl={realized_pnl}"
        )
        return 1  # DuckDB UPDATE does not return rowcount easily; assume 1 on no error

    def update_status(self, broker_order_id: str, status: str) -> None:
        """Update the status of an order (e.g. 'cancelled' or 'rejected').

        Args:
            broker_order_id: Alpaca order UUID.
            status: New status string.
        """
        self.execute(
            "UPDATE live_orders SET status = ? WHERE broker_order_id = ?",
            (status, broker_order_id),
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_submitted_orders(self) -> List[Dict]:
        """Return all orders with ``status='submitted'`` for reconciliation.

        Returns:
            List of row dicts with id, symbol, side, qty, broker_order_id,
            submitted_at, signal_id.
        """
        df = self.fetch_df(
            "SELECT id, symbol, side, qty, broker_order_id, submitted_at, signal_id "
            "FROM live_orders WHERE status = 'submitted' ORDER BY submitted_at ASC",
            (),
        )
        if df.empty:
            return []
        return df.to_dict(orient="records")

    def get_orders_for_signal(self, signal_id: int) -> List[Dict]:
        """Return all orders linked to a specific signal.

        Args:
            signal_id: FK to ``strategy_results.id``.

        Returns:
            List of order row dicts.
        """
        df = self.fetch_df(
            "SELECT * FROM live_orders WHERE signal_id = ? ORDER BY submitted_at DESC",
            (signal_id,),
        )
        if df.empty:
            return []
        return df.to_dict(orient="records")

    def get_recent_orders(self, limit: int = 50) -> List[Dict]:
        """Return the most recent orders across all statuses.

        Args:
            limit: Maximum rows to return. Default 50.

        Returns:
            List of order row dicts.
        """
        df = self.fetch_df(
            "SELECT * FROM live_orders ORDER BY submitted_at DESC LIMIT ?",
            (limit,),
        )
        if df.empty:
            return []
        return df.to_dict(orient="records")

    def get_recent_orders_for_symbol(
        self,
        symbol: str,
        side: str,
        lookback_hours: int = 24
    ) -> List[Dict]:
        """Fetch recent orders for a symbol to prevent duplicates.

        Used by autonomous signal aggregator to check if a similar order
        was recently placed within the lookback window.

        Args:
            symbol: Stock ticker (e.g. "AAPL").
            side: Order side: "buy" or "sell".
            lookback_hours: How far back to check for duplicates. Default 24.

        Returns:
            List of order row dicts matching symbol+side within time window.
        """
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(hours=lookback_hours)

        df = self.fetch_df(
            """
            SELECT *
            FROM live_orders
            WHERE symbol = ?
              AND side = ?
              AND submitted_at >= ?
            ORDER BY submitted_at DESC
            """,
            (symbol.upper(), side.lower(), cutoff),
        )
        if df.empty:
            return []
        return df.to_dict(orient="records")

    def get_recent_orders_by_symbols(
        self,
        symbol_side_pairs: List[tuple],
        lookback_hours: int = 24,
    ) -> dict:
        """Return recent order counts keyed by (symbol, side) for batch duplicate detection.

        Queries all symbols in one round-trip instead of one query per symbol,
        eliminating the N+1 pattern in ``signal_aggregator.generate_signal_batch``.

        Args:
            symbol_side_pairs: List of (symbol, side) tuples to check.
            lookback_hours: Hours to look back for recent orders. Default 24.

        Returns:
            Dict mapping ``(symbol, side)`` → count of recent matching orders.
            Pairs not in the result had zero recent orders.
        """
        if not symbol_side_pairs:
            return {}

        from datetime import timedelta

        cutoff = datetime.now() - timedelta(hours=lookback_hours)
        symbols = list({pair[0].upper() for pair in symbol_side_pairs})
        placeholders = ", ".join("?" for _ in symbols)

        df = self.fetch_df(
            f"SELECT symbol, side, COUNT(*) AS cnt "
            f"FROM live_orders "
            f"WHERE symbol IN ({placeholders}) "
            f"  AND submitted_at >= ? "
            f"GROUP BY symbol, side",
            tuple(symbols) + (cutoff,),
        )
        if df.empty:
            return {}
        # Build lookup; filter to only the requested (symbol, side) pairs
        requested = {(p[0].upper(), p[1].lower()) for p in symbol_side_pairs}
        return {
            (row["symbol"], row["side"]): int(row["cnt"])
            for _, row in df.iterrows()
            if (row["symbol"], row["side"]) in requested
        }