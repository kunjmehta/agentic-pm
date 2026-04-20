"""Order lifecycle business logic — no FastAPI dependency."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    """Result of a fill-reconciliation pass.

    Attributes:
        reconciled_count: Orders whose status was updated (filled/cancelled/expired).
        skipped_count: Local orders with no matching broker record.
        signals_updated: ``strategy_results`` rows set to ``filled``.
        timestamp: ISO-8601 UTC timestamp of the reconciliation run.
    """

    reconciled_count: int
    skipped_count: int
    signals_updated: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _reconcile_sync() -> ReconcileResult:
    """Execute the full reconciliation pass synchronously.

    Intended to be called via ``asyncio.to_thread`` so all blocking DAO and
    HTTP operations stay off the event loop.

    Returns:
        ReconcileResult with counts and timestamp.
    """
    from src.common.dao import OrdersDAO
    from src.common.dao.strategy_dao import StrategyDAO
    from src.common.external.alpaca_portfolio import fetch_orders

    orders_dao = OrdersDAO()
    try:
        submitted = orders_dao.get_submitted_orders()

        if not submitted:
            return ReconcileResult(0, 0, 0)

        # Fetch recent closed orders from Alpaca (covers fills + cancellations).
        broker_orders = fetch_orders(status="closed", limit=200)
        broker_map: dict[str, dict] = {o["id"]: o for o in broker_orders}

        reconciled = 0
        skipped = 0
        signal_ids_filled: list[str] = []

        for row in submitted:
            bid = row.get("broker_order_id")
            if not bid or bid not in broker_map:
                skipped += 1
                continue

            alpaca_order = broker_map[bid]
            alpaca_status = alpaca_order.get("status", "")

            if alpaca_status == "filled":
                filled_at_raw = alpaca_order.get("filled_at")
                filled_at = (
                    datetime.fromisoformat(filled_at_raw.replace("Z", "+00:00"))
                    if filled_at_raw
                    else datetime.now(timezone.utc)
                )
                filled_price = float(alpaca_order.get("filled_avg_price") or 0.0)
                orders_dao.update_fill(
                    broker_order_id=bid,
                    filled_at=filled_at,
                    filled_price=filled_price,
                )
                if row.get("signal_id"):
                    signal_ids_filled.append(row["signal_id"])
                reconciled += 1
            elif alpaca_status in ("canceled", "expired", "rejected"):
                orders_dao.update_status(broker_order_id=bid, status=alpaca_status)
                reconciled += 1

    finally:
        orders_dao.close()

    # Propagate fill status to strategy_results for linked signals — single batch query.
    signals_updated = 0
    if signal_ids_filled:
        s_dao = StrategyDAO()
        try:
            placeholders = ", ".join("?" * len(signal_ids_filled))
            s_dao.execute(
                f"UPDATE strategy_results SET status = 'filled' WHERE id IN ({placeholders})",
                signal_ids_filled,
            )
            signals_updated = len(signal_ids_filled)
        finally:
            s_dao.close()

    logger.info(
        f"[reconcile] done: reconciled={reconciled} skipped={skipped} "
        f"signals_updated={signals_updated}"
    )
    return ReconcileResult(reconciled, skipped, signals_updated)


async def reconcile_submitted_orders() -> ReconcileResult:
    """Reconcile local submitted orders against Alpaca broker state.

    Fetches all ``live_orders`` with ``status='submitted'``, queries Alpaca
    for their current broker state, and updates ``filled_at`` / ``filled_price`` /
    ``status`` for any that have been filled or cancelled/expired/rejected.

    Also propagates ``status='filled'`` back to ``strategy_results`` for
    orders linked to a signal via ``signal_id``.

    All blocking DAO and HTTP calls are delegated to a thread via
    ``asyncio.to_thread`` so the event loop is never stalled.

    Returns:
        ReconcileResult with counts and timestamp.
    """
    return await asyncio.to_thread(_reconcile_sync)


if __name__ == "__main__":
    """Smoke test: verify module imports and dataclass construction."""
    print("=" * 60)
    print("services/order_service.py smoke test")
    print("=" * 60)

    # Verify dataclass construction
    r = ReconcileResult(reconciled_count=3, skipped_count=1, signals_updated=2)
    assert r.reconciled_count == 3
    assert r.skipped_count == 1
    assert r.signals_updated == 2
    assert r.timestamp  # default factory populated
    print(f"  [OK]  ReconcileResult: {r}")

    # Verify function is a coroutine
    import inspect
    assert inspect.iscoroutinefunction(reconcile_submitted_orders), \
        "reconcile_submitted_orders must be a coroutine (async def)"
    print("  [OK]  reconcile_submitted_orders is a coroutine")

    # Verify _reconcile_sync is a plain callable (not a coroutine)
    assert callable(_reconcile_sync) and not inspect.iscoroutinefunction(_reconcile_sync), \
        "_reconcile_sync must be a plain sync function"
    print("  [OK]  _reconcile_sync is a plain sync function")

    print("\n[ALL OK] services/order_service.py smoke test passed")
    print("=" * 60)
