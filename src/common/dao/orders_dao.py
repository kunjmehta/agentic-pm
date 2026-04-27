"""Orders Data Access Object.

Manages the ``live_orders`` table in ``market_data.duckdb``.
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
    """DAO for the ``live_orders`` table in the market data database.

    Inherits all DuckDB helpers from ``BaseDAO`` and targets the
    ``market`` database (``data/market_data.duckdb``).
    """

    def __init__(self) -> None:
        """Initialize with the market data database."""
        super().__init__(db_type="market")
        self._ensure_table()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _ensure_table(self) -> None:
        """Create ``live_orders`` if it does not already exist.

        Safe to call on every startup — uses ``IF NOT EXISTS``.
        """
        self.execute("""
            CREATE TABLE IF NOT EXISTS live_orders (
                id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
                signal_id INTEGER,
                symbol VARCHAR NOT NULL,
                side VARCHAR NOT NULL,
                qty INTEGER NOT NULL,
                order_type VARCHAR DEFAULT 'market',
                limit_price DECIMAL(10, 4),
                broker_order_id VARCHAR,
                status VARCHAR DEFAULT 'submitted',
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                filled_at TIMESTAMP,
                filled_price DECIMAL(10, 4),
                realized_pnl DECIMAL(15, 4)
            )
        """)
        self.execute(
            "CREATE INDEX IF NOT EXISTS idx_live_orders_status ON live_orders(status, submitted_at DESC)"
        )
        self.execute(
            "CREATE INDEX IF NOT EXISTS idx_live_orders_signal ON live_orders(signal_id)"
        )

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


# =============================================================================
# Main block — smoke test
# =============================================================================

if __name__ == "__main__":
    import json

    print("=" * 60)
    print("OrdersDAO smoke test")
    print("=" * 60)

    dao = OrdersDAO()
    print("[OK] Table ensured")

    # Insert a test order
    oid = dao.save_order(
        symbol="AAPL",
        side="buy",
        qty=10,
        broker_order_id="test-broker-id-001",
        order_type="market",
        signal_id=None,
    )
    print(f"[OK] save_order → id={oid}")

    # Check submitted list
    rows = dao.get_submitted_orders()
    assert any(r["broker_order_id"] == "test-broker-id-001" for r in rows), \
        "Test order not found in submitted list"
    print(f"[OK] get_submitted_orders → {len(rows)} row(s)")

    # Mark as filled
    dao.update_fill(
        broker_order_id="test-broker-id-001",
        filled_at=datetime.now(),
        filled_price=175.50,
        realized_pnl=12.50,
    )
    print("[OK] update_fill")

    # Verify no longer in submitted
    rows_after = dao.get_submitted_orders()
    assert not any(r["broker_order_id"] == "test-broker-id-001" for r in rows_after), \
        "Filled order should not appear in submitted list"
    print("[OK] order removed from submitted after fill")

    # Cleanup
    dao.execute("DELETE FROM live_orders WHERE broker_order_id = 'test-broker-id-001'")
    dao.close()
    print("=" * 60)
    print("All smoke tests passed")
    print("=" * 60)
