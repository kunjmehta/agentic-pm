"""Tests for skills output models, the _out() helper, and thin registry wrappers.

Covers:
- All Pydantic output models in src.semi_auto.models.skills
- _out() validation helper (success, fallback, extra fields)
- Thin portfolio/backtester registry wrappers (mock-based)
"""

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest


# ── MACDOutput ─────────────────────────────────────────────────────────────────


class TestMACDOutput:
    def test_all_none_defaults(self):
        from src.semi_auto.models.skills import MACDOutput
        m = MACDOutput()
        assert m.value is None
        assert m.signal is None
        assert m.histogram is None

    def test_with_values(self):
        from src.semi_auto.models.skills import MACDOutput
        m = MACDOutput(value=0.5, signal=0.3, histogram=0.2)
        assert m.value == 0.5
        assert m.histogram == 0.2

    def test_extra_fields_allowed(self):
        from src.semi_auto.models.skills import MACDOutput
        m = MACDOutput.model_validate({"value": 1.0, "extra_key": "ignored_but_kept"})
        assert m.value == 1.0


# ── MomentumOutput ─────────────────────────────────────────────────────────────


class TestMomentumOutput:
    def test_defaults_from_empty_dict(self):
        from src.semi_auto.models.skills import MomentumOutput
        m = MomentumOutput.model_validate({})
        assert m.symbol == ""
        assert m.timeframe == "1Day"
        assert m.mode == "live"
        assert m.rsi is None
        assert m.error is None

    def test_error_dict_passes(self):
        """Error dicts (no symbol) must not raise ValidationError."""
        from src.semi_auto.models.skills import MomentumOutput
        m = MomentumOutput.model_validate({"error": "No data found"})
        assert m.error == "No data found"
        assert m.symbol == ""

    def test_full_round_trip(self):
        from src.semi_auto.models.skills import MomentumOutput, MACDOutput
        raw = {
            "symbol": "AAPL",
            "macd": {"value": 0.5, "signal": 0.3, "histogram": 0.2},
            "rsi": 65.4,
            "timeframe": "1Day",
            "timestamp": "2026-03-01T00:00:00",
            "mode": "live",
        }
        m = MomentumOutput.model_validate(raw)
        data = m.model_dump()
        assert data["symbol"] == "AAPL"
        assert data["rsi"] == 65.4
        assert data["macd"]["value"] == 0.5

    def test_extra_fields_pass_through(self):
        from src.semi_auto.models.skills import MomentumOutput
        m = MomentumOutput.model_validate({"symbol": "TSLA", "trend": "bullish"})
        data = m.model_dump()
        assert data.get("trend") == "bullish"


# ── VolatilityOutput ───────────────────────────────────────────────────────────


class TestVolatilityOutput:
    def test_defaults_from_empty_dict(self):
        from src.semi_auto.models.skills import VolatilityOutput
        v = VolatilityOutput.model_validate({})
        assert v.symbol == ""
        assert v.upper is None
        assert v.bandwidth is None

    def test_error_dict_passes(self):
        from src.semi_auto.models.skills import VolatilityOutput
        v = VolatilityOutput.model_validate({"error": "DB down"})
        assert v.error == "DB down"

    def test_full_values(self):
        from src.semi_auto.models.skills import VolatilityOutput
        v = VolatilityOutput(symbol="MSFT", upper=155.0, middle=150.0, lower=145.0, bandwidth=6.7)
        assert v.upper == 155.0
        assert v.bandwidth == 6.7


# ── VolumeOutput ───────────────────────────────────────────────────────────────


class TestVolumeOutput:
    def test_defaults_from_empty_dict(self):
        from src.semi_auto.models.skills import VolumeOutput
        v = VolumeOutput.model_validate({})
        assert v.symbol == ""
        assert v.obv is None
        assert v.volume_trend is None

    def test_error_dict_passes(self):
        from src.semi_auto.models.skills import VolumeOutput
        v = VolumeOutput.model_validate({"error": "No bars"})
        assert v.error == "No bars"

    def test_full_values(self):
        from src.semi_auto.models.skills import VolumeOutput
        v = VolumeOutput(
            symbol="NVDA",
            obv=1500000.0,
            volume_trend="increasing",
            avg_volume_10d=800000.0,
            current_vs_avg=1.87,
        )
        assert v.volume_trend == "increasing"
        assert v.current_vs_avg == pytest.approx(1.87)


# ── CandleOutput ──────────────────────────────────────────────────────────────


class TestCandleOutput:
    def test_defaults_from_empty_dict(self):
        from src.semi_auto.models.skills import CandleOutput
        c = CandleOutput.model_validate({})
        assert c.symbol == ""
        assert c.patterns == []
        assert c.pattern_count == 0

    def test_error_dict_passes(self):
        from src.semi_auto.models.skills import CandleOutput
        c = CandleOutput.model_validate({"error": "empty bars"})
        assert c.error == "empty bars"

    def test_with_patterns(self):
        from src.semi_auto.models.skills import CandleOutput
        c = CandleOutput(
            symbol="AAPL",
            patterns=["hammer", "doji"],
            last_candle_type="bullish",
            last_body_pct=65.2,
            pattern_count=2,
        )
        assert len(c.patterns) == 2
        assert c.last_candle_type == "bullish"


# ── BacktestMetrics ───────────────────────────────────────────────────────────


class TestBacktestMetrics:
    def test_all_fields_optional(self):
        from src.semi_auto.models.skills import BacktestMetrics
        m = BacktestMetrics()
        assert m.total_return_pct is None
        assert m.sharpe_ratio is None
        assert m.total_trades is None

    def test_partial_metrics(self):
        from src.semi_auto.models.skills import BacktestMetrics
        m = BacktestMetrics(total_return_pct=12.5, sharpe_ratio=1.3, win_rate=0.62)
        assert m.total_return_pct == 12.5
        assert m.win_rate == pytest.approx(0.62)

    def test_extra_fields_allowed(self):
        from src.semi_auto.models.skills import BacktestMetrics
        m = BacktestMetrics.model_validate({"total_return_pct": 5.0, "custom_metric": 99})
        assert m.total_return_pct == 5.0


# ── BacktestOutput ────────────────────────────────────────────────────────────


class TestBacktestOutput:
    def test_required_fields(self):
        from src.semi_auto.models.skills import BacktestOutput
        b = BacktestOutput(
            strategy="mean-reversion",
            ticker="AAPL",
            start_date="2025-01-01",
            end_date="2025-12-31",
        )
        assert b.status == "completed"
        assert b.error is None

    def test_missing_required_field_raises(self):
        from src.semi_auto.models.skills import BacktestOutput
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BacktestOutput(ticker="AAPL", start_date="2025-01-01", end_date="2025-12-31")

    def test_with_nested_metrics(self):
        from src.semi_auto.models.skills import BacktestOutput, BacktestMetrics
        b = BacktestOutput(
            strategy="momentum",
            ticker="TSLA",
            start_date="2025-01-01",
            end_date="2025-06-30",
            metrics=BacktestMetrics(total_return_pct=8.2, sharpe_ratio=0.9),
        )
        assert b.metrics.total_return_pct == 8.2

    def test_error_status(self):
        from src.semi_auto.models.skills import BacktestOutput
        b = BacktestOutput(
            status="error",
            strategy="buy-and-hold",
            ticker="MSFT",
            start_date="2025-01-01",
            end_date="2025-12-31",
            error="Insufficient data",
        )
        assert b.status == "error"
        assert "Insufficient" in b.error

    def test_round_trip_model_dump(self):
        from src.semi_auto.models.skills import BacktestOutput
        b = BacktestOutput(
            strategy="mean-reversion",
            ticker="SPY",
            start_date="2025-01-01",
            end_date="2025-12-31",
            run_id="run-abc-123",
            trades_count=42,
        )
        data = b.model_dump()
        assert data["run_id"] == "run-abc-123"
        assert data["trades_count"] == 42


# ── MeanReversion sub-models ──────────────────────────────────────────────────


class TestMeanReversionSubModels:
    def test_statistics_defaults(self):
        from src.semi_auto.models.skills import MeanReversionStatistics
        s = MeanReversionStatistics()
        assert s.mean is None
        assert s.z_score is None

    def test_moving_averages_defaults(self):
        from src.semi_auto.models.skills import MeanReversionMovingAverages
        ma = MeanReversionMovingAverages()
        assert ma.sma_20 is None
        assert ma.ema_20 is None

    def test_signals_defaults(self):
        from src.semi_auto.models.skills import MeanReversionSignals
        sig = MeanReversionSignals()
        assert sig.current_state == "unknown"
        assert sig.overall_signal == "hold"

    def test_levels_defaults(self):
        from src.semi_auto.models.skills import MeanReversionLevels
        lv = MeanReversionLevels()
        assert lv.resistance is None
        assert lv.support is None

    def test_recommendation_defaults(self):
        from src.semi_auto.models.skills import MeanReversionRecommendation
        r = MeanReversionRecommendation()
        assert r.action == "hold"
        assert r.confidence == 0.0
        assert r.reason == ""

    def test_recommendation_buy_signal(self):
        from src.semi_auto.models.skills import MeanReversionRecommendation
        r = MeanReversionRecommendation(
            action="buy", confidence=0.85, reason="Oversold below -2 z-score",
            entry_price=148.5, stop_loss=144.0, take_profit=158.0,
        )
        assert r.action == "buy"
        assert r.confidence == pytest.approx(0.85)
        assert r.stop_loss == 144.0


class TestMeanReversionOutput:
    def test_defaults_from_empty_dict(self):
        from src.semi_auto.models.skills import MeanReversionOutput
        m = MeanReversionOutput.model_validate({})
        assert m.symbol == ""
        assert m.current_price is None
        assert m.statistics is None

    def test_error_dict_passes(self):
        from src.semi_auto.models.skills import MeanReversionOutput
        m = MeanReversionOutput.model_validate({"error": "No price data"})
        assert m.error == "No price data"

    def test_full_nested_output(self):
        from src.semi_auto.models.skills import (
            MeanReversionOutput, MeanReversionStatistics,
            MeanReversionSignals, MeanReversionRecommendation,
        )
        raw = {
            "symbol": "AAPL",
            "current_price": 185.3,
            "statistics": {"mean": 180.0, "std_dev": 5.0, "z_score": 1.06},
            "signals": {"overall_signal": "sell", "current_state": "overbought"},
            "trade_recommendation": {"action": "sell", "confidence": 0.75, "reason": "Overbought"},
        }
        m = MeanReversionOutput.model_validate(raw)
        assert m.symbol == "AAPL"
        assert m.statistics.z_score == pytest.approx(1.06)
        assert m.signals.overall_signal == "sell"
        assert m.trade_recommendation.confidence == pytest.approx(0.75)

    def test_round_trip_model_dump(self):
        from src.semi_auto.models.skills import MeanReversionOutput
        m = MeanReversionOutput(symbol="NVDA", current_price=850.0, timeframe="1Hour")
        data = m.model_dump()
        assert data["symbol"] == "NVDA"
        assert data["current_price"] == 850.0


# ── PortfolioStatusOutput ─────────────────────────────────────────────────────


class TestPortfolioStatusOutput:
    def test_defaults_from_empty_dict(self):
        from src.semi_auto.models.skills import PortfolioStatusOutput
        p = PortfolioStatusOutput.model_validate({})
        assert p.equity == 0.0
        assert p.cash == 0.0
        assert p.long_positions == 0

    def test_error_dict_passes(self):
        from src.semi_auto.models.skills import PortfolioStatusOutput
        p = PortfolioStatusOutput.model_validate({"error": "Alpaca timeout"})
        assert p.error == "Alpaca timeout"
        assert p.equity == 0.0  # default

    def test_full_values(self):
        from src.semi_auto.models.skills import PortfolioStatusOutput
        p = PortfolioStatusOutput(
            equity=150000.0,
            cash=30000.0,
            buying_power=60000.0,
            long_positions=8,
            short_positions=0,
            portfolio_value=120000.0,
            last_equity=148000.0,
            timestamp="2026-03-01T16:00:00",
        )
        assert p.equity == 150000.0
        assert p.long_positions == 8

    def test_round_trip(self):
        from src.semi_auto.models.skills import PortfolioStatusOutput
        p = PortfolioStatusOutput(equity=100000.0, cash=25000.0)
        data = p.model_dump()
        assert data["equity"] == 100000.0
        assert data["cash"] == 25000.0


# ── PositionsSummaryOutput ────────────────────────────────────────────────────


class TestPositionsSummaryOutput:
    def test_defaults_from_empty_dict(self):
        from src.semi_auto.models.skills import PositionsSummaryOutput
        p = PositionsSummaryOutput.model_validate({})
        assert p.positions == []
        assert p.count == 0
        assert p.total_market_value == 0.0

    def test_error_dict_passes(self):
        from src.semi_auto.models.skills import PositionsSummaryOutput
        p = PositionsSummaryOutput.model_validate({"error": "No positions"})
        assert p.error == "No positions"

    def test_with_positions(self):
        from src.semi_auto.models.skills import PositionsSummaryOutput
        p = PositionsSummaryOutput(
            positions=[{"symbol": "AAPL", "qty": 10}, {"symbol": "MSFT", "qty": 5}],
            count=2,
            total_market_value=15000.0,
            total_unrealized_pl=500.0,
        )
        assert p.count == 2
        assert p.total_unrealized_pl == 500.0


# ── HealthViolation, HealthRiskParams, HealthCheckOutput ─────────────────────


class TestHealthModels:
    def test_health_violation_defaults(self):
        from src.semi_auto.models.skills import HealthViolation
        hv = HealthViolation()
        assert hv.rule == ""
        assert hv.symbol is None
        assert hv.message == ""

    def test_health_violation_populated(self):
        from src.semi_auto.models.skills import HealthViolation
        hv = HealthViolation(rule="max_position_size", symbol="AAPL", current=0.25, limit=0.20, message="Over limit")
        assert hv.current == pytest.approx(0.25)

    def test_health_risk_params_defaults(self):
        from src.semi_auto.models.skills import HealthRiskParams
        rp = HealthRiskParams()
        assert rp.position_limit_percent is None
        assert rp.daily_loss_limit is None

    def test_health_check_output_defaults_from_empty(self):
        from src.semi_auto.models.skills import HealthCheckOutput
        h = HealthCheckOutput.model_validate({})
        assert h.health_status == "healthy"
        assert h.violations == []
        assert h.warnings == []
        assert h.checks_performed == []

    def test_health_check_output_error_dict(self):
        from src.semi_auto.models.skills import HealthCheckOutput
        h = HealthCheckOutput.model_validate({"error": "DB error"})
        assert h.error == "DB error"
        assert h.health_status == "healthy"  # default preserved

    def test_health_check_output_with_violations(self):
        from src.semi_auto.models.skills import HealthCheckOutput, HealthViolation
        h = HealthCheckOutput(
            health_status="unhealthy",
            violations=[HealthViolation(rule="daily_loss", message="Exceeded daily loss limit")],
            warnings=[],
            checks_performed=["position_check", "daily_loss_check"],
        )
        assert h.health_status == "unhealthy"
        assert len(h.violations) == 1
        assert len(h.checks_performed) == 2

    def test_health_check_output_round_trip(self):
        from src.semi_auto.models.skills import HealthCheckOutput
        h = HealthCheckOutput(health_status="warning", checks_performed=["pos_check"])
        data = h.model_dump()
        assert data["health_status"] == "warning"
        assert data["violations"] == []


# ── FetchHistoricalDataOutput ─────────────────────────────────────────────────


class TestFetchHistoricalDataOutput:
    def test_defaults_from_empty_dict(self):
        from src.semi_auto.models.skills import FetchHistoricalDataOutput
        f = FetchHistoricalDataOutput.model_validate({})
        assert f.status == "success"
        assert f.bars_fetched is None
        assert f.data_source is None

    def test_error_dict_passes(self):
        from src.semi_auto.models.skills import FetchHistoricalDataOutput
        f = FetchHistoricalDataOutput.model_validate({"error": "API unavailable"})
        assert f.error == "API unavailable"
        assert f.status == "success"  # default preserved

    def test_full_values(self):
        from src.semi_auto.models.skills import FetchHistoricalDataOutput
        f = FetchHistoricalDataOutput(
            status="success",
            bars_fetched=250,
            symbol="AAPL",
            date_range="2025-01-01 to 2025-12-31",
            timeframe="1Day",
            data_source="alpaca_api",
        )
        assert f.bars_fetched == 250
        assert f.data_source == "alpaca_api"


# ── DataAvailabilityOutput ────────────────────────────────────────────────────


class TestDataAvailabilityOutput:
    def test_defaults_from_empty_dict(self):
        from src.semi_auto.models.skills import DataAvailabilityOutput
        d = DataAvailabilityOutput.model_validate({})
        assert d.available is False
        assert d.bar_count == 0
        assert d.coverage_pct is None

    def test_error_dict_passes(self):
        from src.semi_auto.models.skills import DataAvailabilityOutput
        d = DataAvailabilityOutput.model_validate({"error": "Query failed"})
        assert d.error == "Query failed"

    def test_partial_availability(self):
        from src.semi_auto.models.skills import DataAvailabilityOutput
        d = DataAvailabilityOutput(available="partial", bar_count=60, expected_bars=90, coverage_pct=66.7)
        assert d.available == "partial"
        assert d.coverage_pct == pytest.approx(66.7)

    def test_full_availability(self):
        from src.semi_auto.models.skills import DataAvailabilityOutput
        d = DataAvailabilityOutput(available=True, bar_count=365, expected_bars=365, coverage_pct=100.0)
        assert d.available is True


# ── SnapshotSaveOutput ────────────────────────────────────────────────────────


class TestSnapshotSaveOutput:
    def test_defaults_from_empty_dict(self):
        from src.semi_auto.models.skills import SnapshotSaveOutput
        s = SnapshotSaveOutput.model_validate({})
        assert s.status == "success"
        assert s.snapshot_id is None
        assert s.positions_count is None

    def test_error_dict_passes(self):
        from src.semi_auto.models.skills import SnapshotSaveOutput
        s = SnapshotSaveOutput.model_validate({"status": "error", "error": "DB write failed"})
        assert s.status == "error"
        assert s.error == "DB write failed"

    def test_full_success(self):
        from src.semi_auto.models.skills import SnapshotSaveOutput
        s = SnapshotSaveOutput(
            status="success",
            message="Snapshot saved",
            snapshot_id=42,
            date="2026-03-31",
            positions_count=8,
            long_positions=8,
            short_positions=0,
        )
        assert s.snapshot_id == 42
        assert s.long_positions == 8


# ── SimulationOutput, SnapshotWorthOutput, SwapPositionsOutput ───────────────


class TestSimulationOutputFamily:
    def test_simulation_output_defaults(self):
        from src.semi_auto.models.skills import SimulationOutput
        s = SimulationOutput.model_validate({})
        assert s.initial_worth is None
        assert s.return_pct is None

    def test_simulation_output_error_dict(self):
        from src.semi_auto.models.skills import SimulationOutput
        s = SimulationOutput.model_validate({"error": "No snapshot"})
        assert s.error == "No snapshot"

    def test_simulation_output_full_values(self):
        from src.semi_auto.models.skills import SimulationOutput
        s = SimulationOutput(
            snapshot_date="2026-01-01",
            end_date="2026-03-31",
            initial_worth=100000.0,
            final_worth=112000.0,
            return_pct=12.0,
            return_dollars=12000.0,
        )
        assert s.return_pct == pytest.approx(12.0)
        assert s.return_dollars == 12000.0

    def test_snapshot_worth_output_inherits_simulation(self):
        from src.semi_auto.models.skills import SnapshotWorthOutput
        s = SnapshotWorthOutput(
            snapshot_date="2026-01-01",
            end_date="2026-03-31",
            initial_worth=100000.0,
            final_worth=108000.0,
            return_pct=8.0,
        )
        assert s.return_pct == pytest.approx(8.0)
        # No extra fields
        data = s.model_dump()
        assert "initial_worth" in data

    def test_snapshot_worth_error_dict(self):
        from src.semi_auto.models.skills import SnapshotWorthOutput
        s = SnapshotWorthOutput.model_validate({"error": "Missing dates"})
        assert s.error == "Missing dates"

    def test_swap_positions_output_extra_fields(self):
        from src.semi_auto.models.skills import SwapPositionsOutput
        s = SwapPositionsOutput(
            snapshot_date="2026-01-01",
            end_date="2026-03-31",
            initial_worth=100000.0,
            final_worth=110000.0,
            return_pct=10.0,
            swaps_applied={"AAPL": "NVDA"},
            initial_worth_before_swap=99500.0,
        )
        assert s.swaps_applied["AAPL"] == "NVDA"
        assert s.initial_worth_before_swap == pytest.approx(99500.0)

    def test_swap_positions_error_dict(self):
        from src.semi_auto.models.skills import SwapPositionsOutput
        s = SwapPositionsOutput.model_validate({"error": "No tickers provided"})
        assert s.error == "No tickers provided"


# ── _out() helper ─────────────────────────────────────────────────────────────


class TestOutHelper:
    """Tests for the _out() registry helper function."""

    def test_valid_dict_returns_model_dump(self):
        from src.semi_auto.registry.functions import _out
        from src.semi_auto.models.skills import MomentumOutput
        raw = {"symbol": "AAPL", "rsi": 65.0, "timeframe": "1Day", "timestamp": "2026-01-01T00:00:00"}
        result = _out(MomentumOutput, raw)
        assert isinstance(result, dict)
        assert result["symbol"] == "AAPL"
        assert result["rsi"] == pytest.approx(65.0)

    def test_empty_dict_returns_defaults(self):
        from src.semi_auto.registry.functions import _out
        from src.semi_auto.models.skills import PortfolioStatusOutput
        result = _out(PortfolioStatusOutput, {})
        assert result["equity"] == 0.0
        assert result["long_positions"] == 0

    def test_error_dict_passes_without_raising(self):
        from src.semi_auto.registry.functions import _out
        from src.semi_auto.models.skills import MomentumOutput
        raw = {"error": "Connection failed"}
        result = _out(MomentumOutput, raw)
        # Either validated (defaults filled) or raw returned — both are dicts
        assert isinstance(result, dict)
        assert "error" in result

    def test_extra_fields_pass_through_with_allow(self):
        from src.semi_auto.registry.functions import _out
        from src.semi_auto.models.skills import PortfolioStatusOutput
        raw = {"equity": 100000.0, "extra_computed_field": 99}
        result = _out(PortfolioStatusOutput, raw)
        assert result["equity"] == 100000.0
        assert result.get("extra_computed_field") == 99

    def test_fallback_on_unrecoverable_failure(self):
        """If model_validate raises (e.g. required field missing) raw dict is returned."""
        from src.semi_auto.registry.functions import _out
        from src.semi_auto.models.skills import BacktestOutput
        # BacktestOutput requires strategy/ticker/start_date/end_date
        raw = {"error": "failed early"}
        result = _out(BacktestOutput, raw)
        # Falls back to raw dict
        assert isinstance(result, dict)
        assert result.get("error") == "failed early"

    def test_returns_dict_not_model_instance(self):
        """Output of _out() must always be a plain dict."""
        from src.semi_auto.registry.functions import _out
        from src.semi_auto.models.skills import HealthCheckOutput
        result = _out(HealthCheckOutput, {"health_status": "warning"})
        assert type(result) is dict

    def test_type_coercion(self):
        """Pydantic coerces string numbers to float/int."""
        from src.semi_auto.registry.functions import _out
        from src.semi_auto.models.skills import PortfolioStatusOutput
        raw = {"equity": "150000.0", "long_positions": "5"}
        result = _out(PortfolioStatusOutput, raw)
        assert isinstance(result["equity"], float)
        assert isinstance(result["long_positions"], int)


# ── Thin wrapper unit tests ───────────────────────────────────────────────────


class TestGetPortfolioStatusWrapper:
    """_get_portfolio_status_wrapped returns PortfolioStatusOutput-shaped dict."""

    _PATCH_BASE = "src.semi_auto.registry.functions"

    def test_calls_underlying_and_returns_validated_dict(self):
        from src.semi_auto.registry.functions import _get_portfolio_status_wrapped
        mock_result = {"equity": 120000.0, "cash": 30000.0, "long_positions": 5}
        with patch(f"{self._PATCH_BASE}.get_portfolio_status_core", return_value=mock_result):
            result = _get_portfolio_status_wrapped()
        assert result["equity"] == 120000.0
        assert result["long_positions"] == 5

    def test_error_from_underlying_returns_error_dict(self):
        from src.semi_auto.registry.functions import _get_portfolio_status_wrapped
        with patch(f"{self._PATCH_BASE}.get_portfolio_status_core", side_effect=RuntimeError("Alpaca down")):
            result = _get_portfolio_status_wrapped()
        assert "error" in result
        assert "Alpaca down" in result["error"]

    def test_result_has_model_defaults_filled(self):
        """Even a sparse result gets defaults filled by model validation."""
        from src.semi_auto.registry.functions import _get_portfolio_status_wrapped
        with patch(f"{self._PATCH_BASE}.get_portfolio_status_core", return_value={"equity": 50000.0}):
            result = _get_portfolio_status_wrapped()
        assert result["equity"] == 50000.0
        assert result["long_positions"] == 0  # default


class TestGetPositionsSummaryWrapper:
    _PATCH_BASE = "src.semi_auto.registry.functions"

    def test_calls_underlying_and_returns_validated_dict(self):
        from src.semi_auto.registry.functions import _get_positions_summary_wrapped
        mock_result = {"positions": [{"symbol": "AAPL"}], "count": 1, "total_market_value": 15000.0}
        with patch(f"{self._PATCH_BASE}.get_positions_summary_core", return_value=mock_result):
            result = _get_positions_summary_wrapped()
        assert result["count"] == 1

    def test_error_returns_error_dict(self):
        from src.semi_auto.registry.functions import _get_positions_summary_wrapped
        with patch(f"{self._PATCH_BASE}.get_positions_summary_core", side_effect=Exception("timeout")):
            result = _get_positions_summary_wrapped()
        assert "error" in result


class TestCheckPortfolioHealthWrapper:
    _PATCH_BASE = "src.semi_auto.registry.functions"

    def test_auto_fetches_when_not_provided(self):
        from src.semi_auto.registry.functions import _check_portfolio_health_wrapped
        mock_status = {"equity": 100000.0}
        mock_positions = {"positions": [], "count": 0}
        mock_health = {"health_status": "healthy", "violations": [], "warnings": []}
        with patch(f"{self._PATCH_BASE}.get_portfolio_status_core", return_value=mock_status), \
             patch(f"{self._PATCH_BASE}.get_positions_summary_core", return_value=mock_positions), \
             patch(f"{self._PATCH_BASE}.check_portfolio_health_core", return_value=mock_health):
            result = _check_portfolio_health_wrapped()
        assert result["health_status"] == "healthy"

    def test_uses_provided_args_without_fetching(self):
        from src.semi_auto.registry.functions import _check_portfolio_health_wrapped
        mock_health = {"health_status": "warning", "violations": [], "warnings": [{"rule": "x"}]}
        ps = {"equity": 80000.0}
        pd = {"positions": [], "count": 0}
        with patch(f"{self._PATCH_BASE}.get_portfolio_status_core") as mock_ps_fn, \
             patch(f"{self._PATCH_BASE}.get_positions_summary_core") as mock_pd_fn, \
             patch(f"{self._PATCH_BASE}.check_portfolio_health_core", return_value=mock_health):
            result = _check_portfolio_health_wrapped(portfolio_status=ps, positions_data=pd)
        # Core functions not called since values were provided
        mock_ps_fn.assert_not_called()
        mock_pd_fn.assert_not_called()
        assert result["health_status"] == "warning"

    def test_error_returns_error_dict(self):
        from src.semi_auto.registry.functions import _check_portfolio_health_wrapped
        with patch(f"{self._PATCH_BASE}.get_portfolio_status_core", side_effect=Exception("fail")):
            result = _check_portfolio_health_wrapped()
        assert "error" in result


class TestSnapshotWorthWrapper:
    _PATCH_BASE = "src.semi_auto.registry.functions"

    def test_missing_snapshot_date_returns_error(self):
        from src.semi_auto.registry.functions import _snapshot_worth_wrapped
        result = _snapshot_worth_wrapped(end_date="2026-03-31")
        assert "error" in result
        assert "snapshot_date" in result["error"]

    def test_missing_end_date_returns_error(self):
        from src.semi_auto.registry.functions import _snapshot_worth_wrapped
        result = _snapshot_worth_wrapped(snapshot_date="2026-01-01")
        assert "error" in result

    def test_calls_raw_and_returns_validated(self):
        from src.semi_auto.registry.functions import _snapshot_worth_wrapped
        mock_result = {"initial_worth": 100000.0, "final_worth": 108000.0, "return_pct": 8.0}
        with patch(f"{self._PATCH_BASE}._snapshot_worth_raw", return_value=mock_result):
            result = _snapshot_worth_wrapped(snapshot_date="2026-01-01", end_date="2026-03-31")
        assert result["return_pct"] == pytest.approx(8.0)

    def test_exception_returns_error_dict(self):
        from src.semi_auto.registry.functions import _snapshot_worth_wrapped
        with patch(f"{self._PATCH_BASE}._snapshot_worth_raw", side_effect=Exception("DB error")):
            result = _snapshot_worth_wrapped(snapshot_date="2026-01-01", end_date="2026-03-31")
        assert "error" in result


class TestSwapPositionsWrapper:
    _PATCH_BASE = "src.semi_auto.registry.functions"

    def test_missing_dates_returns_error(self):
        from src.semi_auto.registry.functions import _swap_positions_wrapped
        result = _swap_positions_wrapped(tickers={"AAPL": "NVDA"})
        assert "error" in result

    def test_missing_tickers_returns_error(self):
        from src.semi_auto.registry.functions import _swap_positions_wrapped
        result = _swap_positions_wrapped(snapshot_date="2026-01-01", end_date="2026-03-31")
        assert "error" in result
        assert "tickers" in result["error"]

    def test_calls_raw_and_returns_validated(self):
        from src.semi_auto.registry.functions import _swap_positions_wrapped
        mock_result = {
            "initial_worth": 100000.0, "final_worth": 115000.0, "return_pct": 15.0,
            "swaps_applied": {"AAPL": "NVDA"},
        }
        with patch(f"{self._PATCH_BASE}._swap_positions_raw", return_value=mock_result):
            result = _swap_positions_wrapped(
                snapshot_date="2026-01-01",
                end_date="2026-03-31",
                tickers={"AAPL": "NVDA"},
            )
        assert result["return_pct"] == pytest.approx(15.0)
        assert result["swaps_applied"]["AAPL"] == "NVDA"

    def test_exception_returns_error_dict(self):
        from src.semi_auto.registry.functions import _swap_positions_wrapped
        with patch(f"{self._PATCH_BASE}._swap_positions_raw", side_effect=ValueError("bad tickers")):
            result = _swap_positions_wrapped(
                snapshot_date="2026-01-01", end_date="2026-03-31", tickers={"AAPL": "NVDA"},
            )
        assert "error" in result


class TestSaveEODSnapshotWrapper:
    _PATCH_BASE = "src.semi_auto.registry.functions"

    def test_calls_raw_with_filled_defaults(self):
        from src.semi_auto.registry.functions import _save_eod_snapshot_wrapped
        mock_result = {"status": "success", "snapshot_id": 7, "positions_count": 5}
        with patch(f"{self._PATCH_BASE}._save_eod_snapshot_raw", return_value=mock_result) as mock_raw:
            result = _save_eod_snapshot_wrapped(equity=100000.0, cash=25000.0)
        mock_raw.assert_called_once()
        call_kwargs = mock_raw.call_args[1]
        assert call_kwargs["equity"] == 100000.0
        assert call_kwargs["positions"] == []

    def test_result_validated_through_snapshot_save_output(self):
        from src.semi_auto.registry.functions import _save_eod_snapshot_wrapped
        mock_result = {"status": "success", "snapshot_id": 10}
        with patch(f"{self._PATCH_BASE}._save_eod_snapshot_raw", return_value=mock_result):
            result = _save_eod_snapshot_wrapped()
        assert result["status"] == "success"
        assert result["snapshot_id"] == 10

    def test_exception_returns_error_status_dict(self):
        from src.semi_auto.registry.functions import _save_eod_snapshot_wrapped
        with patch(f"{self._PATCH_BASE}._save_eod_snapshot_raw", side_effect=Exception("DAO error")):
            result = _save_eod_snapshot_wrapped()
        assert result["status"] == "error"
        assert "error" in result


if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__)), "-v", "--tb=short"],
        cwd=str(project_root),
    )
    sys.exit(result.returncode)
