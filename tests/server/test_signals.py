"""Tests for the Phase 25 HITL Signals router.

Covers all four endpoints:
    GET  /v1/strategy/signals/pending
    POST /v1/strategy/signals/{id}/approve
    POST /v1/strategy/signals/{id}/reject
    PATCH /v1/strategy/signals/{id}/modify

All StrategyDAO calls are mocked so no real database is touched.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Build a minimal app with just the signals router — avoids pulling in the
# full api.py lifespan / app_state machinery.
from src.server.routers.signals import router as signals_router

_app = FastAPI()
_app.include_router(signals_router)

client = TestClient(_app)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _pending_row(signal_id: int = 1, symbol: str = "AAPL") -> dict:
    """Return a minimal strategy_results row in 'pending_review' state."""
    return {
        "id": signal_id,
        "symbol": symbol,
        "strategy_name": "mean-reversion",
        "action": "buy",
        "confidence": 0.82,
        "status": "pending_review",
    }


def _approved_row(signal_id: int = 2) -> dict:
    return {**_pending_row(signal_id), "status": "approved"}


def _rejected_row(signal_id: int = 3) -> dict:
    return {**_pending_row(signal_id), "status": "rejected"}


def _mock_dao(
    fetch_one_return=None,
    fetch_df_return=None,
    execute_side_effect=None,
) -> MagicMock:
    """Build a mock StrategyDAO with configurable return values."""
    dao = MagicMock()
    dao.fetch_one.return_value = fetch_one_return
    dao.fetch_df.return_value = (
        fetch_df_return if fetch_df_return is not None else pd.DataFrame()
    )
    if execute_side_effect is not None:
        dao.execute.side_effect = execute_side_effect
    return dao


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _schema_already_done():
    """Mark schema migration as already completed for all non-migration tests.

    This prevents the 4 ALTER TABLE calls from `_ensure_hitl_schema` from
    polluting execute() call counts in endpoint tests.  Tests that specifically
    need migration to run (TestHITLSchemaInit) override this via their own
    class-level autouse fixture.
    """
    import src.server.routers.signals as _mod
    _mod._schema_ready = True
    yield
    _mod._schema_ready = True


# ===========================================================================
# GET /v1/strategy/signals/pending
# ===========================================================================


class TestGetPendingSignals:
    """GET /v1/strategy/signals/pending"""

    def test_empty_queue(self):
        """Returns empty list when no pending signals exist."""
        with patch("src.semi_auto.routers.signals._dao", return_value=_mock_dao()):
            resp = client.get("/v1/strategy/signals/pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body["signals"] == []
        assert body["count"] == 0

    def test_returns_pending_rows(self):
        """Returns correctly structured records for pending signals."""
        df = pd.DataFrame([
            {"id": 1, "symbol": "AAPL", "action": "buy", "status": "pending_review"},
            {"id": 2, "symbol": "TSLA", "action": "sell", "status": "pending_review"},
        ])
        with patch("src.semi_auto.routers.signals._dao", return_value=_mock_dao(fetch_df_return=df)):
            resp = client.get("/v1/strategy/signals/pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert body["signals"][0]["symbol"] == "AAPL"

    def test_dao_error_returns_500(self):
        """DAO exception propagates as HTTP 500."""
        dao = _mock_dao()
        dao.fetch_df.side_effect = RuntimeError("DB offline")
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.get("/v1/strategy/signals/pending")
        assert resp.status_code == 500


# ===========================================================================
# POST /v1/strategy/signals/{id}/approve
# ===========================================================================


class TestApproveSignal:
    """POST /v1/strategy/signals/{id}/approve"""

    def test_approve_pending_signal(self):
        """Approves a pending_review signal and returns confirmed status."""
        dao = _mock_dao(fetch_one_return=_pending_row(1))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.post("/v1/strategy/signals/1/approve")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["ok"] is True
        assert body["signal_id"] == 1
        dao.execute.assert_called_once()

    def test_approve_not_found_returns_404(self):
        """Returns 404 when signal ID does not exist."""
        dao = _mock_dao(fetch_one_return=None)
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.post("/v1/strategy/signals/999/approve")
        assert resp.status_code == 404

    def test_approve_already_approved_returns_422(self):
        """Cannot approve a signal already in 'approved' state."""
        dao = _mock_dao(fetch_one_return=_approved_row(2))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.post("/v1/strategy/signals/2/approve")
        assert resp.status_code == 422
        assert "approved" in resp.json()["detail"]

    def test_approve_rejected_signal_returns_422(self):
        """Cannot approve a signal that has already been rejected."""
        dao = _mock_dao(fetch_one_return=_rejected_row(3))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.post("/v1/strategy/signals/3/approve")
        assert resp.status_code == 422

    def test_approve_dao_execute_error_returns_500(self):
        """DAO execute failure propagates as HTTP 500."""
        dao = _mock_dao(fetch_one_return=_pending_row(1))
        dao.execute.side_effect = RuntimeError("write failed")
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.post("/v1/strategy/signals/1/approve")
        assert resp.status_code == 500


# ===========================================================================
# POST /v1/strategy/signals/{id}/reject
# ===========================================================================


class TestRejectSignal:
    """POST /v1/strategy/signals/{id}/reject"""

    def test_reject_without_note(self):
        """Rejects a pending signal with no note provided."""
        dao = _mock_dao(fetch_one_return=_pending_row(1))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.post("/v1/strategy/signals/1/reject")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"
        assert body["ok"] is True

    def test_reject_with_note(self):
        """Rejects a pending signal and persists the reviewer note."""
        dao = _mock_dao(fetch_one_return=_pending_row(1))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.post(
                "/v1/strategy/signals/1/reject",
                json={"reviewer_note": "Outside trading hours"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"
        # Verify the note was passed to execute
        call_args = dao.execute.call_args
        assert "Outside trading hours" in str(call_args)

    def test_reject_not_found_returns_404(self):
        """Returns 404 when signal ID does not exist."""
        dao = _mock_dao(fetch_one_return=None)
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.post("/v1/strategy/signals/99/reject")
        assert resp.status_code == 404

    def test_reject_already_rejected_returns_422(self):
        """Cannot reject a signal that is already rejected."""
        dao = _mock_dao(fetch_one_return=_rejected_row(3))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.post("/v1/strategy/signals/3/reject")
        assert resp.status_code == 422

    def test_reject_approved_signal_returns_422(self):
        """Cannot reject an already-approved signal."""
        dao = _mock_dao(fetch_one_return=_approved_row(2))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.post("/v1/strategy/signals/2/reject")
        assert resp.status_code == 422


# ===========================================================================
# PATCH /v1/strategy/signals/{id}/modify
# ===========================================================================


class TestModifySignal:
    """PATCH /v1/strategy/signals/{id}/modify"""

    def test_modify_pending_signal_qty(self):
        """Updates qty_override on a pending_review signal."""
        dao = _mock_dao(fetch_one_return=_pending_row(1))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.patch(
                "/v1/strategy/signals/1/modify",
                json={"qty_override": 50},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["new_qty"] == 50
        assert body["ok"] is True

    def test_modify_approved_signal_qty(self):
        """Updates qty_override on an already-approved signal."""
        dao = _mock_dao(fetch_one_return=_approved_row(2))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.patch(
                "/v1/strategy/signals/2/modify",
                json={"qty_override": 100, "reviewer_note": "Upsized to full allocation"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["new_qty"] == 100

    def test_modify_with_note(self):
        """Reviewer note is forwarded to DAO execute."""
        dao = _mock_dao(fetch_one_return=_pending_row(1))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            client.patch(
                "/v1/strategy/signals/1/modify",
                json={"qty_override": 25, "reviewer_note": "Half size only"},
            )
        call_args = dao.execute.call_args
        assert "Half size only" in str(call_args)

    def test_modify_rejected_signal_returns_422(self):
        """Cannot modify a rejected signal."""
        dao = _mock_dao(fetch_one_return=_rejected_row(3))
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.patch(
                "/v1/strategy/signals/3/modify",
                json={"qty_override": 10},
            )
        assert resp.status_code == 422

    def test_modify_not_found_returns_404(self):
        """Returns 404 when signal ID does not exist."""
        dao = _mock_dao(fetch_one_return=None)
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            resp = client.patch(
                "/v1/strategy/signals/999/modify",
                json={"qty_override": 10},
            )
        assert resp.status_code == 404

    def test_modify_qty_must_be_positive(self):
        """qty_override < 1 is rejected by Pydantic validation → 422."""
        resp = client.patch(
            "/v1/strategy/signals/1/modify",
            json={"qty_override": 0},
        )
        assert resp.status_code == 422

    def test_modify_missing_qty_returns_422(self):
        """Missing required qty_override field → 422."""
        resp = client.patch(
            "/v1/strategy/signals/1/modify",
            json={"reviewer_note": "no qty provided"},
        )
        assert resp.status_code == 422


# ===========================================================================
# Schema migration
# ===========================================================================


class TestHITLSchemaInit:
    """_ensure_hitl_schema runs ALTER TABLEs exactly once per process."""

    @pytest.fixture(autouse=True)
    def _reset_for_migration_tests(self):
        """Override the module-level autouse so migration tests start fresh."""
        import src.server.routers.signals as _mod
        _mod._schema_ready = False
        yield
        _mod._schema_ready = True

    def test_schema_migration_called_on_first_request(self):
        """_ensure_hitl_schema executes exactly four ALTER TABLE statements."""
        dao = _mock_dao()
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            client.get("/v1/strategy/signals/pending")
        # Four ALTER TABLE statements should have been executed
        assert dao.execute.call_count == 4

    def test_schema_migration_skipped_after_first_call(self):
        """Schema migration is skipped on subsequent requests."""
        import src.server.routers.signals as _mod
        _mod._schema_ready = True  # Simulate already migrated

        dao = _mock_dao()
        with patch("src.semi_auto.routers.signals._dao", return_value=dao):
            client.get("/v1/strategy/signals/pending")
        # No ALTER TABLE calls because _schema_ready was True
        assert dao.execute.call_count == 0


# ===========================================================================
# Model validation
# ===========================================================================


class TestSignalModels:
    """Pydantic model validation for signals endpoint models."""

    def test_signal_review_response_has_timestamp(self):
        from src.server.models.endpoints import SignalReviewResponse
        r = SignalReviewResponse(
            signal_id=1, status="approved", ok=True, message="done", timestamp="2026-03-31T00:00:00+00:00"
        )
        assert r.status == "approved"
        assert r.ok is True

    def test_signal_reject_request_note_optional(self):
        from src.server.models.endpoints import SignalRejectRequest
        r = SignalRejectRequest()
        assert r.reviewer_note is None

    def test_signal_modify_request_requires_positive_qty(self):
        from src.server.models.endpoints import SignalModifyRequest
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            SignalModifyRequest(qty_override=0)

    def test_signal_modify_response_fields(self):
        from src.server.models.endpoints import SignalModifyResponse
        r = SignalModifyResponse(
            signal_id=5, new_qty=100, ok=True, message="Updated", timestamp="2026-03-31T00:00:00+00:00"
        )
        assert r.new_qty == 100

    def test_hitl_enabled_flag(self):
        """_hitl_enabled reads from config correctly."""
        from src.server.routers.signals import _hitl_enabled
        # Config has "strategy.hitl.enabled": true
        assert isinstance(_hitl_enabled(), bool)
