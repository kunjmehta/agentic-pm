"""Tests for the semi-auto multi-agent graph.

Tests cover:
- Model instantiation (no DB or LLM calls)
- Graph topology (node/edge verification)
- Executor node with mock tasks
- State serialization (TypedDict and model_dump roundtrip)
- Classifier (keyword tier-1, no LLM)
- Registry (import checks)
"""

import sys
from pathlib import Path
from typing import Any, Dict

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest


# ── Model tests ───────────────────────────────────────────────────────────────


class TestTaskModels:
    """Pydantic model instantiation and serialization."""

    def test_task_item_defaults(self):
        from src.semi_auto.models.task import TaskItem
        item = TaskItem(
            task_id="pm_001",
            function_name="get_portfolio_status",
            description="Fetch status",
        )
        assert item.priority == 1
        assert item.depends_on == []
        assert item.retry_count == 0

    def test_task_item_with_deps(self):
        from src.semi_auto.models.task import TaskItem
        item = TaskItem(
            task_id="pm_003",
            function_name="check_portfolio_health",
            description="Health check",
            priority=2,
            depends_on=["pm_001", "pm_002"],
        )
        assert len(item.depends_on) == 2

    def test_task_list_serialization(self):
        from src.semi_auto.models.task import TaskItem, TaskList
        items = [
            TaskItem(task_id="pm_001", function_name="get_portfolio_status", description="status"),
            TaskItem(task_id="pm_002", function_name="get_positions_summary", description="positions"),
        ]
        tl = TaskList(tasks=items, reasoning_summary="Fetch portfolio overview.")
        data = tl.model_dump()
        assert len(data["tasks"]) == 2
        assert data["reasoning_summary"] == "Fetch portfolio overview."

    def test_agent_output_delegation_flags(self):
        from src.semi_auto.models.task import AgentOutput, TaskList
        ao = AgentOutput(
            task_list=TaskList(tasks=[], reasoning_summary="delegate only"),
            delegate_to_quant=True,
            quant_query="Analyze AAPL RSI",
        )
        assert ao.delegate_to_quant is True
        assert ao.delegate_to_backtester is False
        assert ao.quant_query == "Analyze AAPL RSI"

    def test_execution_result(self):
        from src.semi_auto.models.responses import ExecutionResult
        er = ExecutionResult(
            task_id="pm_001",
            function_name="get_portfolio_status",
            status="success",
            result={"equity": 100000.0},
            duration_ms=340,
        )
        assert er.status == "success"
        assert er.result["equity"] == 100000.0

    def test_semi_auto_response(self):
        from src.semi_auto.models.responses import SemiAutoResponse, ExecutionResult
        response = SemiAutoResponse(
            query="What is my portfolio?",
            thread_id="t1",
            conversation_id="c1",
            turn_number=1,
            final_response="Portfolio is healthy.",
            tasks_executed=2,
        )
        assert response.status == "success"
        assert response.tasks_executed == 2

    def test_task_preview_response(self):
        from src.semi_auto.models.responses import TaskPreviewResponse
        preview = TaskPreviewResponse(
            thread_id="t1",
            conversation_id="c1",
            portfolio_tasks=[{"task_id": "pm_001", "function_name": "get_portfolio_status"}],
        )
        assert preview.status == "pending_approval"
        assert len(preview.portfolio_tasks) == 1


# ── State tests ───────────────────────────────────────────────────────────────


class TestGraphState:
    """GraphState TypedDict and make_initial_state."""

    def test_make_initial_state_defaults(self):
        from src.semi_auto.state import make_initial_state
        state = make_initial_state("test query", "thread-001")
        assert state["query"] == "test query"
        assert state["thread_id"] == "thread-001"
        assert state["backtest_mode"] is False
        assert state["conversation_id"] is not None
        assert state["intent"] is None

    def test_make_initial_state_with_conversation_id(self):
        from src.semi_auto.state import make_initial_state
        state = make_initial_state("q", "t", conversation_id="existing-conv")
        assert state["conversation_id"] == "existing-conv"

    def test_make_initial_state_backtest_mode(self):
        from src.semi_auto.state import make_initial_state
        state = make_initial_state("q", "t", backtest_mode=True)
        assert state["backtest_mode"] is True

    def test_all_optional_fields_none(self):
        from src.semi_auto.state import make_initial_state
        state = make_initial_state("q", "t")
        optional_fields = [
            "intent", "symbol", "bt_workflow", "routing_error",
            "_delegate_quant", "_delegate_backtester",
            "portfolio_task_queue", "quant_task_queue", "backtester_task_queue",
            "portfolio_reasoning", "quant_reasoning", "backtester_reasoning",
            "pm_review_approved", "pm_review_notes",
            "execution_results", "final_response", "error",
        ]
        for field in optional_fields:
            assert state[field] is None, f"Expected {field} to be None, got {state[field]}"
        # review_iteration initializes to 0, not None
        assert state["review_iteration"] == 0, f"Expected review_iteration=0, got {state['review_iteration']}"


# ── Registry tests ─────────────────────────────────────────────────────────────


class TestRegistry:
    """Function registry import and structure."""

    def test_registry_has_42_functions(self):
        from src.semi_auto.registry.functions import FUNCTION_REGISTRY
        assert len(FUNCTION_REGISTRY) == 42

    def test_registry_schema_has_all_keys(self):
        from src.semi_auto.registry.functions import get_registry_schema, FUNCTION_REGISTRY
        schema = get_registry_schema()
        assert set(schema.keys()) == set(FUNCTION_REGISTRY.keys())

    def test_registry_dao_functions(self):
        from src.semi_auto.registry.functions import FUNCTION_REGISTRY
        dao_fns = [
            "get_market_bars", "get_latest_price", "get_precomputed_indicators",
            "get_tick_trades", "get_trade_count", "get_intraday_stats", "get_watchlist",
            "get_company_fundamentals", "get_dividends", "get_earnings_history",
            "get_income_statement", "get_balance_sheet", "get_cash_flow", "get_all_fundamentals",
            "get_eod_summaries",
            "get_recent_signals", "get_actionable_signals", "get_strategy_performance",
            "get_backtest_run", "get_recent_backtest_runs", "get_backtest_trades",
            "get_backtest_performance",
            "get_portfolio_snapshot_history", "get_risk_parameters",
        ]
        for fn_name in dao_fns:
            assert fn_name in FUNCTION_REGISTRY, f"Missing DAO function: {fn_name}"

    def test_portfolio_functions_importable(self):
        from src.semi_auto.registry.functions import FUNCTION_REGISTRY
        portfolio_fns = [
            "get_portfolio_status", "get_positions_summary",
            "check_portfolio_health",
            "check_data_availability",
        ]
        for fn_name in portfolio_fns:
            assert fn_name in FUNCTION_REGISTRY, f"Missing: {fn_name}"

    def test_quant_functions_registered(self):
        from src.semi_auto.registry.functions import FUNCTION_REGISTRY
        quant_fns = [
            "calc_momentum", "calc_volatility_bands", "calc_volume_flow",
            "analyze_candle_structure", "mean_reversion_analyze",
            "check_data_availability", "fetch_historical_data",
        ]
        for fn_name in quant_fns:
            assert fn_name in FUNCTION_REGISTRY, f"Missing: {fn_name}"

    def test_backtester_function_registered(self):
        from src.semi_auto.registry.functions import FUNCTION_REGISTRY
        assert "backtest_strategy" in FUNCTION_REGISTRY


# ── Executor tests ─────────────────────────────────────────────────────────────


class TestExecutorNode:
    """Executor node with mock tasks."""

    def test_empty_queues(self):
        from src.semi_auto.nodes.executor_node import executor_node
        result = executor_node({
            "portfolio_task_queue": None,
            "quant_task_queue": [],
            "backtester_task_queue": None,
        })
        assert result["execution_results"] == {}
        assert result["tool_timings"] == []

    def test_unknown_function_returns_error(self):
        from src.semi_auto.nodes.executor_node import executor_node
        state = {
            "portfolio_task_queue": [{
                "task_id": "pm_err",
                "function_name": "nonexistent_fn",
                "params": {},
                "priority": 1,
                "depends_on": [],
                "retry_count": 0,
                "description": "test",
            }],
            "quant_task_queue": None,
            "backtester_task_queue": None,
        }
        result = executor_node(state)
        assert result["execution_results"]["pm_err"]["status"] == "error"
        assert "not found in registry" in result["execution_results"]["pm_err"]["error"]

    def test_to_native_strips_numpy(self):
        from src.semi_auto.nodes.executor_node import _to_native
        try:
            import numpy as np
            data = {"value": np.float64(3.14), "count": np.int32(42), "flag": np.bool_(True)}
            native = _to_native(data)
            assert isinstance(native["value"], float)
            assert isinstance(native["count"], int)
            assert isinstance(native["flag"], bool)
        except ImportError:
            pytest.skip("numpy not available")


# ── Classifier tests ──────────────────────────────────────────────────────────


class TestClassifier:
    """Keyword tier-1 classification (no LLM calls)."""

    def test_portfolio_keyword(self):
        from src.semi_auto.nodes.classifier import classify_intent
        result = classify_intent({"query": "What is my portfolio status?"})
        assert result["intent"] == "portfolio"

    def test_quant_keyword(self):
        from src.semi_auto.nodes.classifier import classify_intent
        result = classify_intent({"query": "Analyze AAPL technical indicators"})
        assert result["intent"] == "quant"

    def test_backtest_keyword(self):
        from src.semi_auto.nodes.classifier import classify_intent
        result = classify_intent({"query": "Backtest mean-reversion on AAPL"})
        assert result["intent"] == "backtest"

    def test_full_analysis_keyword(self):
        from src.semi_auto.nodes.classifier import classify_intent
        result = classify_intent({"query": "Full analysis on MSFT"})
        assert result["intent"] == "full_analysis"

    def test_ticker_extraction(self):
        from src.semi_auto.nodes.classifier import classify_intent
        result = classify_intent({"query": "Analyze AAPL momentum"})
        assert result["symbol"] == "AAPL"

    def test_no_ticker(self):
        from src.semi_auto.nodes.classifier import classify_intent
        result = classify_intent({"query": "What is my portfolio status?"})
        assert result.get("symbol") is None

    def test_bt_workflow_a(self):
        from src.semi_auto.nodes.classifier import classify_intent
        result = classify_intent({"query": "Backtest strategy on AAPL from 2026-01-01"})
        assert result.get("bt_workflow") == "A"

    def test_bt_workflow_c(self):
        from src.semi_auto.nodes.classifier import classify_intent
        result = classify_intent({"query": "What if I swapped AAPL for NVDA?"})
        assert result.get("bt_workflow") == "C"


# ── Graph topology tests ──────────────────────────────────────────────────────


class TestGraphTopology:
    """Graph assembly and node verification (no LLM or DB calls)."""

    def test_graph_compiles(self):
        from src.semi_auto.graph import build_graph
        g = build_graph()
        assert g is not None

    def test_expected_nodes_present(self):
        from src.semi_auto.graph import build_graph
        g = build_graph()
        graph_repr = g.get_graph()
        node_names = [n.name for n in graph_repr.nodes.values()]
        expected = [
            "context_node", "classify_intent", "market_hours_guard",
            "portfolio_reasoning_node", "quant_reasoning_node",
            "backtester_reasoning_node", "pm_review_node",
            "executor_node", "synthesizer_node",
        ]
        for node in expected:
            assert node in node_names, f"Missing node: {node}"

    def test_make_initial_state(self):
        from src.semi_auto.state import make_initial_state
        state = make_initial_state("test query", "thread-001", backtest_mode=True)
        assert state["query"] == "test query"
        assert state["backtest_mode"] is True
        assert state["conversation_id"] is not None


if __name__ == "__main__":
    """Run tests directly."""
    import subprocess
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            str(Path(__file__)),
            "-v", "--tb=short",
        ],
        cwd=str(project_root),
    )
    sys.exit(result.returncode)
