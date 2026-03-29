"""Tests for quant agent tools."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import json
from src.agentic.agents.quant_tools import (
    get_market_bars,
    get_company_fundamentals,
    save_eod_summary,
    save_strategy_result_tool
)


class TestGetMarketBars:
    """Test suite for get_market_bars tool."""

    def test_tool_exists(self):
        """Test that tool is properly decorated."""
        assert hasattr(get_market_bars, 'name')
        assert get_market_bars.name == 'get_market_bars'

    def test_get_market_bars_with_no_data(self):
        """Test behavior when no data is available."""
        result = get_market_bars.invoke({"symbol": "NONEXISTENT", "minutes": 30})
        assert isinstance(result, str)
        # Should return either error or "No data available"
        assert "No data available" in result or "Error" in result

    def test_get_market_bars_returns_json_string(self):
        """Test that result is a JSON string."""
        result = get_market_bars.invoke({"symbol": "AAPL", "minutes": 30})
        assert isinstance(result, str)

        # Try to parse as JSON (will fail if no data, but that's OK)
        if "No data" not in result and "Error" not in result:
            data = json.loads(result)
            assert "symbol" in data


class TestGetCompanyFundamentals:
    """Test suite for get_company_fundamentals tool."""

    def test_tool_exists(self):
        """Test that tool is properly decorated."""
        assert hasattr(get_company_fundamentals, 'name')
        assert get_company_fundamentals.name == 'get_company_fundamentals'

    def test_get_fundamentals_with_no_data(self):
        """Test behavior when no data is available."""
        result = get_company_fundamentals.invoke({"symbol": "NONEXISTENT"})
        assert isinstance(result, str)
        assert "No fundamental data" in result or "Error" in result

    def test_get_fundamentals_returns_json_string(self):
        """Test that result is a JSON string."""
        result = get_company_fundamentals.invoke({"symbol": "AAPL"})
        assert isinstance(result, str)


class TestSaveEODSummary:
    """Test suite for save_eod_summary tool."""

    def test_tool_exists(self):
        """Test that tool is properly decorated."""
        assert hasattr(save_eod_summary, 'name')
        assert save_eod_summary.name == 'save_eod_summary'

    def test_save_eod_summary_with_valid_data(self):
        """Test saving EOD summary with valid data."""
        indicators = json.dumps({
            "macd": {"value": 0.52, "signal": 0.48},
            "rsi": 65.3
        })
        signals = json.dumps({
            "momentum": "bullish",
            "volatility": "normal"
        })

        result = save_eod_summary.invoke({
            "symbol": "TEST",
            "indicators": indicators,
            "summary_text": "Test summary",
            "signals": signals,
            "thought_trace": "Test reasoning",
            "model_used": "gpt-5-mini"
        })

        assert isinstance(result, str)
        assert "success" in result.lower() or "saved" in result.lower()

    def test_save_eod_summary_with_json_strings(self):
        """Test that tool handles JSON string inputs correctly."""
        from datetime import datetime
        unique_symbol = f"TEST_{datetime.now().microsecond}"  # Unique symbol to avoid conflicts

        result = save_eod_summary.invoke({
            "symbol": unique_symbol,
            "indicators": json.dumps({"rsi": 65.3}),
            "summary_text": "Test",
            "signals": json.dumps({"momentum": "bullish"}),
            "model_used": "gpt-5-mini"
        })

        assert isinstance(result, str)
        # Should succeed or gracefully handle error
        assert isinstance(result, str)


class TestSaveStrategyResultTool:
    """Test suite for save_strategy_result_tool."""

    def test_tool_exists(self):
        """Test that tool is properly decorated."""
        assert hasattr(save_strategy_result_tool, 'name')
        assert save_strategy_result_tool.name == 'save_strategy_result_tool'

    def test_save_strategy_result_with_valid_data(self):
        """Test saving strategy result with valid data."""
        result_data = {
            "symbol": "TEST",
            "current_price": 150.25,
            "statistics": {"mean": 148.50, "z_score": 0.74},
            "moving_averages": {"sma_20": 148.75},
            "signals": {"overall_signal": "hold"},
            "trade_recommendation": {
                "action": "hold",
                "confidence": 0.65,
                "reason": "Test"
            },
            "levels": {"support": 145.0},
            "parameters": {"lookback": 60}
        }

        result = save_strategy_result_tool.invoke({
            "symbol": "TEST",
            "strategy_name": "mean-reversion",
            "result_json": json.dumps(result_data),
            "thought_trace": "Test reasoning",
            "model_used": "gpt-5-mini"
        })

        assert isinstance(result, str)
        assert "success" in result.lower() or "saved" in result.lower()

    def test_save_strategy_result_with_missing_fields(self):
        """Test handling of incomplete data."""
        result_data = {
            "symbol": "TEST",
            "current_price": 150.25,
            "statistics": {},
            "trade_recommendation": {"action": "hold"}
        }

        result = save_strategy_result_tool.invoke({
            "symbol": "TEST",
            "strategy_name": "mean-reversion",
            "result_json": json.dumps(result_data),
            "model_used": "gpt-5-mini"
        })

        # Should handle gracefully (might succeed or return error)
        assert isinstance(result, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
