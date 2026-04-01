"""HITL Signals router — review, approve, reject, and modify strategy signals.

Gates are controlled by ``strategy.hitl.enabled`` in ``config/config.json``.
When disabled all signals are saved with ``status='auto'`` and these endpoints
still work but the pending queue will always be empty.

Endpoints:
    GET  /v1/strategy/signals/pending          — signals awaiting human review
    POST /v1/strategy/signals/{id}/approve     — approve (Phase 26 will trigger order)
    POST /v1/strategy/signals/{id}/reject      — reject with optional reviewer note
    PATCH /v1/strategy/signals/{id}/modify     — change qty_override + note

Schema migration:
    On first call to any endpoint, four columns are idempotently added to
    ``strategy_results`` via ``ALTER TABLE … ADD COLUMN IF NOT EXISTS``:
    - status VARCHAR DEFAULT 'auto'
    - reviewed_at TIMESTAMP
    - reviewer_note VARCHAR
    - qty_override INTEGER
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, HTTPException

from src.common.utils import config as app_config, get_logger
from src.semi_auto.models.endpoints import (
    PendingSignalsResponse,
    SignalModifyRequest,
    SignalModifyResponse,
    SignalRejectRequest,
    SignalReviewResponse,
)
from src.semi_auto.routers._helpers import _df_to_records

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/strategy/signals", tags=["signals-hitl"])

# ---------------------------------------------------------------------------
# Module-level flag so migration runs exactly once per process lifetime.
# ---------------------------------------------------------------------------
_schema_ready: bool = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dao():
    """Return a fresh StrategyDAO bound to the default analysis DB."""
    from src.common.dao.strategy_dao import StrategyDAO
    return StrategyDAO()


def _ensure_hitl_schema() -> None:
    """Idempotently add HITL columns to strategy_results.

    Safe to call on every request — skipped after the first successful run.
    Uses DuckDB's ``ADD COLUMN IF NOT EXISTS`` so re-running against a DB that
    already has the columns is a no-op.
    """
    global _schema_ready
    if _schema_ready:
        return

    _alters = [
        "ALTER TABLE strategy_results ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'auto'",
        "ALTER TABLE strategy_results ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP",
        "ALTER TABLE strategy_results ADD COLUMN IF NOT EXISTS reviewer_note VARCHAR",
        "ALTER TABLE strategy_results ADD COLUMN IF NOT EXISTS qty_override INTEGER",
    ]
    try:
        dao = _dao()
        for stmt in _alters:
            dao.execute(stmt)
        dao.close()
        _schema_ready = True
        logger.info("[signals] HITL schema columns ensured on strategy_results")
    except Exception as exc:
        logger.warning(f"[signals] HITL schema migration warning (will retry): {exc}")


def _hitl_enabled() -> bool:
    """Return True when HITL review gate is active per config."""
    return bool(app_config.get("strategy.hitl.enabled", False))


def _get_signal_row(dao, signal_id: int) -> Optional[dict]:
    """Fetch a single strategy_results row by primary key.

    Args:
        dao: Open StrategyDAO instance.
        signal_id: Integer primary key.

    Returns:
        Row dict or None if not found.
    """
    return dao.fetch_one(
        "SELECT id, status, symbol, strategy_name, action, confidence FROM strategy_results WHERE id = ?",
        (signal_id,),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/pending", response_model=PendingSignalsResponse)
async def get_pending_signals():
    """Return all strategy signals awaiting human review.

    Only returns rows with ``status='pending_review'``, ordered newest-first.
    Returns an empty list when HITL is disabled or no signals are pending.

    Returns:
        Dict with ``signals`` list and ``count``.
    """
    _ensure_hitl_schema()
    try:
        dao = _dao()
        df = dao.fetch_df(
            "SELECT * FROM strategy_results WHERE status = 'pending_review' ORDER BY created_at DESC",
            (),
        )
        dao.close()
        records = _df_to_records(df)
        return {"signals": records, "count": len(records)}
    except Exception as exc:
        logger.warning(f"[signals/pending] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{signal_id}/approve", response_model=SignalReviewResponse)
async def approve_signal(signal_id: int):
    """Approve a pending signal.

    Sets ``status='approved'`` and records ``reviewed_at`` timestamp.
    Only signals currently in ``status='pending_review'`` can be approved.

    .. note::
        Phase 26 (trading node) will hook into this endpoint to submit the
        order to the broker immediately after approval.

    Args:
        signal_id: Primary key of the signal row in ``strategy_results``.

    Returns:
        ``SignalReviewResponse`` confirmation with new status and timestamp.

    Raises:
        404: Signal not found or not in ``pending_review`` state.
    """
    _ensure_hitl_schema()
    now_dt = datetime.now(timezone.utc)
    now_ts = now_dt.isoformat()
    try:
        dao = _dao()
        row = _get_signal_row(dao, signal_id)
        if row is None:
            dao.close()
            raise HTTPException(
                status_code=404,
                detail=f"Signal {signal_id} not found.",
            )
        if row.get("status") != "pending_review":
            dao.close()
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Signal {signal_id} is in state '{row.get('status')}' — "
                    "only 'pending_review' signals can be approved."
                ),
            )
        dao.execute(
            "UPDATE strategy_results SET status = 'approved', reviewed_at = ? WHERE id = ?",
            (now_dt, signal_id),
        )
        dao.close()
        logger.info(
            f"[signals] Approved signal {signal_id} "
            f"({row.get('symbol')} / {row.get('strategy_name')} / {row.get('action')})"
        )

        # ── Phase 26: submit live order and persist to live_orders ──────
        order_result: dict = {}
        order_error: str = ""
        try:
            from src.semi_auto.skills.portfolio.skills import portfolio_skills
            from src.common.dao.orders_dao import OrdersDAO

            symbol = row.get("symbol", "")
            action = row.get("action", "hold")
            confidence = float(row.get("confidence") or 1.0)

            if action in ("buy", "sell"):
                order_result = portfolio_skills.execute_strategy_signal(
                    symbol=symbol,
                    signal=action,
                    confidence=confidence,
                )
                # Persist to live_orders
                inner_order = order_result.get("order") or {}
                broker_id = inner_order.get("id", "")
                qty = inner_order.get("qty", 0)
                if broker_id:
                    o_dao = OrdersDAO()
                    o_dao.save_order(
                        symbol=symbol,
                        side=action,
                        qty=int(qty),
                        broker_order_id=broker_id,
                        order_type=inner_order.get("type", "market"),
                        signal_id=signal_id,
                    )
                    o_dao.close()
        except Exception as order_exc:
            order_error = str(order_exc)
            logger.warning(f"[signals/{signal_id}/approve] order submission failed: {order_exc}")

        return {
            "signal_id": signal_id,
            "status": "approved",
            "ok": True,
            "message": (
                f"Signal {signal_id} approved and order submitted."
                if not order_error
                else f"Signal {signal_id} approved but order failed: {order_error}"
            ),
            "order": order_result or None,
            "timestamp": now_ts,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"[signals/{signal_id}/approve] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{signal_id}/reject", response_model=SignalReviewResponse)
async def reject_signal(
    signal_id: int,
    body: Optional[SignalRejectRequest] = Body(default=None),
):
    """Reject a pending signal with an optional reviewer note.

    Sets ``status='rejected'``, records ``reviewed_at`` timestamp, and
    persists the ``reviewer_note`` if provided.

    Args:
        signal_id: Primary key of the signal row.
        body: Optional ``SignalRejectRequest`` carrying ``reviewer_note``.

    Returns:
        ``SignalReviewResponse`` confirmation.

    Raises:
        404: Signal not found or not in ``pending_review`` state.
    """
    _ensure_hitl_schema()
    note = (body.reviewer_note if body and body.reviewer_note else "") or ""
    now_dt = datetime.now(timezone.utc)
    now_ts = now_dt.isoformat()
    try:
        dao = _dao()
        row = _get_signal_row(dao, signal_id)
        if row is None:
            dao.close()
            raise HTTPException(
                status_code=404,
                detail=f"Signal {signal_id} not found.",
            )
        if row.get("status") != "pending_review":
            dao.close()
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Signal {signal_id} is in state '{row.get('status')}' — "
                    "only 'pending_review' signals can be rejected."
                ),
            )
        dao.execute(
            "UPDATE strategy_results SET status = 'rejected', reviewed_at = ?, reviewer_note = ? WHERE id = ?",
            (now_dt, note or None, signal_id),
        )
        dao.close()
        logger.info(f"[signals] Rejected signal {signal_id} — note: {note!r}")
        return {
            "signal_id": signal_id,
            "status": "rejected",
            "ok": True,
            "message": f"Signal {signal_id} rejected.",
            "timestamp": now_ts,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"[signals/{signal_id}/reject] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/{signal_id}/modify", response_model=SignalModifyResponse)
async def modify_signal(signal_id: int, body: SignalModifyRequest):
    """Override share quantity and/or add a reviewer note on a pending or approved signal.

    Modifiable states: ``'pending_review'``, ``'approved'``.
    The ``qty_override`` will be used by the Phase 26 order layer instead of
    the auto-sized quantity from the signal engine.

    Args:
        signal_id: Primary key of the signal row.
        body: ``SignalModifyRequest`` with required ``qty_override ≥ 1`` and
              optional ``reviewer_note``.

    Returns:
        ``SignalModifyResponse`` confirmation with new quantity and timestamp.

    Raises:
        404: Signal not found or not in a modifiable state.
    """
    _ensure_hitl_schema()
    note = body.reviewer_note or ""
    now_dt = datetime.now(timezone.utc)
    now_ts = now_dt.isoformat()
    try:
        dao = _dao()
        row = _get_signal_row(dao, signal_id)
        if row is None:
            dao.close()
            raise HTTPException(
                status_code=404,
                detail=f"Signal {signal_id} not found.",
            )
        if row.get("status") not in ("pending_review", "approved"):
            dao.close()
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Signal {signal_id} is in state '{row.get('status')}' — "
                    "only 'pending_review' or 'approved' signals can be modified."
                ),
            )
        dao.execute(
            "UPDATE strategy_results SET qty_override = ?, reviewer_note = ? WHERE id = ?",
            (body.qty_override, note or None, signal_id),
        )
        dao.close()
        logger.info(
            f"[signals] Modified signal {signal_id} qty_override={body.qty_override} note={note!r}"
        )
        return {
            "signal_id": signal_id,
            "new_qty": body.qty_override,
            "ok": True,
            "message": f"Signal {signal_id} quantity updated to {body.qty_override}.",
            "timestamp": now_ts,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"[signals/{signal_id}/modify] {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    """Smoke-test the HITL schema migration and helper utilities."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

    print("=" * 60)
    print("Signals router — schema migration smoke-test")
    print("=" * 60)

    _ensure_hitl_schema()
    print(f"HITL enabled: {_hitl_enabled()}")

    dao = _dao()
    cols = dao.fetch_df(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'strategy_results'",
        (),
    )
    dao.close()
    hitl_cols = [c for c in cols["column_name"].tolist() if c in ("status", "reviewed_at", "reviewer_note", "qty_override")]
    print(f"HITL columns present: {hitl_cols}")
    assert set(hitl_cols) == {"status", "reviewed_at", "reviewer_note", "qty_override"}, \
        "Missing HITL columns!"
    print("OK: All HITL columns present")
    print("=" * 60)
