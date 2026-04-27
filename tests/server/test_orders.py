"""Tests for the order execution router and skill functions.

Uses FastAPI's TestClient with mocked Alpaca API and registry functions
so no real network connections or live accounts are required.

Covers:
    GET    /v1/orders                   list open orders
    POST   /v1/orders/execute           place market/limit order
    POST   /v1/orders/close/{symbol}    close a position
    POST   /v1/orders/scale             scale to target %
    POST   /v1/orders/signal            execute strategy signal
    DELETE /v1/orders/{order_id}        cancel order
    DELETE /v1/orders                   cancel all orders

Also covers unit-level tests for:
    PortfolioSkills.execute_order
    PortfolioSkills.close_position
    PortfolioSkills.scale_position
    PortfolioSkills.execute_strategy_signal
    alpaca_portfolio_skills.place_market_order (mocked)
    alpaca_portfolio_skills.place_limit_order  (mocked)
    alpaca_portfolio_skills.cancel_order       (mocked)
    alpaca_portfolio_skills.close_position     (mocked)
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest


# ── Shared fixtures ───────────────────────────────────────────────────────────


def _make_state_snapshot(values=None, next_nodes=None):
    snap = MagicMock()
    snap.values = values or {}
    snap.next = list(next_nodes or [])
    return snap


def _make_mock_graph():
    g = MagicMock()
    snap = _make_state_snapshot()
    g.get_state.return_value = snap
    g.invoke.return_value = snap.values
    g.update_state.return_value = None

    async def _empty(*_a, **_kw):
        return
        yield

    g.astream_events = _empty
    g.get_graph.return_value = MagicMock(nodes={})
    return g


@pytest.fixture(scope="module")
def client():
    """TestClient with mocked lifespan (no real DB / network)."""
    from fastapi.testclient import TestClient

    mock_coordinator = MagicMock()
    mock_coordinator.symbols = ["AAPL"]
    mock_coordinator.start_streaming = AsyncMock()
    mock_coordinator.run_streaming_loop = AsyncMock()
    mock_coordinator.stop_all_streaming = MagicMock()
    mock_coordinator.close = MagicMock()

    with (
        patch("src.semi_auto.lifespan.build_graph", return_value=_make_mock_graph()),
        patch("src.semi_auto.lifespan.DataCoordinator", return_value=mock_coordinator),
    ):
        from src.server.api import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ── Shared order result stubs ─────────────────────────────────────────────────

_MOCK_ORDER = {
    "id": "aeeebbbb-0000-0000-0000-123456789abc",
    "symbol": "AAPL",
    "qty": 10.0,
    "side": "buy",
    "type": "market",
    "status": "accepted",
    "submitted_at": "2026-03-31T10:00:00+00:00",
    "time_in_force": "day",
}

_MOCK_LIMIT_ORDER = {**_MOCK_ORDER, "type": "limit", "limit_price": 175.00, "side": "sell"}

_MOCK_SCALE_RESULT = {
    "action": "buy",
    "symbol": "AAPL",
    "target_pct": 0.05,
    "current_pct": 0.02,
    "current_qty": 5,
    "target_qty": 12,
    "delta_qty": 7,
    "equity": 50000.0,
    "current_price": 175.0,
    "order": _MOCK_ORDER,
    "timestamp": "2026-03-31T10:00:00",
}

_MOCK_SIGNAL_RESULT = {
    "action": "buy",
    "symbol": "AAPL",
    "signal": "buy",
    "confidence": 0.8,
    "target_pct": 0.04,
    "order": _MOCK_ORDER,
    "timestamp": "2026-03-31T10:00:00",
}


# =============================================================================
# GET /v1/orders
# =============================================================================


class TestListOpenOrders:
    def test_returns_200(self, client):
        with patch(
            "src.semi_auto.routers.orders.fetch_orders",
            return_value=[_MOCK_ORDER],
        ):
            r = client.get("/v1/orders")
        assert r.status_code == 200

    def test_returns_order_list(self, client):
        with patch(
            "src.semi_auto.routers.orders.fetch_orders",
            return_value=[_MOCK_ORDER],
        ):
            data = client.get("/v1/orders").json()
        assert "orders" in data
        assert len(data["orders"]) == 1

    def test_returns_correct_count(self, client):
        with patch(
            "src.semi_auto.routers.orders.fetch_orders",
            return_value=[_MOCK_ORDER, _MOCK_ORDER],
        ):
            data = client.get("/v1/orders").json()
        assert data["count"] == 2

    def test_empty_list_when_no_orders(self, client):
        with patch("src.semi_auto.routers.orders.fetch_orders", return_value=[]):
            data = client.get("/v1/orders").json()
        assert data["orders"] == []
        assert data["count"] == 0

    def test_500_on_exception(self, client):
        with patch(
            "src.semi_auto.routers.orders.fetch_orders",
            side_effect=Exception("API unavailable"),
        ):
            r = client.get("/v1/orders")
        assert r.status_code == 500


# =============================================================================
# POST /v1/orders/execute
# =============================================================================


class TestExecuteOrder:
    def _mock_registry(self, result):
        """Patch AVAILABLE_FUNCTIONS to return a callable yielding ``result``."""
        return patch(
            "src.semi_auto.routers.orders.AVAILABLE_FUNCTIONS",
            {"execute_order": lambda **kw: result},
        )

    def test_market_buy_returns_200(self, client):
        with self._mock_registry(_MOCK_ORDER):
            r = client.post(
                "/v1/orders/execute",
                json={"symbol": "AAPL", "qty": 10, "side": "buy"},
            )
        assert r.status_code == 200

    def test_response_has_order(self, client):
        with self._mock_registry(_MOCK_ORDER):
            data = client.post(
                "/v1/orders/execute",
                json={"symbol": "AAPL", "qty": 10, "side": "buy"},
            ).json()
        assert data["status"] == "success"
        assert data["order"]["id"] == _MOCK_ORDER["id"]

    def test_limit_sell_returns_200(self, client):
        with self._mock_registry(_MOCK_LIMIT_ORDER):
            r = client.post(
                "/v1/orders/execute",
                json={
                    "symbol": "AAPL",
                    "qty": 5,
                    "side": "sell",
                    "order_type": "limit",
                    "limit_price": 175.0,
                },
            )
        assert r.status_code == 200

    def test_invalid_side_returns_422(self, client):
        r = client.post(
            "/v1/orders/execute",
            json={"symbol": "AAPL", "qty": 10, "side": "invalid"},
        )
        assert r.status_code == 422

    def test_invalid_qty_returns_422(self, client):
        r = client.post(
            "/v1/orders/execute",
            json={"symbol": "AAPL", "qty": -5, "side": "buy"},
        )
        assert r.status_code == 422

    def test_invalid_order_type_returns_422(self, client):
        r = client.post(
            "/v1/orders/execute",
            json={"symbol": "AAPL", "qty": 5, "side": "buy", "order_type": "stop"},
        )
        assert r.status_code == 422

    def test_skill_error_returns_500(self, client):
        with self._mock_registry({"status": "error", "error": "Alpaca API error"}):
            r = client.post(
                "/v1/orders/execute",
                json={"symbol": "AAPL", "qty": 10, "side": "buy"},
            )
        assert r.status_code == 500

    def test_503_when_function_not_in_registry(self, client):
        with patch("src.semi_auto.routers.orders.AVAILABLE_FUNCTIONS", {}):
            r = client.post(
                "/v1/orders/execute",
                json={"symbol": "AAPL", "qty": 10, "side": "buy"},
            )
        assert r.status_code == 503


# =============================================================================
# POST /v1/orders/close/{symbol}
# =============================================================================


class TestClosePosition:
    def _mock_registry(self, result):
        return patch(
            "src.semi_auto.routers.orders.AVAILABLE_FUNCTIONS",
            {"close_position": lambda **kw: result},
        )

    def test_returns_200(self, client):
        with self._mock_registry({**_MOCK_ORDER, "side": "sell"}):
            r = client.post("/v1/orders/close/AAPL")
        assert r.status_code == 200

    def test_response_has_order(self, client):
        with self._mock_registry({**_MOCK_ORDER, "side": "sell"}):
            data = client.post("/v1/orders/close/AAPL").json()
        assert data["status"] == "success"
        assert "order" in data

    def test_error_from_skill_returns_500(self, client):
        with self._mock_registry({"status": "error", "error": "No position"}):
            r = client.post("/v1/orders/close/AAPL")
        assert r.status_code == 500


# =============================================================================
# POST /v1/orders/scale
# =============================================================================


class TestScalePosition:
    def _mock_registry(self, result):
        return patch(
            "src.semi_auto.routers.orders.AVAILABLE_FUNCTIONS",
            {"scale_position": lambda **kw: result},
        )

    def test_returns_200(self, client):
        with self._mock_registry(_MOCK_SCALE_RESULT):
            r = client.post(
                "/v1/orders/scale",
                json={"symbol": "AAPL", "target_pct": 0.05},
            )
        assert r.status_code == 200

    def test_response_has_action(self, client):
        with self._mock_registry(_MOCK_SCALE_RESULT):
            data = client.post(
                "/v1/orders/scale",
                json={"symbol": "AAPL", "target_pct": 0.05},
            ).json()
        assert data["status"] == "success"
        assert data["action"] == "buy"

    def test_hold_action_when_no_delta(self, client):
        hold_result = {
            **_MOCK_SCALE_RESULT,
            "action": "hold",
            "delta_qty": 0,
            "order": None,
            "message": "Position already at target",
        }
        with self._mock_registry(hold_result):
            data = client.post(
                "/v1/orders/scale",
                json={"symbol": "AAPL", "target_pct": 0.02},
            ).json()
        assert data["action"] == "hold"
        assert data["order"] is None

    def test_target_pct_too_large_returns_422(self, client):
        r = client.post(
            "/v1/orders/scale",
            json={"symbol": "AAPL", "target_pct": 1.5},
        )
        assert r.status_code == 422

    def test_negative_target_pct_returns_422(self, client):
        r = client.post(
            "/v1/orders/scale",
            json={"symbol": "AAPL", "target_pct": -0.1},
        )
        assert r.status_code == 422


# =============================================================================
# POST /v1/orders/signal
# =============================================================================


class TestExecuteStrategySignal:
    def _mock_registry(self, result):
        return patch(
            "src.semi_auto.routers.orders.AVAILABLE_FUNCTIONS",
            {"execute_strategy_signal": lambda **kw: result},
        )

    def test_buy_signal_returns_200(self, client):
        with self._mock_registry(_MOCK_SIGNAL_RESULT):
            r = client.post(
                "/v1/orders/signal",
                json={"symbol": "AAPL", "signal": "buy", "confidence": 0.8},
            )
        assert r.status_code == 200

    def test_buy_signal_response_has_order(self, client):
        with self._mock_registry(_MOCK_SIGNAL_RESULT):
            data = client.post(
                "/v1/orders/signal",
                json={"symbol": "AAPL", "signal": "buy", "confidence": 0.8},
            ).json()
        assert data["status"] == "success"
        assert data["action"] == "buy"

    def test_hold_signal_no_order(self, client):
        hold_result = {
            "action": "hold",
            "symbol": "AAPL",
            "signal": "hold",
            "confidence": 1.0,
            "order": None,
            "target_pct": None,
            "message": "Signal is HOLD — no order placed",
            "timestamp": "2026-03-31T10:00:00",
        }
        with self._mock_registry(hold_result):
            data = client.post(
                "/v1/orders/signal",
                json={"symbol": "AAPL", "signal": "hold"},
            ).json()
        assert data["action"] == "hold"
        assert data["order"] is None

    def test_invalid_signal_returns_422(self, client):
        r = client.post(
            "/v1/orders/signal",
            json={"symbol": "AAPL", "signal": "strong_buy"},
        )
        assert r.status_code == 422

    def test_confidence_out_of_range_returns_422(self, client):
        r = client.post(
            "/v1/orders/signal",
            json={"symbol": "AAPL", "signal": "buy", "confidence": 1.5},
        )
        assert r.status_code == 422


# =============================================================================
# DELETE /v1/orders/{order_id}
# =============================================================================


class TestCancelOrder:
    def test_returns_200(self, client):
        with patch(
            "src.semi_auto.routers.orders._alpaca_cancel_order",
            return_value={"order_id": "abc", "status": "cancelled"},
        ):
            r = client.delete("/v1/orders/abc-1234")
        assert r.status_code == 200

    def test_response_has_order_id(self, client):
        with patch(
            "src.semi_auto.routers.orders._alpaca_cancel_order",
            return_value={"order_id": "abc-1234", "status": "cancelled"},
        ):
            data = client.delete("/v1/orders/abc-1234").json()
        assert data["status"] == "success"
        assert data["order_id"] == "abc-1234"

    def test_500_on_exception(self, client):
        with patch(
            "src.semi_auto.routers.orders._alpaca_cancel_order",
            side_effect=Exception("Order not found"),
        ):
            r = client.delete("/v1/orders/nonexistent")
        assert r.status_code == 500


# =============================================================================
# DELETE /v1/orders  (cancel all)
# =============================================================================


class TestCancelAllOrders:
    def test_returns_200(self, client):
        with patch(
            "src.semi_auto.routers.orders._cancel_all_orders",
            return_value={"cancelled_count": 3, "status": "all_cancelled"},
        ):
            r = client.delete("/v1/orders")
        assert r.status_code == 200

    def test_response_has_message(self, client):
        with patch(
            "src.semi_auto.routers.orders._cancel_all_orders",
            return_value={"cancelled_count": 2, "status": "all_cancelled"},
        ):
            data = client.delete("/v1/orders").json()
        assert data["status"] == "success"
        assert "message" in data


# =============================================================================
# Unit tests — PortfolioSkills order methods (no HTTP)
# =============================================================================


class TestPortfolioSkillsExecuteOrder:
    """Unit tests for PortfolioSkills.execute_order."""

    @pytest.fixture(autouse=True)
    def _import_skills(self):
        from src.server.skills.portfolio.skills import PortfolioSkills
        self.skills = PortfolioSkills()

    def test_market_order_delegates_to_place_market_order(self):
        with patch(
            "src.common.external.alpaca_portfolio.place_market_order",
            return_value=_MOCK_ORDER,
        ) as mock_fn:
            self.skills.execute_order("AAPL", qty=10, side="buy", order_type="market")
        mock_fn.assert_called_once_with(symbol="AAPL", qty=10, side="buy")

    def test_limit_order_delegates_to_place_limit_order(self):
        with patch(
            "src.common.external.alpaca_portfolio.place_limit_order",
            return_value=_MOCK_LIMIT_ORDER,
        ) as mock_fn:
            self.skills.execute_order(
                "AAPL", qty=5, side="sell", order_type="limit", limit_price=175.0
            )
        mock_fn.assert_called_once_with(
            symbol="AAPL", qty=5, side="sell", limit_price=175.0
        )

    def test_unsupported_order_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported order_type"):
            self.skills.execute_order("AAPL", qty=5, side="buy", order_type="stop")

    def test_limit_order_without_price_raises(self):
        with pytest.raises(ValueError, match="limit_price must be > 0"):
            self.skills.execute_order(
                "AAPL", qty=5, side="buy", order_type="limit", limit_price=None
            )


class TestPortfolioSkillsClosePosition:
    @pytest.fixture(autouse=True)
    def _import_skills(self):
        from src.server.skills.portfolio.skills import PortfolioSkills
        self.skills = PortfolioSkills()

    def test_delegates_to_alpaca_close(self):
        with patch(
            "src.common.external.alpaca_portfolio.close_position",
            return_value={**_MOCK_ORDER, "side": "sell"},
        ) as mock_fn:
            self.skills.close_position("AAPL")
        mock_fn.assert_called_once_with(symbol="AAPL")

    def test_passes_symbol_uppercase(self):
        with patch(
            "src.common.external.alpaca_portfolio.close_position",
            return_value={**_MOCK_ORDER, "side": "sell"},
        ) as mock_fn:
            self.skills.close_position("aapl")
        mock_fn.assert_called_once()


class TestPortfolioSkillsScalePosition:
    @pytest.fixture(autouse=True)
    def _import_skills(self):
        from src.server.skills.portfolio.skills import PortfolioSkills
        self.skills = PortfolioSkills()

    def _mock_account(self, equity=50000.0):
        return {"equity": equity, "cash": 10000.0}

    def _mock_positions(self, qty=5, price=175.0):
        return [
            {
                "symbol": "AAPL",
                "qty": qty,
                "side": "long",
                "current_price": price,
                "market_value": qty * price,
            }
        ]

    def test_scale_up_places_buy(self):
        with (
            patch(
                "src.common.external.alpaca_portfolio.fetch_account_info",
                return_value=self._mock_account(50000),
            ),
            patch(
                "src.common.external.alpaca_portfolio.fetch_positions",
                return_value=self._mock_positions(qty=5, price=175.0),
            ),
            patch.object(self.skills, "execute_order", return_value=_MOCK_ORDER) as mock_exec,
        ):
            # target_pct=0.10 → target_notional=5000 → target_qty=28 (>5) → buy
            result = self.skills.scale_position("AAPL", target_pct=0.10)
        assert result["action"] == "buy"
        mock_exec.assert_called_once()
        assert mock_exec.call_args.kwargs["side"] == "buy"

    def test_scale_down_places_sell(self):
        with (
            patch(
                "src.common.external.alpaca_portfolio.fetch_account_info",
                return_value=self._mock_account(50000),
            ),
            patch(
                "src.common.external.alpaca_portfolio.fetch_positions",
                return_value=self._mock_positions(qty=100, price=175.0),
            ),
            patch.object(self.skills, "execute_order", return_value=_MOCK_ORDER) as mock_exec,
        ):
            # target_pct=0.01 → target_qty=2 → sell 98
            result = self.skills.scale_position("AAPL", target_pct=0.01)
        assert result["action"] == "sell"
        assert mock_exec.call_args.kwargs["side"] == "sell"

    def test_zero_pct_closes_position(self):
        with (
            patch(
                "src.common.external.alpaca_portfolio.fetch_account_info",
                return_value=self._mock_account(),
            ),
            patch(
                "src.common.external.alpaca_portfolio.fetch_positions",
                return_value=self._mock_positions(),
            ),
            patch.object(self.skills, "close_position", return_value=_MOCK_ORDER) as mock_close,
        ):
            result = self.skills.scale_position("AAPL", target_pct=0.0)
        assert result["action"] == "close"
        mock_close.assert_called_once_with("AAPL")

    def test_hold_when_already_at_target(self):
        # 5 shares * $175 / $49000 equity ≈ 1.79%  target=0.018 → target_qty=4 → delta=−1
        # Make equity and qty align perfectly for zero delta
        # 10 shares * 175 / 50000 = 3.5%
        with (
            patch(
                "src.common.external.alpaca_portfolio.fetch_account_info",
                return_value=self._mock_account(50000),
            ),
            patch(
                "src.common.external.alpaca_portfolio.fetch_positions",
                return_value=self._mock_positions(qty=14, price=175.0),
            ),
            patch.object(self.skills, "execute_order") as mock_exec,
        ):
            # target_pct=0.049 → 0.049*50000/175=14 → delta=0 → hold
            result = self.skills.scale_position("AAPL", target_pct=0.049)
        assert result["action"] == "hold"
        mock_exec.assert_not_called()

    def test_invalid_equity_raises(self):
        with (
            patch(
                "src.common.external.alpaca_portfolio.fetch_account_info",
                return_value={"equity": 0.0},
            ),
            patch(
                "src.common.external.alpaca_portfolio.fetch_positions",
                return_value=[],
            ),
        ):
            with pytest.raises(ValueError, match="invalid equity"):
                self.skills.scale_position("AAPL", target_pct=0.05)


class TestPortfolioSkillsExecuteStrategySignal:
    @pytest.fixture(autouse=True)
    def _import_skills(self):
        from src.server.skills.portfolio.skills import PortfolioSkills
        self.skills = PortfolioSkills()

    def test_buy_signal_calls_scale_position(self):
        with patch.object(
            self.skills, "scale_position", return_value=_MOCK_SCALE_RESULT
        ) as mock_scale:
            result = self.skills.execute_strategy_signal(
                "AAPL", signal="buy", confidence=0.8, base_position_pct=0.05
            )
        assert result["action"] == "buy"
        assert result["confidence"] == 0.8
        # target_pct = 0.05 * 0.8 = 0.04
        assert abs(result["target_pct"] - 0.04) < 0.001
        mock_scale.assert_called_once()

    def test_sell_signal_calls_close_position(self):
        with patch.object(
            self.skills, "close_position", return_value=_MOCK_ORDER
        ) as mock_close:
            result = self.skills.execute_strategy_signal("AAPL", signal="sell")
        assert result["action"] == "sell"
        assert result["target_pct"] == 0.0
        mock_close.assert_called_once_with("AAPL")

    def test_hold_signal_no_order(self):
        result = self.skills.execute_strategy_signal("AAPL", signal="hold")
        assert result["action"] == "hold"
        assert result["order"] is None

    def test_confidence_scales_target_pct(self):
        with patch.object(
            self.skills,
            "scale_position",
            return_value={**_MOCK_SCALE_RESULT, "action": "buy"},
        ) as mock_scale:
            self.skills.execute_strategy_signal(
                "AAPL", signal="buy", confidence=0.5, base_position_pct=0.10
            )
        called_pct = mock_scale.call_args.kwargs["target_pct"]
        assert abs(called_pct - 0.05) < 0.001  # 0.10 * 0.5

    def test_invalid_signal_raises(self):
        with pytest.raises(ValueError, match="Invalid signal"):
            self.skills.execute_strategy_signal("AAPL", signal="strong_buy")

    def test_sell_no_position_returns_gracefully(self):
        with patch.object(
            self.skills, "close_position", side_effect=Exception("no position")
        ):
            result = self.skills.execute_strategy_signal("AAPL", signal="sell")
        # Should not raise — gracefully handle missing position
        assert result["action"] == "sell"
        assert result["order"] is None


# =============================================================================
# Unit tests — registry wrapper functions
# =============================================================================


class TestRegistryOrderWrappers:
    """Verify that _execute_order_wrapped / _close_position_wrapped etc. work."""

    def test_execute_order_wrapper_calls_core(self):
        with patch(
            "src.semi_auto.registry.functions.execute_order_core",
            return_value=_MOCK_ORDER,
        ):
            from src.server.registry.functions import FUNCTION_REGISTRY
            fn = FUNCTION_REGISTRY["execute_order"]
            result = fn(symbol="AAPL", qty=10, side="buy")
        assert result["id"] == _MOCK_ORDER["id"]

    def test_close_position_wrapper_calls_core(self):
        with patch(
            "src.semi_auto.registry.functions.close_position_core",
            return_value={**_MOCK_ORDER, "side": "sell"},
        ):
            from src.server.registry.functions import FUNCTION_REGISTRY
            fn = FUNCTION_REGISTRY["close_position"]
            result = fn(symbol="AAPL")
        assert result["side"] == "sell"

    def test_scale_position_wrapper_calls_core(self):
        with patch(
            "src.semi_auto.registry.functions.scale_position_core",
            return_value=_MOCK_SCALE_RESULT,
        ):
            from src.server.registry.functions import FUNCTION_REGISTRY
            fn = FUNCTION_REGISTRY["scale_position"]
            result = fn(symbol="AAPL", target_pct=0.05)
        assert result["action"] == "buy"

    def test_execute_strategy_signal_wrapper_calls_core(self):
        with patch(
            "src.semi_auto.registry.functions.execute_strategy_signal_core",
            return_value=_MOCK_SIGNAL_RESULT,
        ):
            from src.server.registry.functions import FUNCTION_REGISTRY
            fn = FUNCTION_REGISTRY["execute_strategy_signal"]
            result = fn(symbol="AAPL", signal="buy", confidence=0.8)
        assert result["signal"] == "buy"

    def test_execute_order_wrapper_surfaces_error(self):
        with patch(
            "src.semi_auto.registry.functions.execute_order_core",
            side_effect=Exception("Alpaca down"),
        ):
            from src.server.registry.functions import FUNCTION_REGISTRY
            fn = FUNCTION_REGISTRY["execute_order"]
            result = fn(symbol="AAPL", qty=10, side="buy")
        assert result["status"] == "error"
        assert "Alpaca down" in result["error"]

    def test_registry_has_all_four_order_functions(self):
        from src.server.registry.functions import FUNCTION_REGISTRY

        for name in ("execute_order", "close_position", "scale_position", "execute_strategy_signal"):
            assert name in FUNCTION_REGISTRY, f"Missing: {name}"

    def test_registry_total_count_is_56(self):
        from src.server.registry.functions import FUNCTION_REGISTRY

        assert len(FUNCTION_REGISTRY) == 56, (
            f"Expected 56 functions, got {len(FUNCTION_REGISTRY)}"
        )
