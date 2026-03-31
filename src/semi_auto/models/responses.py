"""Pydantic response models for the semi-auto API and graph output.

SemiAutoResponse is the final structured output returned after full graph execution.
TaskPreviewResponse is returned when the graph is interrupted before execution (HITL).
ApprovalRequest is the body for /v1/approve to optionally modify task queues.
SemiAutoQueryRequest is the POST body for /v1/query.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExecutionResult(BaseModel):
    """Result of a single task execution.

    Attributes:
        task_id: Matches TaskItem.task_id.
        function_name: Registry function that was called.
        status: "success" | "error" | "skipped".
        result: Return value from the function (None on error/skip).
        error: Error message if status == "error".
        duration_ms: Execution wall-clock time in milliseconds.
    """

    task_id: str
    function_name: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


class TaskPreviewResponse(BaseModel):
    """Response returned when the graph pauses for human-in-the-loop approval.

    Returned by POST /v1/query when interrupt_before=["executor_node"] fires.
    The caller must POST to /v1/approve/{thread_id} to continue execution.

    Attributes:
        status: Always "pending_approval".
        thread_id: LangGraph MemorySaver checkpoint key — required for resume.
        conversation_id: App-level session UUID.
        portfolio_reasoning: PM reasoning summary.
        quant_reasoning: Quant reasoning summary (if delegated).
        backtester_reasoning: Backtester reasoning summary (if delegated).
        portfolio_tasks: Serialized PM task queue.
        quant_tasks: Serialized quant task queue.
        backtester_tasks: Serialized backtester task queue.
        message: Instructions for the API caller.
    """

    status: str = "pending_approval"
    thread_id: str
    conversation_id: str
    portfolio_reasoning: Optional[str] = None
    quant_reasoning: Optional[str] = None
    backtester_reasoning: Optional[str] = None
    pm_review_notes: Optional[str] = None   # PM supervisor verdict on sub-agent plans
    portfolio_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    quant_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    backtester_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    message: str = "Review the planned tasks and call POST /v1/approve/{thread_id} to proceed"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ApprovalRequest(BaseModel):
    """Request body for POST /v1/approve/{thread_id}.

    Allows the caller to optionally override any of the task queues
    before execution. Pass None (omit) to keep the reasoning-node output.

    Attributes:
        modified_portfolio_tasks: Replacement for portfolio_task_queue in state.
        modified_quant_tasks: Replacement for quant_task_queue in state.
        modified_backtester_tasks: Replacement for backtester_task_queue in state.
    """

    modified_portfolio_tasks: Optional[List[Dict[str, Any]]] = None
    modified_quant_tasks: Optional[List[Dict[str, Any]]] = None
    modified_backtester_tasks: Optional[List[Dict[str, Any]]] = None


class SemiAutoResponse(BaseModel):
    """Final structured response returned after complete graph execution.

    Attributes:
        query: Original user query.
        thread_id: LangGraph checkpoint key.
        conversation_id: App-level session UUID.
        turn_number: Conversation turn index.
        intent: Classified intent.
        symbol: Extracted ticker or None.
        portfolio_reasoning: PM reasoning trace shown to user.
        quant_reasoning: Quant reasoning trace (if applicable).
        backtester_reasoning: Backtester reasoning trace (if applicable).
        final_response: Synthesized natural-language response.
        tasks_executed: Total number of tasks run.
        execution_results: Per-task results.
        timestamp: ISO 8601 response timestamp.
        execution_time_ms: Total wall-clock time.
        status: "success" | "error".
        error: Top-level error message if status == "error".
    """

    query: str
    thread_id: str
    conversation_id: str
    turn_number: int
    intent: Optional[str] = None
    symbol: Optional[str] = None
    portfolio_reasoning: Optional[str] = None
    quant_reasoning: Optional[str] = None
    backtester_reasoning: Optional[str] = None
    final_response: str
    tasks_executed: int = 0
    execution_results: List[ExecutionResult] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    execution_time_ms: Optional[int] = None
    status: str = "success"
    error: Optional[str] = None


class SemiAutoQueryRequest(BaseModel):
    """Request body for POST /v1/query.

    Attributes:
        query: User's natural-language query. Required.
        thread_id: Existing thread UUID for multi-turn conversations.
                   Auto-generated if omitted.
        conversation_id: App-level session UUID. Auto-generated if omitted.
        backtest_mode: If True, bypass market-hours and portfolio guards.
        stream_reasoning: If True, SSE stream includes reasoning trace events.
    """

    query: str = Field(..., min_length=1)
    thread_id: Optional[str] = None
    conversation_id: Optional[str] = None
    backtest_mode: bool = False
    stream_reasoning: bool = False


# ===========================================================================
# Synthesizer Structured Output — SynthesisResult
# ===========================================================================

class MetricRow(BaseModel):
    """A single row in a structured metrics table.

    Attributes:
        metric: Human-readable metric label.
        value: Pre-formatted value string (percentage, dollar, ratio, etc.).
    """

    metric: str = Field(description="Human-readable metric label")
    value: str = Field(description="Pre-formatted value string")


class ContentSection(BaseModel):
    """A named section of the synthesis output.

    Each section has a title and may contain any combination of a metrics table,
    bullet-point observations, and an optional italic footnote.

    Attributes:
        title: Section heading, e.g. ``"Returns"``, ``"Signals"``.
        table: Ordered list of MetricRow items for tabular numeric data.
        bullets: Short qualitative observations.
        note: Single italic note (e.g. for caveats or missing data).
    """

    title: str = Field(description="Section heading")
    table: List[MetricRow] = Field(
        default_factory=list, description="Ordered metric rows for table rendering"
    )
    bullets: List[str] = Field(
        default_factory=list, description="Short qualitative observations"
    )
    note: Optional[str] = Field(
        default=None, description="Optional italic caveat or footnote"
    )


class SynthesisResult(BaseModel):
    """Structured synthesis output produced by the synthesizer LLM via ``with_structured_output``.

    This model replaces free-form markdown generation — the LLM fills in each
    structured field and the synthesizer then renders them deterministically into
    well-formatted Markdown for the UI.

    Attributes:
        headline: Short descriptive title, e.g. ``"AAPL — Mean-Reversion Backtest"``.
        intent: Analysis type — ``"backtest"`` | ``"quant"`` | ``"portfolio"`` | ``"mixed"``.
        verdict: Backtest-only verdict: ``"RECOMMENDED"`` or ``"NOT RECOMMENDED"``.
        summary_quote: Verbatim one-sentence summary from backtest result.
        overall_signal: Quant-only top-level signal: ``"BUY"`` | ``"SELL"`` | ``"HOLD"``.
        signal_confidence: Quant signal confidence: ``"High"`` | ``"Medium"`` | ``"Low"``.
        sections: Ordered list of ContentSection (Returns, Risk, Trade Stats, Signals, etc.).
        takeaway: One-sentence bottom-line conclusion shown as a blockquote.
        agents_used: Agents that contributed, e.g. ``["PM", "Quant"]``.
        error_note: Brief note when some tasks failed or data was unavailable.
    """

    headline: str = Field(
        description="Short title — symbol + analysis type, e.g. 'AAPL — Mean-Reversion Backtest'"
    )
    intent: str = Field(
        description="Analysis type: 'backtest' | 'quant' | 'portfolio' | 'mixed'"
    )
    verdict: Optional[str] = Field(
        default=None,
        description="Backtest only: 'RECOMMENDED' or 'NOT RECOMMENDED'",
    )
    summary_quote: Optional[str] = Field(
        default=None,
        description="Verbatim one-sentence backtest summary to render as a blockquote",
    )
    overall_signal: Optional[str] = Field(
        default=None,
        description="Quant only: 'BUY' | 'SELL' | 'HOLD'",
    )
    signal_confidence: Optional[str] = Field(
        default=None,
        description="Quant signal confidence: 'High' | 'Medium' | 'Low'",
    )
    sections: List[ContentSection] = Field(
        default_factory=list,
        description="Ordered content sections (Returns, Risk, Trade Stats, Signals, etc.)",
    )
    takeaway: str = Field(
        description="One-sentence bottom-line conclusion rendered as a blockquote"
    )
    agents_used: List[str] = Field(
        default_factory=list,
        description="Contributing agents, e.g. ['PM', 'Quant', 'Backtester']",
    )
    error_note: Optional[str] = Field(
        default=None,
        description="Brief note about failed tasks or unavailable data",
    )


if __name__ == "__main__":
    """Smoke test: instantiate all response models."""
    print("=" * 60)
    print("models/responses.py Smoke Tests")
    print("=" * 60)

    # ExecutionResult
    er = ExecutionResult(
        task_id="pm_001",
        function_name="get_portfolio_status",
        status="success",
        result={"equity": 100000.0},
        duration_ms=340,
    )
    assert er.status == "success"
    print("[OK] ExecutionResult")

    # TaskPreviewResponse
    preview = TaskPreviewResponse(
        thread_id="test-thread-001",
        conversation_id="conv-001",
        portfolio_reasoning="PM planned portfolio status check.",
        portfolio_tasks=[{"task_id": "pm_001", "function_name": "get_portfolio_status"}],
    )
    assert preview.status == "pending_approval"
    print("[OK] TaskPreviewResponse")

    # ApprovalRequest
    approval = ApprovalRequest(modified_portfolio_tasks=None)
    assert approval.modified_portfolio_tasks is None
    print("[OK] ApprovalRequest (no modifications)")

    # SemiAutoResponse
    response = SemiAutoResponse(
        query="What is my portfolio status?",
        thread_id="test-thread-001",
        conversation_id="conv-001",
        turn_number=1,
        final_response="Portfolio is healthy at $100,000 equity.",
        execution_results=[er],
        tasks_executed=1,
    )
    assert response.status == "success"
    assert len(response.execution_results) == 1
    print("[OK] SemiAutoResponse")

    # SemiAutoQueryRequest
    req = SemiAutoQueryRequest(query="Analyze AAPL", backtest_mode=True)
    assert req.backtest_mode is True
    assert req.thread_id is None
    print("[OK] SemiAutoQueryRequest")

    # SynthesisResult — backtest shape
    sr = SynthesisResult(
        headline="AAPL — Mean-Reversion Backtest",
        intent="backtest",
        verdict="RECOMMENDED",
        summary_quote="Strategy generated 12.5% return with controlled drawdown.",
        sections=[
            ContentSection(
                title="Returns",
                table=[
                    MetricRow(metric="Total Return", value="+12.50%"),
                    MetricRow(metric="Sharpe Ratio", value="1.340"),
                ],
                bullets=["Outperformed buy-and-hold by 4%"],
            ),
            ContentSection(
                title="Risk",
                table=[MetricRow(metric="Max Drawdown", value="-8.20%")],
                note="Sortino unavailable due to no negative-return days in dataset",
            ),
        ],
        takeaway="The mean-reversion strategy on AAPL delivered solid risk-adjusted returns for the period.",
        agents_used=["PM", "Backtester"],
    )
    assert sr.verdict == "RECOMMENDED"
    assert len(sr.sections) == 2
    assert sr.sections[0].table[0].metric == "Total Return"
    print("[OK] SynthesisResult (backtest shape)")

    # SynthesisResult — quant shape
    sq = SynthesisResult(
        headline="AAPL Technical Analysis",
        intent="quant",
        overall_signal="BUY",
        signal_confidence="Medium",
        sections=[
            ContentSection(
                title="Momentum",
                table=[
                    MetricRow(metric="RSI (14)", value="58.3"),
                    MetricRow(metric="MACD Histogram", value="+0.42"),
                ],
                bullets=["MACD crossed signal line bullishly 3 days ago"],
            ),
        ],
        takeaway="Momentum and volume point to a short-term BUY entry with medium conviction.",
        agents_used=["PM", "Quant"],
    )
    assert sq.overall_signal == "BUY"
    assert sq.verdict is None
    print("[OK] SynthesisResult (quant shape)")

    print("\n[ALL OK] models/responses.py smoke tests passed")
