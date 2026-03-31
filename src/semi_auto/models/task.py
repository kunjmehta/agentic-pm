"""Pydantic models for agent task planning in the semi-auto multi-agent system.

PM agent:
  TaskItem  → full call spec (function_name, params, priority, depends_on, ...)
  TaskList  → ordered list of TaskItems + reasoning_summary
  AgentOutput → TaskList + delegation flags

Quant / Backtester agents (simpler):
  FunctionCall → (task_id, function_name, params, priority, depends_on)
  AgentPlan    → List[FunctionCall] + one-sentence reasoning_summary

PM review (structured edits, no free text):
  FunctionCallEdit → targeted change to a specific FunctionCall by index
  PMFeedback       → approved flag + per-agent edit lists + one-sentence reason
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskItem(BaseModel):
    """A single planned function call with its parameters.

    Attributes:
        task_id: Unique identifier (e.g. "pm_001", "qa_002", "bt_001").
        function_name: Key in FUNCTION_REGISTRY to look up callable.
        params: Keyword arguments to pass to the function.
        description: Human-readable rationale for choosing this task.
        priority: Execution priority. 1=high (parallel), 3=low (sequential).
        depends_on: List of task_ids whose results must be injected as params.
        retry_count: Number of times this task has been retried after failure.
    """

    task_id: str = Field(description="Unique ID, e.g. 'pm_001'")
    function_name: str = Field(description="Registry key matching functions.py")
    params: Dict[str, Any] = Field(default_factory=dict)
    description: str = Field(description="Human-readable reason for this call")
    priority: int = Field(default=1, ge=1, le=3, description="1=high (parallel), 3=low (sequential)")
    depends_on: List[str] = Field(default_factory=list, description="task_ids whose results must be injected")
    retry_count: int = Field(default=0, description="Number of retries attempted")


class TaskList(BaseModel):
    """Ordered list of tasks with a reasoning summary.

    Attributes:
        tasks: List of TaskItem objects to execute.
        reasoning_summary: One-paragraph explanation shown to user and stored in DB.
    """

    tasks: List[TaskItem] = Field(default_factory=list)
    reasoning_summary: str = Field(
        description="One-paragraph summary of why these tasks were chosen"
    )


class AgentOutput(BaseModel):
    """Structured output from the Portfolio Manager reasoning node.

    Extends TaskList with delegation flags for sub-agent reasoning.

    Attributes:
        task_list: PM's own task list (direct function calls).
        delegate_to_quant: Whether to invoke the Quant reasoning node.
        delegate_to_backtester: Whether to invoke the Backtester reasoning node.
        quant_query: Focused sub-query to pass to quant node.
        backtester_query: Focused sub-query to pass to backtester node.
    """

    task_list: TaskList
    delegate_to_quant: bool = Field(default=False)
    delegate_to_backtester: bool = Field(default=False)
    quant_query: Optional[str] = Field(default=None)
    backtester_query: Optional[str] = Field(default=None)


class FunctionCall(BaseModel):
    """A single function call with scheduling metadata.

    Used by Quant and Backtester agents as their output unit.
    At execution time, function_name is resolved to a callable via FUNCTION_REGISTRY.

    Attributes:
        task_id: Unique ID for dependency tracking (e.g. "bt_001"). Auto-generated if None.
        function_name: Key in FUNCTION_REGISTRY.
        params: Keyword arguments passed directly to the registered function.
        priority: Execution priority. 1=high (parallel), 3=sequential write operation.
        depends_on: task_ids whose results must complete before this task runs.
    """

    task_id: Optional[str] = Field(default=None, description="Unique ID e.g. 'bt_001'. Auto-assigned if None.")
    function_name: str = Field(description="Registry key — must match FUNCTION_REGISTRY exactly")
    params: Dict[str, Any] = Field(default_factory=dict, description="Keyword arguments for the function")
    priority: int = Field(default=1, ge=1, le=3, description="1=parallel, 3=sequential (write ops)")
    depends_on: List[str] = Field(default_factory=list, description="task_ids that must complete first")


class AgentPlan(BaseModel):
    """Structured output from Quant or Backtester reasoning node.

    Attributes:
        calls: Ordered list of function calls to execute (max 5, max 3 unique names).
        reasoning_summary: One sentence explaining the overall plan.
    """

    calls: List[FunctionCall] = Field(
        default_factory=list,
        description="Ordered list of function calls. Max 5 total, max 3 unique function_names.",
    )
    reasoning_summary: str = Field(description="One sentence explaining what this plan does")


class FunctionCallEdit(BaseModel):
    """A targeted edit to a single FunctionCall in an AgentPlan by its 0-based index.

    Attributes:
        index: 0-based position of the call to edit in the calls list.
        action: "remove" | "update_params" | "replace_function".
        new_function_name: Replacement function name (action=replace_function only).
        new_params: Replacement params dict (action=update_params only).
    """

    index: int = Field(description="0-based index of the call to edit")
    action: str = Field(description="One of: 'remove' | 'update_params' | 'replace_function'")
    new_function_name: Optional[str] = Field(default=None, description="New function name (replace_function only)")
    new_params: Optional[Dict[str, Any]] = Field(default=None, description="New params (update_params only)")


class PMFeedback(BaseModel):
    """Structured PM review of Quant and Backtester AgentPlans.

    PM applies edits directly to the plans — no free-text rejection notes.
    If approved=False, the graph routes agents back for a full re-plan.

    Attributes:
        approved: True if both plans are ready to execute (after applying edits).
        quant_edits: Edits to apply to the Quant AgentPlan.calls list.
        backtester_edits: Edits to apply to the Backtester AgentPlan.calls list.
        reason: One sentence (only if approved=False). Empty string if approved.
    """

    approved: bool = Field(description="True if plans are correct and ready to execute after applying edits")
    quant_edits: List[FunctionCallEdit] = Field(
        default_factory=list,
        description="Edits to apply to quant calls. Empty if no changes needed.",
    )
    backtester_edits: List[FunctionCallEdit] = Field(
        default_factory=list,
        description="Edits to apply to backtester calls. Empty if no changes needed.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="One sentence explaining what structural problem remains (only if approved=False)",
    )


class AgentReasoning(BaseModel):
    """Serializable reasoning trace stored in state and persisted to DB.

    Attributes:
        agent: Agent name — "portfolio" | "quant" | "backtester".
        turn_number: Current conversation turn index.
        reasoning_summary: Short explanation of the planning decision.
        tasks_planned: Serialized TaskItem dicts.
        delegations: Names of agents delegated to.
        timestamp: ISO 8601 timestamp.
    """

    agent: str
    turn_number: int
    reasoning_summary: str
    tasks_planned: List[Dict[str, Any]] = Field(default_factory=list)
    delegations: List[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    """Smoke test: instantiate all models and verify serialization."""
    print("=" * 60)
    print("models/task.py Smoke Tests")
    print("=" * 60)

    # FunctionCall
    fc = FunctionCall(function_name="calc_momentum", params={"symbol": "AAPL", "timeframe": "1Day"})
    assert fc.function_name == "calc_momentum"
    print("[OK] FunctionCall")

    # AgentPlan
    plan = AgentPlan(
        calls=[fc, FunctionCall(function_name="calc_volatility_bands", params={"symbol": "AAPL"})],
        reasoning_summary="Compute momentum and volatility for AAPL.",
    )
    assert len(plan.calls) == 2
    print("[OK] AgentPlan")

    # FunctionCallEdit
    edit = FunctionCallEdit(index=0, action="update_params", new_params={"symbol": "MSFT"})
    assert edit.index == 0
    print("[OK] FunctionCallEdit")

    # PMFeedback approved
    fb_ok = PMFeedback(approved=True)
    assert fb_ok.quant_edits == []
    print("[OK] PMFeedback (approved)")

    # PMFeedback with edits
    fb_edit = PMFeedback(
        approved=True,
        quant_edits=[edit],
        reason=None,
    )
    assert len(fb_edit.quant_edits) == 1
    print("[OK] PMFeedback (with edits)")

    # TaskItem
    item = TaskItem(
        task_id="pm_001",
        function_name="get_portfolio_status",
        params={},
        description="Fetch current portfolio equity and position counts",
    )
    assert item.task_id == "pm_001"
    assert item.priority == 1
    assert item.depends_on == []
    print("[OK] TaskItem instantiated and defaults correct")

    # Dependent task
    dep_item = TaskItem(
        task_id="pm_003",
        function_name="check_portfolio_health",
        params={},
        description="Check portfolio health using prior status and positions",
        priority=2,
        depends_on=["pm_001", "pm_002"],
    )
    assert dep_item.depends_on == ["pm_001", "pm_002"]
    print("[OK] TaskItem with depends_on correct")

    # TaskList
    tl = TaskList(
        tasks=[item, dep_item],
        reasoning_summary="Fetch portfolio status and health check.",
    )
    assert len(tl.tasks) == 2
    serialized = tl.model_dump()
    assert "tasks" in serialized
    print("[OK] TaskList serialized correctly")

    # AgentOutput
    ao = AgentOutput(
        task_list=tl,
        delegate_to_quant=True,
        quant_query="Analyze AAPL momentum indicators",
    )
    assert ao.delegate_to_quant is True
    assert ao.delegate_to_backtester is False
    print("[OK] AgentOutput delegation flags correct")

    # AgentReasoning
    ar = AgentReasoning(
        agent="portfolio",
        turn_number=1,
        reasoning_summary="PM planned 2 tasks and delegated to quant.",
        tasks_planned=[item.model_dump()],
        delegations=["quant"],
    )
    assert ar.agent == "portfolio"
    assert "quant" in ar.delegations
    print("[OK] AgentReasoning serialized correctly")

    print("\n[ALL OK] models/task.py smoke tests passed")
