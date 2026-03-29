"""Unit tests for the intent classifier node."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from src.langgraph.nodes.classifier import classify_intent, _extract_ticker, _classify_bt_workflow


class TestExtractTicker:
    """Tests for ticker extraction."""

    def test_extracts_standard_ticker(self):
        result = _extract_ticker("Analyze AAPL for buy signal")
        assert result == "AAPL"

    def test_extracts_multi_char_ticker(self):
        result = _extract_ticker("Backtest TSLA from 2026-01-01")
        assert result == "TSLA"

    def test_ignores_stop_words(self):
        result = _extract_ticker("What is my portfolio status?")
        # Should not return common words like "What", "my" — may be None or non-stop
        if result:
            assert result not in {"I", "A", "THE", "AND", "OR"}

    def test_returns_none_for_no_ticker(self):
        result = _extract_ticker("what is my portfolio status today")
        assert result is None


class TestClassifyBtWorkflow:
    """Tests for backtester sub-workflow classification."""

    def test_workflow_a_for_backtest(self):
        assert _classify_bt_workflow("backtest mean-reversion on aapl") == "A"

    def test_workflow_b_for_snapshot_worth(self):
        assert _classify_bt_workflow("what would my portfolio be worth today") == "B"

    def test_workflow_c_for_swap(self):
        assert _classify_bt_workflow("swap aapl for tsla") == "C"

    def test_workflow_c_priority_over_b(self):
        # C > B > A priority
        assert _classify_bt_workflow("swap aapl what would be worth") == "C"

    def test_default_is_a(self):
        assert _classify_bt_workflow("run some analysis") == "A"


class TestClassifyIntent:
    """Tests for the main classify_intent node function."""

    def test_portfolio_intent(self):
        result = classify_intent({"query": "What is my portfolio status?"})
        assert result["intent"] == "portfolio"

    def test_quant_intent(self):
        result = classify_intent({"query": "Analyze AAPL RSI and MACD signals"})
        assert result["intent"] == "quant"

    def test_backtest_intent(self):
        result = classify_intent({"query": "Backtest strategy on TSLA"})
        assert result["intent"] == "backtest"

    def test_full_analysis_explicit(self):
        result = classify_intent({"query": "Full analysis on MSFT"})
        assert result["intent"] == "full_analysis"

    def test_bt_workflow_set_for_backtest(self):
        result = classify_intent({"query": "Backtest AAPL from 2026-01-01"})
        assert result["intent"] == "backtest"
        assert result["bt_workflow"] in ("A", "B", "C")

    def test_symbol_extracted(self):
        result = classify_intent({"query": "Analyze NVDA for momentum signals"})
        assert result["symbol"] == "NVDA"

    def test_snapshot_worth_is_backtest_b(self):
        result = classify_intent({"query": "What would my Jan 15 portfolio be worth today?"})
        assert result["intent"] == "backtest"
        assert result["bt_workflow"] == "B"

    def test_swap_is_backtest_c(self):
        result = classify_intent({"query": "What if I swapped AAPL for TSLA?"})
        assert result["intent"] == "backtest"
        assert result["bt_workflow"] == "C"

    def test_returns_timestamp(self):
        result = classify_intent({"query": "portfolio status"})
        assert "timestamp" in result
        assert result["timestamp"]

    def test_empty_query_does_not_crash(self):
        result = classify_intent({"query": ""})
        assert "intent" in result
