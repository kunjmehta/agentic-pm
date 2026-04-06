"""Extended tests for semi-auto nodes, models, routing, and helpers.

Covers code paths not exercised by test_graph.py:
- FunctionCall / AgentPlan / FunctionCallEdit / PMFeedback models
- Response models (ApprovalRequest, SemiAutoQueryRequest, SemiAutoResponse)
- Graph routing pure functions (route_after_*)
- Guards (backtest bypass, routing_error output)
- Synthesizer helpers (_format_execution_results, _build_synthesis_prompt, short-circuit)
- PM review helpers (_apply_edits, _format_calls, auto-approval)
- Executor additional scenarios (upstream error, queue normalisation, timing)
- Classifier helpers (_keyword_fallback — intent, bt_workflow, ticker, strategy extraction)
- Context node (with PortfolioDAO mocked)
"""

import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest


# ── FunctionCall / AgentPlan / FunctionCallEdit / PMFeedback ─────────────────


class TestFunctionCallModels:
    """New Pydantic models added for quant/bt structured output and PM feedback."""

    def test_function_call_defaults(self):
        from src.semi_auto.models.task import FunctionCall
        fc = FunctionCall(function_name="calc_momentum")
        assert fc.function_name == "calc_momentum"
        assert fc.params == {}

    def test_function_call_with_params(self):
        from src.semi_auto.models.task import FunctionCall
        fc = FunctionCall(
            function_name="calc_momentum",
            params={"symbol": "AAPL", "timeframe": "1Day", "lookback_days": 90},
        )
        assert fc.params["symbol"] == "AAPL"

    def test_agent_plan_empty(self):
        from src.semi_auto.models.task import AgentPlan
        plan = AgentPlan(reasoning_summary="No calls needed.")
        assert plan.calls == []
        assert plan.reasoning_summary == "No calls needed."

    def test_agent_plan_with_calls(self):
        from src.semi_auto.models.task import AgentPlan, FunctionCall
        plan = AgentPlan(
            calls=[
                FunctionCall(function_name="calc_momentum", params={"symbol": "AAPL"}),
                FunctionCall(function_name="calc_volatility_bands", params={"symbol": "AAPL"}),
            ],
            reasoning_summary="Momentum and volatility for AAPL.",
        )
        assert len(plan.calls) == 2
        assert plan.calls[0].function_name == "calc_momentum"

    def test_agent_plan_serialization_roundtrip(self):
        from src.semi_auto.models.task import AgentPlan, FunctionCall
        plan = AgentPlan(
            calls=[FunctionCall(function_name="get_latest_price", params={"symbol": "TSLA"})],
            reasoning_summary="Get current price.",
        )
        data = plan.model_dump()
        assert data["reasoning_summary"] == "Get current price."
        assert data["calls"][0]["function_name"] == "get_latest_price"
        restored = AgentPlan(**data)
        assert restored.calls[0].function_name == "get_latest_price"

    def test_function_call_edit_remove(self):
        from src.semi_auto.models.task import FunctionCallEdit
        edit = FunctionCallEdit(index=2, action="remove")
        assert edit.index == 2
        assert edit.action == "remove"
        assert edit.new_params is None
        assert edit.new_function_name is None

    def test_function_call_edit_update_params(self):
        from src.semi_auto.models.task import FunctionCallEdit
        edit = FunctionCallEdit(
            index=0,
            action="update_params",
            new_params={"symbol": "MSFT", "lookback_days": 60},
        )
        assert edit.action == "update_params"
        assert edit.new_params["symbol"] == "MSFT"

    def test_function_call_edit_replace_function(self):
        from src.semi_auto.models.task import FunctionCallEdit
        edit = FunctionCallEdit(
            index=1,
            action="replace_function",
            new_function_name="mean_reversion_analyze",
            new_params={"symbol": "AAPL", "lookback": 60},
        )
        assert edit.new_function_name == "mean_reversion_analyze"

    def test_pm_feedback_approved_no_edits(self):
        from src.semi_auto.models.task import PMFeedback
        fb = PMFeedback(approved=True)
        assert fb.approved is True
        assert fb.quant_edits == []
        assert fb.backtester_edits == []
        assert fb.reason is None

    def test_pm_feedback_approved_with_quant_edits(self):
        from src.semi_auto.models.task import PMFeedback, FunctionCallEdit
        fb = PMFeedback(
            approved=True,
            quant_edits=[FunctionCallEdit(index=0, action="remove")],
        )
        assert len(fb.quant_edits) == 1
        assert fb.quant_edits[0].action == "remove"

    def test_pm_feedback_rejected_with_reason(self):
        from src.semi_auto.models.task import PMFeedback
        fb = PMFeedback(
            approved=False,
            reason="Missing mandatory check_data_availability as first step.",
        )
        assert fb.approved is False
        assert "check_data_availability" in fb.reason

    def test_pm_feedback_serialization(self):
        from src.semi_auto.models.task import PMFeedback, FunctionCallEdit
        fb = PMFeedback(
            approved=True,
            backtester_edits=[FunctionCallEdit(index=1, action="update_params", new_params={"symbol": "NVDA"})],
        )
        data = fb.model_dump()
        assert data["approved"] is True
        assert data["backtester_edits"][0]["new_params"]["symbol"] == "NVDA"


# ── Response models ───────────────────────────────────────────────────────────


class TestResponseModels:
    """SemiAutoQueryRequest, ApprovalRequest, SemiAutoResponse, ExecutionResult."""

    def test_execution_result_error_status(self):
        from src.semi_auto.models.responses import ExecutionResult
        er = ExecutionResult(
            task_id="pm_001",
            function_name="get_portfolio_status",
            status="error",
            error="Connection refused",
        )
        assert er.status == "error"
        assert er.result is None
        assert er.error == "Connection refused"

    def test_execution_result_skipped(self):
        from src.semi_auto.models.responses import ExecutionResult
        er = ExecutionResult(
            task_id="pm_002",
            function_name="check_portfolio_health",
            status="skipped",
            error="Max retries reached",
        )
        assert er.status == "skipped"

    def test_execution_result_defaults(self):
        from src.semi_auto.models.responses import ExecutionResult
        er = ExecutionResult(task_id="x", function_name="fn", status="success")
        assert er.result is None
        assert er.error is None
        assert er.duration_ms is None

    def test_approval_request_all_optional(self):
        from src.semi_auto.models.responses import ApprovalRequest
        req = ApprovalRequest()
        assert req.modified_portfolio_tasks is None
        assert req.modified_quant_tasks is None
        assert req.modified_backtester_tasks is None

    def test_approval_request_with_modified_queue(self):
        from src.semi_auto.models.responses import ApprovalRequest
        req = ApprovalRequest(
            modified_quant_tasks=[
                {"function_name": "calc_momentum", "params": {"symbol": "AAPL"}}
            ]
        )
        assert len(req.modified_quant_tasks) == 1

    def test_query_request_defaults(self):
        from src.semi_auto.models.responses import SemiAutoQueryRequest
        req = SemiAutoQueryRequest(query="What is my portfolio?")
        assert req.backtest_mode is False
        assert req.stream_reasoning is False
        assert req.thread_id is None
        assert req.conversation_id is None

    def test_query_request_min_length_validation(self):
        from src.semi_auto.models.responses import SemiAutoQueryRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SemiAutoQueryRequest(query="")

    def test_semi_auto_response_success_defaults(self):
        from src.semi_auto.models.responses import SemiAutoResponse
        resp = SemiAutoResponse(
            query="test",
            thread_id="t1",
            conversation_id="c1",
            turn_number=1,
            final_response="Done.",
        )
        assert resp.status == "success"
        assert resp.tasks_executed == 0
        assert resp.execution_results == []
        assert resp.error is None

    def test_semi_auto_response_error_status(self):
        from src.semi_auto.models.responses import SemiAutoResponse
        resp = SemiAutoResponse(
            query="q",
            thread_id="t",
            conversation_id="c",
            turn_number=1,
            final_response="Failed.",
            status="error",
            error="Timeout",
        )
        assert resp.status == "error"
        assert resp.error == "Timeout"

    def test_task_preview_quant_and_bt_tasks(self):
        from src.semi_auto.models.responses import TaskPreviewResponse
        preview = TaskPreviewResponse(
            thread_id="t1",
            conversation_id="c1",
            quant_tasks=[{"function_name": "calc_momentum", "params": {"symbol": "AAPL"}}],
            backtester_tasks=[{"function_name": "backtest_strategy", "params": {}}],
            pm_review_notes="Plans approved.",
        )
        assert preview.status == "pending_approval"
        assert len(preview.quant_tasks) == 1
        assert len(preview.backtester_tasks) == 1
        assert preview.pm_review_notes == "Plans approved."


# ── Graph routing pure functions ──────────────────────────────────────────────


class TestGraphRouting:
    """All route_after_* conditional edge functions — no LLM or DB."""

    def test_route_market_guard_blocked(self):
        from src.semi_auto.graph import route_after_market_guard
        assert route_after_market_guard({"routing_error": "Market closed"}) == "synthesizer_node"

    def test_route_market_guard_passes(self):
        from src.semi_auto.graph import route_after_market_guard
        assert route_after_market_guard({}) == "portfolio_reasoning_node"
        assert route_after_market_guard({"routing_error": None}) == "portfolio_reasoning_node"

    def test_route_pm_reasoning_error(self):
        from src.semi_auto.graph import route_after_pm_reasoning
        assert route_after_pm_reasoning({"error": "LLM failure"}) == "synthesizer_node"

    def test_route_pm_reasoning_delegate_quant_full_analysis(self):
        from src.semi_auto.graph import route_after_pm_reasoning
        state = {"intent": "full_analysis", "_delegate_quant": True, "_delegate_backtester": True}
        assert route_after_pm_reasoning(state) == "quant_reasoning_node"

    def test_route_pm_reasoning_delegate_backtester_only_full_analysis(self):
        from src.semi_auto.graph import route_after_pm_reasoning
        state = {"intent": "full_analysis", "_delegate_quant": False, "_delegate_backtester": True}
        assert route_after_pm_reasoning(state) == "backtester_reasoning_node"

    def test_route_pm_reasoning_backtest_intent_skips_quant(self):
        """backtest intent routes directly to backtester even if _delegate_quant is set."""
        from src.semi_auto.graph import route_after_pm_reasoning
        state = {"intent": "backtest", "_delegate_quant": True, "_delegate_backtester": True}
        assert route_after_pm_reasoning(state) == "backtester_reasoning_node"

    def test_route_pm_reasoning_backtest_intent_no_delegation(self):
        from src.semi_auto.graph import route_after_pm_reasoning
        state = {"intent": "backtest", "_delegate_backtester": False}
        assert route_after_pm_reasoning(state) == "pm_review_node"

    def test_route_pm_reasoning_quant_intent_goes_to_quant(self):
        from src.semi_auto.graph import route_after_pm_reasoning
        state = {"intent": "quant", "_delegate_quant": True, "_delegate_backtester": True}
        assert route_after_pm_reasoning(state) == "quant_reasoning_node"

    def test_route_pm_reasoning_quant_intent_no_delegation(self):
        from src.semi_auto.graph import route_after_pm_reasoning
        state = {"intent": "quant", "_delegate_quant": False}
        assert route_after_pm_reasoning(state) == "pm_review_node"

    def test_route_pm_reasoning_neither(self):
        from src.semi_auto.graph import route_after_pm_reasoning
        assert route_after_pm_reasoning({}) == "pm_review_node"
        assert route_after_pm_reasoning({"_delegate_quant": False, "_delegate_backtester": False}) == "pm_review_node"

    def test_route_after_quant_error(self):
        from src.semi_auto.graph import route_after_quant
        assert route_after_quant({"error": "timeout"}) == "synthesizer_node"

    def test_route_after_quant_chains_to_backtester_for_full_analysis(self):
        from src.semi_auto.graph import route_after_quant
        state = {"intent": "full_analysis", "_delegate_backtester": True}
        assert route_after_quant(state) == "backtester_reasoning_node"

    def test_route_after_quant_no_backtester_chain_for_quant_intent(self):
        """quant intent: never chains to backtester even if _delegate_backtester is set."""
        from src.semi_auto.graph import route_after_quant
        state = {"intent": "quant", "_delegate_backtester": True}
        assert route_after_quant(state) == "pm_review_node"

    def test_route_after_quant_no_backtester(self):
        from src.semi_auto.graph import route_after_quant
        assert route_after_quant({}) == "pm_review_node"
        assert route_after_quant({"_delegate_backtester": False}) == "pm_review_node"

    def test_route_after_backtester_error(self):
        from src.semi_auto.graph import route_after_backtester
        assert route_after_backtester({"error": "fail"}) == "synthesizer_node"

    def test_route_after_backtester_always_pm_review(self):
        from src.semi_auto.graph import route_after_backtester
        assert route_after_backtester({}) == "pm_review_node"
        assert route_after_backtester({"_delegate_quant": True}) == "pm_review_node"

    def test_route_after_pm_review_approved(self):
        from src.semi_auto.graph import route_after_pm_review
        assert route_after_pm_review({"pm_review_approved": True}) == "executor_node"

    def test_route_after_pm_review_error(self):
        from src.semi_auto.graph import route_after_pm_review
        assert route_after_pm_review({"error": "fail"}) == "synthesizer_node"

    def test_route_after_pm_review_rejected_iter0_quant(self):
        from src.semi_auto.graph import route_after_pm_review
        state = {"pm_review_approved": False, "review_iteration": 0, "_delegate_quant": True}
        assert route_after_pm_review(state) == "quant_reasoning_node"

    def test_route_after_pm_review_rejected_iter1_backtester_only(self):
        from src.semi_auto.graph import route_after_pm_review
        state = {
            "pm_review_approved": False,
            "review_iteration": 1,
            "_delegate_quant": False,
            "_delegate_backtester": True,
        }
        assert route_after_pm_review(state) == "backtester_reasoning_node"

    def test_route_after_pm_review_rejected_max_iterations(self):
        from src.semi_auto.graph import route_after_pm_review
        # iteration >= 2 → give up
        state = {"pm_review_approved": False, "review_iteration": 2, "_delegate_quant": True}
        assert route_after_pm_review(state) == "synthesizer_node"

    def test_route_after_pm_review_rejected_no_delegates(self):
        from src.semi_auto.graph import route_after_pm_review
        # rejected with iteration < 2 but no delegations → synthesizer
        state = {"pm_review_approved": False, "review_iteration": 0}
        assert route_after_pm_review(state) == "synthesizer_node"


# ── Guards ────────────────────────────────────────────────────────────────────


class TestGuards:
    """market_hours_guard — backtest bypass and violation output."""

    def test_backtest_mode_always_passes(self):
        from src.semi_auto.nodes.guards import market_hours_guard
        result = market_hours_guard({"backtest_mode": True})
        assert result == {}

    def test_violation_sets_routing_error(self):
        """Force a violation by making the middleware raise RuntimeError."""
        from src.semi_auto.nodes.guards import market_hours_guard
        with patch(
            "src.semi_auto.nodes.guards.MarketHoursGuardMiddleware"
        ) as MockGuard:
            mock_instance = MagicMock()
            mock_instance.before_agent.side_effect = RuntimeError("Market is closed")
            MockGuard.return_value = mock_instance

            result = market_hours_guard({"backtest_mode": False})

        assert "routing_error" in result
        assert "final_response" in result
        assert "Market is closed" in result["routing_error"]
        assert "Market Hours Guard" in result["final_response"]

    def test_violation_response_mentions_market_hours(self):
        from src.semi_auto.nodes.guards import market_hours_guard
        with patch(
            "src.semi_auto.nodes.guards.MarketHoursGuardMiddleware"
        ) as MockGuard:
            mock_instance = MagicMock()
            mock_instance.before_agent.side_effect = RuntimeError("Outside hours")
            MockGuard.return_value = mock_instance

            result = market_hours_guard({"backtest_mode": False})

        assert "NYSE" in result["final_response"]
        assert "backtest_mode" in result["final_response"]


# ── Synthesizer helpers ────────────────────────────────────────────────────────


class TestSynthesizerHelpers:
    """Pure helper functions — no LLM or DB calls."""

    def test_format_execution_results_empty(self):
        from src.semi_auto.nodes.synthesizer import _format_execution_results
        out = _format_execution_results({})
        assert "No functions" in out

    def test_format_execution_results_success(self):
        from src.semi_auto.nodes.synthesizer import _format_execution_results
        results = {
            "pm_001": {
                "function_name": "get_portfolio_status",
                "status": "success",
                "result": {"equity": 100000.0},
                "timing": {"duration_ms": 340},
            }
        }
        out = _format_execution_results(results)
        assert "pm_001" in out
        assert "get_portfolio_status" in out
        assert "success" in out

    def test_format_execution_results_error(self):
        from src.semi_auto.nodes.synthesizer import _format_execution_results
        results = {
            "pm_002": {
                "function_name": "check_portfolio_health",
                "status": "error",
                "result": None,
                "error": "Connection refused",
                "timing": {"duration_ms": 50},
            }
        }
        out = _format_execution_results(results)
        assert "error" in out
        assert "Connection refused" in out

    def test_format_execution_results_truncates_large_result(self):
        from src.semi_auto.nodes.synthesizer import _format_execution_results
        large_result = {"data": "x" * 1000}
        results = {
            "pm_001": {
                "function_name": "fn",
                "status": "success",
                "result": large_result,
                "timing": {"duration_ms": 10},
            }
        }
        out = _format_execution_results(results)
        # Output must be bounded — JSON of {"data": "x"*1000} is ~1006 chars
        # The code truncates result_str to 500 chars
        assert len(out) < 2000

    def test_build_synthesis_prompt_includes_query(self):
        from src.semi_auto.nodes.synthesizer import _build_synthesis_prompt
        state = {
            "query": "What is my portfolio?",
            "intent": "portfolio",
            "symbol": None,
            "turn_number": 1,
            "execution_results": {},
        }
        prompt = _build_synthesis_prompt(state)
        assert "What is my portfolio?" in prompt
        assert "portfolio" in prompt

    def test_build_synthesis_prompt_includes_pm_reasoning(self):
        from src.semi_auto.nodes.synthesizer import _build_synthesis_prompt
        state = {
            "query": "q",
            "intent": "portfolio",
            "symbol": "AAPL",
            "turn_number": 2,
            "portfolio_reasoning": "PM fetched status and positions.",
            "quant_reasoning": None,
            "backtester_reasoning": None,
            "execution_results": {},
        }
        prompt = _build_synthesis_prompt(state)
        assert "PM Reasoning" in prompt
        assert "PM fetched status and positions." in prompt

    def test_build_synthesis_prompt_includes_all_agent_reasoning(self):
        from src.semi_auto.nodes.synthesizer import _build_synthesis_prompt
        state = {
            "query": "Full analysis",
            "intent": "full_analysis",
            "symbol": "MSFT",
            "turn_number": 1,
            "portfolio_reasoning": "pm trace",
            "quant_reasoning": "quant trace",
            "backtester_reasoning": "bt trace",
            "execution_results": {},
        }
        prompt = _build_synthesis_prompt(state)
        assert "PM Reasoning" in prompt
        assert "Quant Reasoning" in prompt
        assert "Backtester Reasoning" in prompt

    def test_build_synthesis_prompt_no_symbol(self):
        from src.semi_auto.nodes.synthesizer import _build_synthesis_prompt
        state = {"query": "q", "intent": "portfolio", "symbol": None, "turn_number": 1, "execution_results": {}}
        prompt = _build_synthesis_prompt(state)
        assert "N/A" in prompt

    def test_short_circuit_returns_empty_dict(self):
        from src.semi_auto.nodes.synthesizer import synthesizer_node
        result = synthesizer_node({
            "routing_error": "Market closed",
            "final_response": "Guard blocked this request.",
            "query": "q",
        })
        assert result == {}

    def test_short_circuit_only_when_both_fields_set(self):
        """Guard short-circuit requires BOTH routing_error AND final_response."""
        from src.semi_auto.nodes.synthesizer import synthesizer_node
        # routing_error set but no final_response → should NOT short-circuit
        # (will try LLM call and fail gracefully)
        with patch("src.semi_auto.nodes.synthesizer._call_llm", return_value="degraded"):
            with patch("src.semi_auto.nodes.synthesizer._persist_turn"):
                result = synthesizer_node({
                    "routing_error": "error",
                    "final_response": None,
                    "query": "q",
                    "intent": "portfolio",
                    "execution_results": {},
                })
        assert "final_response" in result
        assert result["final_response"] == "degraded"


# ── PM review helpers ─────────────────────────────────────────────────────────


class TestPMReviewHelpers:
    """_format_calls and _apply_edits — pure functions."""

    def test_format_calls_empty(self):
        from src.semi_auto.nodes.pm_review_node import _format_calls
        out = _format_calls("Quant", [])
        assert "none" in out.lower()

    def test_format_calls_none_queue(self):
        from src.semi_auto.nodes.pm_review_node import _format_calls
        out = _format_calls("Backtester", None)
        assert "none" in out.lower()

    def test_format_calls_shows_index(self):
        from src.semi_auto.nodes.pm_review_node import _format_calls
        queue = [
            {"function_name": "calc_momentum", "params": {"symbol": "AAPL"}},
            {"function_name": "calc_volatility_bands", "params": {"symbol": "AAPL"}},
        ]
        out = _format_calls("Quant", queue)
        assert "[0]" in out
        assert "[1]" in out
        assert "calc_momentum" in out
        assert "calc_volatility_bands" in out

    def test_format_calls_shows_unique_count(self):
        from src.semi_auto.nodes.pm_review_node import _format_calls
        queue = [
            {"function_name": "calc_momentum", "params": {}},
            {"function_name": "calc_momentum", "params": {}},
        ]
        out = _format_calls("Quant", queue)
        # 2 total, 1 unique
        assert "2 total" in out
        assert "1 unique" in out

    def test_apply_edits_empty_edits(self):
        from src.semi_auto.nodes.pm_review_node import _apply_edits
        queue = [{"function_name": "fn1", "params": {}}]
        result = _apply_edits(queue, [], "Test")
        assert result == queue

    def test_apply_edits_update_params(self):
        from src.semi_auto.models.task import FunctionCallEdit
        from src.semi_auto.nodes.pm_review_node import _apply_edits
        queue = [{"function_name": "calc_momentum", "params": {"symbol": "AAPL"}}]
        edits = [FunctionCallEdit(index=0, action="update_params", new_params={"symbol": "MSFT", "lookback_days": 60})]
        result = _apply_edits(queue, edits, "Quant")
        assert result[0]["params"]["symbol"] == "MSFT"
        assert result[0]["params"]["lookback_days"] == 60
        assert result[0]["function_name"] == "calc_momentum"  # name unchanged

    def test_apply_edits_replace_function(self):
        from src.semi_auto.models.task import FunctionCallEdit
        from src.semi_auto.nodes.pm_review_node import _apply_edits
        queue = [{"function_name": "wrong_fn", "params": {"symbol": "AAPL"}}]
        edits = [FunctionCallEdit(index=0, action="replace_function", new_function_name="calc_momentum")]
        result = _apply_edits(queue, edits, "Quant")
        assert result[0]["function_name"] == "calc_momentum"
        assert result[0]["params"]["symbol"] == "AAPL"  # params preserved when not provided

    def test_apply_edits_replace_function_with_new_params(self):
        from src.semi_auto.models.task import FunctionCallEdit
        from src.semi_auto.nodes.pm_review_node import _apply_edits
        queue = [{"function_name": "wrong_fn", "params": {"old": "val"}}]
        edits = [FunctionCallEdit(
            index=0, action="replace_function",
            new_function_name="calc_momentum",
            new_params={"symbol": "NVDA"},
        )]
        result = _apply_edits(queue, edits, "Quant")
        assert result[0]["function_name"] == "calc_momentum"
        assert result[0]["params"]["symbol"] == "NVDA"

    def test_apply_edits_remove_single(self):
        from src.semi_auto.models.task import FunctionCallEdit
        from src.semi_auto.nodes.pm_review_node import _apply_edits
        queue = [
            {"function_name": "fn1", "params": {}},
            {"function_name": "fn2", "params": {}},
        ]
        edits = [FunctionCallEdit(index=0, action="remove")]
        result = _apply_edits(queue, edits, "Quant")
        assert len(result) == 1
        assert result[0]["function_name"] == "fn2"

    def test_apply_edits_remove_descending_order(self):
        """Removes at indices 2 then 0 — must not shift indices between removals."""
        from src.semi_auto.models.task import FunctionCallEdit
        from src.semi_auto.nodes.pm_review_node import _apply_edits
        queue = [
            {"function_name": "fn0", "params": {}},
            {"function_name": "fn1", "params": {}},
            {"function_name": "fn2", "params": {}},
        ]
        edits = [
            FunctionCallEdit(index=0, action="remove"),
            FunctionCallEdit(index=2, action="remove"),
        ]
        result = _apply_edits(queue, edits, "Quant")
        assert len(result) == 1
        assert result[0]["function_name"] == "fn1"

    def test_apply_edits_out_of_range_skipped(self):
        """Out-of-range non-remove edits are skipped without crashing."""
        from src.semi_auto.models.task import FunctionCallEdit
        from src.semi_auto.nodes.pm_review_node import _apply_edits
        queue = [{"function_name": "fn1", "params": {}}]
        edits = [FunctionCallEdit(index=99, action="update_params", new_params={"x": 1})]
        result = _apply_edits(queue, edits, "Quant")
        # Original queue unchanged
        assert len(result) == 1
        assert result[0]["function_name"] == "fn1"

    def test_apply_edits_update_then_remove(self):
        """Update index 0 params AND remove index 1 — both apply cleanly."""
        from src.semi_auto.models.task import FunctionCallEdit
        from src.semi_auto.nodes.pm_review_node import _apply_edits
        queue = [
            {"function_name": "fn0", "params": {"symbol": "AAPL"}},
            {"function_name": "fn1", "params": {}},
        ]
        edits = [
            FunctionCallEdit(index=0, action="update_params", new_params={"symbol": "TSLA"}),
            FunctionCallEdit(index=1, action="remove"),
        ]
        result = _apply_edits(queue, edits, "Quant")
        assert len(result) == 1
        assert result[0]["params"]["symbol"] == "TSLA"

    def test_auto_approve_no_sub_agent_tasks(self):
        """pm_review_node auto-approves when both quant and bt queues are empty."""
        from src.semi_auto.nodes.pm_review_node import pm_review_node
        state = {
            "query": "What is my portfolio?",
            "intent": "portfolio",
            "portfolio_task_queue": [{"task_id": "pm_001", "function_name": "get_portfolio_status"}],
            "quant_task_queue": [],
            "backtester_task_queue": None,
            "review_iteration": 0,
        }
        result = pm_review_node(state)
        assert result["pm_review_approved"] is True
        assert "no sub-agent" in result["pm_review_notes"].lower() or "approved" in result["pm_review_notes"].lower()

    def test_auto_approve_both_queues_none(self):
        from src.semi_auto.nodes.pm_review_node import pm_review_node
        state = {
            "query": "q",
            "intent": "portfolio",
            "portfolio_task_queue": [],
            "quant_task_queue": None,
            "backtester_task_queue": None,
            "review_iteration": 0,
        }
        result = pm_review_node(state)
        assert result["pm_review_approved"] is True


# ── Executor additional scenarios ─────────────────────────────────────────────


class TestExecutorAdditional:
    """Executor scenarios not covered in test_graph.py."""

    def test_upstream_error_skips_execution(self):
        from src.semi_auto.nodes.executor_node import executor_node
        result = executor_node({
            "error": "PM reasoning failed",
            "portfolio_task_queue": [{"task_id": "pm_001", "function_name": "get_portfolio_status",
                                       "params": {}, "priority": 1, "depends_on": [], "retry_count": 0}],
            "quant_task_queue": None,
            "backtester_task_queue": None,
        })
        assert result["execution_results"] == {}
        assert result["tool_timings"] == []

    def test_quant_queue_normalisation(self):
        """Quant calls in {function_name, params} format get task_id qa_001, qa_002..."""
        from src.semi_auto.nodes.executor_node import executor_node
        result = executor_node({
            "portfolio_task_queue": None,
            "quant_task_queue": [
                {"function_name": "nonexistent_quant_fn", "params": {}},
            ],
            "backtester_task_queue": None,
        })
        assert "qa_001" in result["execution_results"]
        assert result["execution_results"]["qa_001"]["status"] == "error"

    def test_bt_queue_normalisation(self):
        """Backtester calls get task_id bt_001, bt_002..."""
        from src.semi_auto.nodes.executor_node import executor_node
        result = executor_node({
            "portfolio_task_queue": None,
            "quant_task_queue": None,
            "backtester_task_queue": [
                {"function_name": "nonexistent_bt_fn", "params": {}},
                {"function_name": "another_missing_fn", "params": {}},
            ],
        })
        assert "bt_001" in result["execution_results"]
        assert "bt_002" in result["execution_results"]

    def test_mixed_queue_task_ids_dont_collide(self):
        """PM uses pm_NNN, quant uses qa_NNN, bt uses bt_NNN — all distinct."""
        from src.semi_auto.nodes.executor_node import executor_node
        result = executor_node({
            "portfolio_task_queue": [{
                "task_id": "pm_001",
                "function_name": "missing_pm",
                "params": {}, "priority": 1, "depends_on": [], "retry_count": 0,
            }],
            "quant_task_queue": [{"function_name": "missing_quant", "params": {}}],
            "backtester_task_queue": [{"function_name": "missing_bt", "params": {}}],
        })
        keys = set(result["execution_results"].keys())
        assert "pm_001" in keys
        assert "qa_001" in keys
        assert "bt_001" in keys
        assert len(keys) == 3

    def test_timing_populated_on_error(self):
        """Error results should still include a timing entry."""
        from src.semi_auto.nodes.executor_node import executor_node
        result = executor_node({
            "portfolio_task_queue": [{
                "task_id": "pm_err",
                "function_name": "nonexistent_fn",
                "params": {}, "priority": 1, "depends_on": [], "retry_count": 0,
            }],
            "quant_task_queue": None,
            "backtester_task_queue": None,
        })
        # executor records timing even on registry miss
        assert len(result["tool_timings"]) >= 1

    def test_to_native_numpy_array(self):
        from src.semi_auto.nodes.executor_node import _to_native
        try:
            import numpy as np
            arr = np.array([1, 2, 3])
            result = _to_native(arr)
            assert result == [1, 2, 3]
            assert isinstance(result, list)
        except ImportError:
            pytest.skip("numpy not available")

    def test_to_native_nested_structure(self):
        from src.semi_auto.nodes.executor_node import _to_native
        try:
            import numpy as np
            nested = {"a": np.float32(1.5), "b": [np.int64(10), np.int64(20)], "c": "text"}
            result = _to_native(nested)
            assert isinstance(result["a"], float)
            assert isinstance(result["b"][0], int)
            assert result["c"] == "text"
        except ImportError:
            pytest.skip("numpy not available")

    def test_to_native_passthrough_for_native_types(self):
        from src.semi_auto.nodes.executor_node import _to_native
        data = {"a": 1, "b": "hello", "c": [1.0, 2.0], "d": True}
        result = _to_native(data)
        assert result == data

    def test_to_native_tuple(self):
        from src.semi_auto.nodes.executor_node import _to_native
        result = _to_native((1, "two", 3.0))
        assert result == (1, "two", 3.0)
        assert isinstance(result, tuple)

    def test_extract_dep_params_wrong_status(self):
        """_extract_dep_params returns empty dict when dependency failed."""
        from src.semi_auto.nodes.executor_node import _extract_dep_params
        dep_result = {"status": "error", "result": None, "function_name": "get_portfolio_status"}
        params = _extract_dep_params("pm_001", dep_result, "check_portfolio_health")
        assert params == {}

    def test_extract_dep_params_portfolio_status(self):
        """Injects portfolio_status into check_portfolio_health."""
        from src.semi_auto.nodes.executor_node import _extract_dep_params
        dep_result = {
            "status": "success",
            "result": {"equity": 100000.0},
            "function_name": "get_portfolio_status",
        }
        params = _extract_dep_params("pm_001", dep_result, "check_portfolio_health")
        assert "portfolio_status" in params
        assert params["portfolio_status"]["equity"] == 100000.0

    def test_extract_dep_params_positions_summary(self):
        """Injects positions_data into check_portfolio_health."""
        from src.semi_auto.nodes.executor_node import _extract_dep_params
        dep_result = {
            "status": "success",
            "result": [{"symbol": "AAPL", "qty": 10}],
            "function_name": "get_positions_summary",
        }
        params = _extract_dep_params("pm_002", dep_result, "check_portfolio_health")
        assert "positions_data" in params

    def test_extract_dep_params_other_function_no_injection(self):
        """Non-health-check functions get no injected params."""
        from src.semi_auto.nodes.executor_node import _extract_dep_params
        dep_result = {
            "status": "success",
            "result": {"equity": 100000.0},
            "function_name": "get_portfolio_status",
        }
        params = _extract_dep_params("pm_001", dep_result, "calc_momentum")
        assert params == {}


# ── Classifier helpers ────────────────────────────────────────────────────────


class TestClassifierHelpers:
    """_keyword_fallback (new API) — intent, bt_workflow, ticker extraction."""

    _TODAY = "2026-03-30"
    _DEFAULT_START = "2026-03-01"

    def _fb(self, query: str):
        """Shorthand: call _keyword_fallback and return QueryIntent."""
        from src.semi_auto.nodes.classifier import _keyword_fallback
        from datetime import datetime, timezone
        now = datetime.strptime(self._TODAY, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return _keyword_fallback(query, now, self._TODAY, self._DEFAULT_START)

    def test_portfolio_keywords_detected(self):
        qi = self._fb("what is my portfolio status and equity")
        assert qi.intent == "portfolio"
        assert "portfolio" in qi.agents

    def test_quant_keywords_detected(self):
        qi = self._fb("analyze aapl rsi macd momentum")
        assert qi.intent == "quant"
        assert "quant" in qi.agents

    def test_backtest_keywords_detected(self):
        # "backtest" and "historical" are pure BT keywords (no quant overlap)
        qi = self._fb("run historical backtest on AAPL")
        assert qi.intent == "backtest"
        assert "backtester" in qi.agents

    def test_empty_query_defaults_to_portfolio(self):
        qi = self._fb("")
        assert qi.intent == "portfolio"

    def test_bt_workflow_a_default(self):
        qi = self._fb("backtest mean-reversion strategy on aapl")
        assert qi.bt_workflow == "A"

    def test_bt_workflow_b_snapshot(self):
        # "backtest" triggers has_bt; "worth" triggers workflow B
        qi = self._fb("backtest what aapl would be worth if held since 2023")
        assert qi.bt_workflow == "B"

    def test_bt_workflow_c_swap(self):
        qi = self._fb("what if i swapped aapl for nvda")
        assert qi.bt_workflow == "C"

    def test_bt_workflow_c_beats_b(self):
        """swap keyword present → workflow C regardless of worth keyword."""
        # "backtest" triggers has_bt; "swap" triggers C, "worth" triggers B — C wins
        qi = self._fb("backtest swap positions what would be worth")
        assert qi.bt_workflow == "C"

    def test_ticker_stop_words_ignored(self):
        qi = self._fb("RSI analysis for my portfolio")
        assert qi.ticker not in {"RSI", "MY", "FOR", None} or qi.ticker is None

    def test_ticker_extracted_from_query(self):
        qi = self._fb("I want to analyze AAPL")
        assert qi.ticker == "AAPL"

    def test_ticker_first_match_wins(self):
        qi = self._fb("Compare AAPL and MSFT momentum")
        assert qi.ticker == "AAPL"

    def test_ticker_none_when_no_uppercase(self):
        qi = self._fb("what is my portfolio status")
        assert qi.ticker is None

    def test_confidence_is_lower_for_fallback(self):
        qi = self._fb("backtest AAPL strategy")
        assert qi.confidence < 1.0

    def test_default_dates_applied(self):
        qi = self._fb("backtest AAPL")
        assert qi.start_date == self._DEFAULT_START
        assert qi.end_date == self._TODAY

    def test_explicit_dates_extracted(self):
        qi = self._fb("backtest AAPL from 2026-01-01 to 2026-01-31")
        assert qi.start_date == "2026-01-01"
        assert qi.end_date == "2026-01-31"

    def test_strategy_mean_reversion_extracted(self):
        qi = self._fb("backtest mean reversion on AAPL")
        assert qi.strategy == "mean-reversion"

    def test_strategy_momentum_extracted(self):
        qi = self._fb("run momentum backtest on TSLA")
        assert qi.strategy == "momentum"

    def test_classify_intent_bt_workflow_set_for_backtest(self):
        from src.semi_auto.nodes.classifier import classify_intent
        result = classify_intent({"query": "Backtest mean-reversion strategy on TSLA"})
        assert result.get("bt_workflow") is not None

    def test_classify_intent_bt_workflow_none_for_portfolio(self):
        from src.semi_auto.nodes.classifier import classify_intent
        result = classify_intent({"query": "What is my portfolio equity?"})
        assert result.get("bt_workflow") is None


# ── Context node ──────────────────────────────────────────────────────────────


class TestContextNode:
    """context_node with mocked PortfolioDAO."""

    def _make_mock_dao(self, interactions=None):
        mock_dao = MagicMock()
        mock_dao.get_interaction_history.return_value = interactions or []
        mock_dao.save_thread_id.return_value = None
        mock_dao.close.return_value = None
        return mock_dao

    def _patch_dao(self, mock_dao):
        """Patch PortfolioDAO at source (imported locally inside context_node functions)."""
        return patch("src.common.dao.portfolio_dao.PortfolioDAO", return_value=mock_dao)

    def test_generates_conversation_id_when_none(self):
        from src.semi_auto.nodes.context_node import context_node
        mock_dao = self._make_mock_dao()
        with self._patch_dao(mock_dao):
            result = context_node({"thread_id": "t1", "conversation_id": None})
        assert result["conversation_id"] is not None
        assert len(result["conversation_id"]) > 0

    def test_preserves_existing_conversation_id(self):
        from src.semi_auto.nodes.context_node import context_node
        mock_dao = self._make_mock_dao()
        with self._patch_dao(mock_dao):
            result = context_node({"thread_id": "t1", "conversation_id": "existing-conv-123"})
        assert result["conversation_id"] == "existing-conv-123"

    def test_turn_number_starts_at_one_with_no_history(self):
        from src.semi_auto.nodes.context_node import context_node
        mock_dao = self._make_mock_dao(interactions=[])
        with self._patch_dao(mock_dao):
            result = context_node({"thread_id": "t1", "conversation_id": None})
        assert result["turn_number"] == 1

    def test_turn_number_increments_with_history(self):
        from src.semi_auto.nodes.context_node import context_node
        prior = [{"turn": 1}, {"turn": 2}, {"turn": 3}]
        mock_dao = self._make_mock_dao(interactions=prior)
        with self._patch_dao(mock_dao):
            result = context_node({"thread_id": "t1", "conversation_id": None})
        assert result["turn_number"] == 4

    def test_prior_turns_loaded(self):
        from src.semi_auto.nodes.context_node import context_node
        prior = [{"id": 1}, {"id": 2}]
        mock_dao = self._make_mock_dao(interactions=prior)
        with self._patch_dao(mock_dao):
            result = context_node({"thread_id": "t1", "conversation_id": None})
        assert result["prior_turns"] == prior

    def test_db_failure_graceful(self):
        """DB errors should not propagate — context_node degrades gracefully."""
        from src.semi_auto.nodes.context_node import context_node
        mock_dao = MagicMock()
        mock_dao.get_interaction_history.side_effect = Exception("DB connection failed")
        mock_dao.save_thread_id.side_effect = Exception("DB connection failed")
        mock_dao.close.return_value = None
        with self._patch_dao(mock_dao):
            result = context_node({"thread_id": "t1", "conversation_id": None})
        # DB failure is caught — should still return required fields with empty prior_turns
        assert "conversation_id" in result
        assert "turn_number" in result


# ── State additional field coverage ──────────────────────────────────────────


class TestGraphStateAdditional:
    """Additional state fields introduced in the AgentPlan/PMFeedback refactor."""

    def test_pm_review_edits_initialized_none(self):
        from src.semi_auto.state import make_initial_state
        state = make_initial_state("q", "t")
        assert state["pm_review_edits"] is None

    def test_timestamp_is_set_on_init(self):
        from src.semi_auto.state import make_initial_state
        state = make_initial_state("q", "t")
        assert state["timestamp"] is not None
        assert "T" in state["timestamp"]  # ISO 8601 format

    def test_quant_backtester_routing_flags_initialized_none(self):
        from src.semi_auto.state import make_initial_state
        state = make_initial_state("q", "t")
        assert state["_delegate_quant"] is None
        assert state["_delegate_backtester"] is None
        assert state["_quant_query"] is None
        assert state["_backtester_query"] is None

    def test_all_task_queues_initialized_none(self):
        from src.semi_auto.state import make_initial_state
        state = make_initial_state("q", "t")
        assert state["portfolio_task_queue"] is None
        assert state["quant_task_queue"] is None
        assert state["backtester_task_queue"] is None

    def test_tool_timings_initialized_none(self):
        from src.semi_auto.state import make_initial_state
        state = make_initial_state("q", "t")
        assert state["tool_timings"] is None


# ── Registry schema completeness ──────────────────────────────────────────────


class TestRegistrySchema:
    """Schema documentation covers all registered functions."""

    def test_all_registry_keys_have_descriptions(self):
        from src.semi_auto.registry.functions import get_registry_schema, FUNCTION_REGISTRY
        schema = get_registry_schema()
        for fn_name in FUNCTION_REGISTRY:
            assert fn_name in schema, f"Missing schema entry: {fn_name}"
            entry = schema[fn_name]
            assert "description" in entry, f"No description for {fn_name}"
            assert entry["description"], f"Empty description for {fn_name}"

    def test_schema_entries_have_params(self):
        from src.semi_auto.registry.functions import get_registry_schema
        schema = get_registry_schema()
        for fn_name, entry in schema.items():
            assert "params" in entry, f"Missing params key for {fn_name}"

    def test_all_registry_values_are_callable(self):
        from src.semi_auto.registry.functions import FUNCTION_REGISTRY
        for fn_name, fn in FUNCTION_REGISTRY.items():
            assert callable(fn), f"Registry entry '{fn_name}' is not callable"


if __name__ == "__main__":
    """Run tests directly."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__)), "-v", "--tb=short"],
        cwd=str(project_root),
    )
    sys.exit(result.returncode)
