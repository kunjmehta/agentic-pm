"""Tests for DAO read endpoints added in Phase 22.

Covers all five new DAO routers:
  - /v1/market/...        (AlpacaDAO)
  - /v1/fundamentals/...  (AlphaVantageDAO)
  - /v1/analyst/...       (AnalystDAO)
  - /v1/strategy/...      (StrategyDAO)
  - /v1/backtest/...      (BacktestDAO)

No real database, network, or LLM connections are required — every DAO is
mocked at the ``_dao()`` factory function inside each router module.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pandas as pd
import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


# ── Shared client fixture (same pattern as test_api.py) ──────────────────────


def _make_mock_graph(state_values=None, next_nodes=None):
    mock_graph = MagicMock()
    snap = MagicMock()
    snap.values = state_values or {}
    snap.next = list(next_nodes or [])
    mock_graph.get_state.return_value = snap
    mock_graph.invoke.return_value = snap.values
    mock_graph.update_state.return_value = None

    async def _astream_empty(*_a, **_kw):
        return
        yield  # noqa: unreachable — makes it an async generator

    mock_graph.astream_events = _astream_empty
    mock_graph.get_graph.return_value = MagicMock(nodes={})
    return mock_graph


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    mock_graph = _make_mock_graph(
        state_values={"query": "test", "intent": "portfolio"},
        next_nodes=[],
    )
    mock_coordinator = MagicMock()
    mock_coordinator.symbols = ["AAPL"]
    mock_coordinator.start_streaming = AsyncMock()
    mock_coordinator.run_streaming_loop = AsyncMock()
    mock_coordinator.stop_all_streaming = MagicMock()
    mock_coordinator.close = MagicMock()

    with (
        patch("src.semi_auto.lifespan.build_graph", return_value=mock_graph),
        patch("src.semi_auto.lifespan.DataCoordinator", return_value=mock_coordinator),
    ):
        from src.semi_auto.api import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ── Helpers ───────────────────────────────────────────────────────────────────


def _empty_df() -> pd.DataFrame:
    """Return an empty DataFrame (simulates no rows returned from DAO)."""
    return pd.DataFrame()


def _row_df(**kwargs) -> pd.DataFrame:
    """Return a single-row DataFrame from keyword column/value pairs."""
    return pd.DataFrame([kwargs])


# ══════════════════════════════════════════════════════════════════════════════
# Market data endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestMarketEndpoints:
    _PATCH = "src.semi_auto.routers.market._dao"

    def _mock_dao(self, **kwargs) -> MagicMock:
        dao = MagicMock()
        dao.close.return_value = None
        for k, v in kwargs.items():
            setattr(dao, k, MagicMock(return_value=v))
        return dao

    # ── watchlist ────────────────────────────────────────────────────────────

    def test_get_watchlist_returns_200(self, client):
        mock = self._mock_dao(get_watchlist=["AAPL", "MSFT"])
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/market/watchlist")
        assert r.status_code == 200

    def test_get_watchlist_returns_count(self, client):
        mock = self._mock_dao(get_watchlist=["AAPL", "MSFT"])
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/market/watchlist").json()
        assert data["count"] == 2
        assert "AAPL" in data["symbols"]

    def test_get_watchlist_500_on_error(self, client):
        dao = MagicMock()
        dao.get_watchlist.side_effect = RuntimeError("DB down")
        with patch(self._PATCH, return_value=dao):
            r = client.get("/v1/market/watchlist")
        assert r.status_code == 500

    def test_watchlist_symbol_check_true(self, client):
        mock = self._mock_dao(is_in_watchlist=True)
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/market/watchlist/aapl").json()
        assert data["in_watchlist"] is True
        assert data["symbol"] == "AAPL"

    def test_watchlist_symbol_check_false(self, client):
        mock = self._mock_dao(is_in_watchlist=False)
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/market/watchlist/UNKNOWN").json()
        assert data["in_watchlist"] is False

    # ── bars ─────────────────────────────────────────────────────────────────

    def test_get_bars_returns_200(self, client):
        df = _row_df(t="2024-01-02", o=100.0, c=101.0, v=1000)
        mock = self._mock_dao(get_bars=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/market/bars?symbol=AAPL&start=2024-01-01&end=2024-01-31")
        assert r.status_code == 200

    def test_get_bars_count(self, client):
        df = _row_df(t="2024-01-02", c=101.0)
        mock = self._mock_dao(get_bars=df)
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/market/bars?symbol=AAPL&start=2024-01-01&end=2024-01-31").json()
        assert data["count"] == 1

    def test_get_latest_bar_returns_200(self, client):
        mock = self._mock_dao(get_latest_bar={"c": 155.5, "t": "2024-01-31"})
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/market/bars/AAPL/latest")
        assert r.status_code == 200

    def test_get_latest_bar_null_when_no_data(self, client):
        mock = self._mock_dao(get_latest_bar=None)
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/market/bars/AAPL/latest").json()
        assert data["bar"] is None

    # ── trades ───────────────────────────────────────────────────────────────

    def test_get_trades_returns_200(self, client):
        df = _row_df(symbol="AAPL", price=155.0, size=100)
        mock = self._mock_dao(get_recent_trades=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/market/trades?symbol=AAPL&start=2024-01-01&end=2024-01-31")
        assert r.status_code == 200

    # ── indicators ───────────────────────────────────────────────────────────

    def test_get_indicators_returns_200(self, client):
        df = _row_df(symbol="AAPL", sma_20=155.0)
        mock = self._mock_dao(get_computed_indicators=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/market/indicators?symbol=AAPL&start=2024-01-01&end=2024-01-31")
        assert r.status_code == 200

    # ── intraday stats ────────────────────────────────────────────────────────

    def test_get_intraday_stats_returns_200(self, client):
        mock = self._mock_dao(calculate_intraday_stats={"high": 160.0, "low": 150.0})
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/market/stats/AAPL?date=2024-01-15")
        assert r.status_code == 200

    def test_get_intraday_stats_has_symbol(self, client):
        mock = self._mock_dao(calculate_intraday_stats={"high": 160.0})
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/market/stats/aapl?date=2024-01-15").json()
        assert data["symbol"] == "AAPL"
        assert data["stats"]["high"] == 160.0


# ══════════════════════════════════════════════════════════════════════════════
# Fundamentals endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestFundamentalsEndpoints:
    _PATCH = "src.semi_auto.routers.fundamentals._dao"

    def _mock_dao(self, **kwargs) -> MagicMock:
        dao = MagicMock()
        dao.close.return_value = None
        for k, v in kwargs.items():
            setattr(dao, k, MagicMock(return_value=v))
        return dao

    def test_get_all_returns_200(self, client):
        df = _row_df(symbol="AAPL", pe_ratio=28.5)
        mock = self._mock_dao(get_all_fundamentals=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/fundamentals")
        assert r.status_code == 200

    def test_get_company_overview_returns_200(self, client):
        mock = self._mock_dao(get_company_overview={"symbol": "AAPL", "sector": "Tech"})
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/fundamentals/AAPL")
        assert r.status_code == 200

    def test_get_company_overview_null_when_not_found(self, client):
        mock = self._mock_dao(get_company_overview=None)
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/fundamentals/ZZZZ").json()
        assert data["overview"] is None

    def test_get_dividends_returns_200(self, client):
        df = _row_df(symbol="AAPL", amount=0.24, ex_date="2024-02-09")
        mock = self._mock_dao(get_dividends=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/fundamentals/AAPL/dividends")
        assert r.status_code == 200

    def test_get_earnings_returns_200(self, client):
        df = _row_df(symbol="AAPL", reported_eps=2.18)
        mock = self._mock_dao(get_earnings=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/fundamentals/AAPL/earnings")
        assert r.status_code == 200

    def test_get_income_statement_returns_200(self, client):
        df = _row_df(symbol="AAPL", total_revenue=90000000000)
        mock = self._mock_dao(get_income_statement=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/fundamentals/AAPL/income")
        assert r.status_code == 200

    def test_get_balance_sheet_returns_200(self, client):
        df = _row_df(symbol="AAPL", total_assets=350000000000)
        mock = self._mock_dao(get_balance_sheet=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/fundamentals/AAPL/balance-sheet")
        assert r.status_code == 200

    def test_get_cash_flow_returns_200(self, client):
        df = _row_df(symbol="AAPL", operating_cashflow=90000000000)
        mock = self._mock_dao(get_cash_flow=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/fundamentals/AAPL/cash-flow")
        assert r.status_code == 200

    def test_returns_500_on_dao_error(self, client):
        dao = MagicMock()
        dao.get_company_overview.side_effect = RuntimeError("DB error")
        with patch(self._PATCH, return_value=dao):
            r = client.get("/v1/fundamentals/AAPL")
        assert r.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
# Analyst endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestAnalystEndpoints:
    _PATCH = "src.semi_auto.routers.analyst._dao"

    def _mock_dao(self, **kwargs) -> MagicMock:
        dao = MagicMock()
        dao.close.return_value = None
        for k, v in kwargs.items():
            setattr(dao, k, MagicMock(return_value=v))
        return dao

    def test_get_symbols_returns_200(self, client):
        mock = self._mock_dao(get_all_symbols=["AAPL", "MSFT"])
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/analyst/symbols")
        assert r.status_code == 200
        assert client.get("/v1/analyst/symbols").json()  # non-empty response

    def test_get_eod_summaries_returns_200(self, client):
        df = _row_df(symbol="AAPL", date="2024-01-15", sentiment="bullish")
        mock = self._mock_dao(get_eod_summaries=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/analyst/AAPL/eod?start=2024-01-01&end=2024-01-31")
        assert r.status_code == 200

    def test_get_latest_eod_returns_200(self, client):
        mock = self._mock_dao(get_latest_eod={"date": "2024-01-31", "sentiment": "bullish"})
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/analyst/AAPL/eod/latest")
        assert r.status_code == 200

    def test_get_latest_eod_null_when_missing(self, client):
        mock = self._mock_dao(get_latest_eod=None)
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/analyst/ZZZZ/eod/latest").json()
        assert data["summary"] is None

    def test_get_recent_eods_returns_200(self, client):
        mock = self._mock_dao(get_recent_eods=[{"date": "2024-01-31"}])
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/analyst/AAPL/eod/recent?count=3")
        assert r.status_code == 200

    def test_returns_500_on_dao_error(self, client):
        dao = MagicMock()
        dao.get_all_symbols.side_effect = RuntimeError("DB down")
        with patch(self._PATCH, return_value=dao):
            r = client.get("/v1/analyst/symbols")
        assert r.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
# Strategy endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestStrategyEndpoints:
    _PATCH = "src.semi_auto.routers.strategy._dao"

    def _mock_dao(self, **kwargs) -> MagicMock:
        dao = MagicMock()
        dao.close.return_value = None
        for k, v in kwargs.items():
            setattr(dao, k, MagicMock(return_value=v))
        return dao

    def test_get_actionable_signals_returns_200(self, client):
        df = _row_df(symbol="AAPL", action="buy", confidence=0.85)
        mock = self._mock_dao(get_actionable_signals=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/strategy/actionable")
        assert r.status_code == 200

    def test_get_actionable_signals_has_count(self, client):
        df = _row_df(symbol="AAPL", action="sell", confidence=0.9)
        mock = self._mock_dao(get_actionable_signals=df)
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/strategy/actionable?action=sell").json()
        assert data["count"] == 1

    def test_get_strategy_performance_returns_200(self, client):
        mock = self._mock_dao(get_strategy_performance={"total_return": 0.12, "sharpe": 1.4})
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/strategy/momentum_cross/performance")
        assert r.status_code == 200

    def test_get_latest_signal_returns_200(self, client):
        mock = self._mock_dao(get_latest_signal={"action": "buy", "confidence": 0.85})
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/strategy/AAPL/momentum_cross/latest")
        assert r.status_code == 200

    def test_get_recent_signals_returns_200(self, client):
        df = _row_df(symbol="AAPL", action="buy", confidence=0.85)
        mock = self._mock_dao(get_recent_signals=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/strategy/AAPL/momentum_cross/signals?limit=5")
        assert r.status_code == 200

    def test_returns_500_on_dao_error(self, client):
        dao = MagicMock()
        dao.get_actionable_signals.side_effect = RuntimeError("DB error")
        with patch(self._PATCH, return_value=dao):
            r = client.get("/v1/strategy/actionable")
        assert r.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
# Backtest endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestBacktestEndpoints:
    _PATCH = "src.semi_auto.routers.backtest._dao"

    def _mock_dao(self, **kwargs) -> MagicMock:
        dao = MagicMock()
        dao.close.return_value = None
        for k, v in kwargs.items():
            setattr(dao, k, MagicMock(return_value=v))
        return dao

    def test_get_recent_runs_returns_200(self, client):
        mock = self._mock_dao(get_recent_runs=[{"run_id": "abc123", "strategy": "momentum"}])
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/backtest/runs")
        assert r.status_code == 200

    def test_get_recent_runs_count(self, client):
        mock = self._mock_dao(get_recent_runs=[{"run_id": "abc"}, {"run_id": "xyz"}])
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/backtest/runs").json()
        assert data["count"] == 2

    def test_get_run_returns_200(self, client):
        mock = self._mock_dao(get_run={"run_id": "abc123", "total_return": 0.15})
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/backtest/runs/abc123")
        assert r.status_code == 200

    def test_get_run_null_when_not_found(self, client):
        mock = self._mock_dao(get_run=None)
        with patch(self._PATCH, return_value=mock):
            data = client.get("/v1/backtest/runs/unknown").json()
        assert data["run"] is None

    def test_get_trades_for_run_returns_200(self, client):
        df = _row_df(run_id="abc123", symbol="AAPL", pnl=200.0)
        mock = self._mock_dao(get_trades_for_run=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/backtest/runs/abc123/trades")
        assert r.status_code == 200

    def test_get_performance_history_returns_200(self, client):
        df = _row_df(run_id="abc123", date="2024-01-15", equity=105000.0)
        mock = self._mock_dao(get_performance_history=df)
        with patch(self._PATCH, return_value=mock):
            r = client.get("/v1/backtest/runs/abc123/performance")
        assert r.status_code == 200

    def test_returns_500_on_dao_error(self, client):
        dao = MagicMock()
        dao.get_recent_runs.side_effect = RuntimeError("DuckDB file locked")
        with patch(self._PATCH, return_value=dao):
            r = client.get("/v1/backtest/runs")
        assert r.status_code == 500
