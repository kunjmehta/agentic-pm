"""GraphState TypedDict for the semi-auto multi-agent LangGraph system.

All fields are Optional except required inputs (query, thread_id, etc.).
Nodes populate their slice of state and return a partial dict.

State lifecycle:
  context_node          → conversation_id, turn_number, prior_turns
  classify_intent       → intent, symbol, bt_workflow
  data_availability_node→ data_availability
  market_hours_guard    → routing_error (if blocked)
  portfolio_node        → portfolio_task_queue, portfolio_reasoning, delegation flags
  quant_node            → quant_task_queue, quant_reasoning
  backtester_node       → backtester_task_queue, backtester_reasoning
  executor_node         → execution_results, tool_timings
  synthesizer_node      → final_response, execution_time_ms
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict


class GraphState(TypedDict):
    """Shared state for the semi-auto reasoning-agent graph.

    Populated incrementally as nodes execute. All fields except
    query, thread_id, backtest_mode, and timestamp are optional.
    """

    # ── Required input ──────────────────────────────────────────────────────
    query: str
    thread_id: str
    backtest_mode: bool

    # ── Multi-turn context ──────────────────────────────────────────────────
    conversation_id: Optional[str]          # app-level session UUID
    turn_number: Optional[int]              # incremented each turn
    prior_turns: Optional[List[Dict[str, Any]]]  # last N DB interactions

    # ── Data availability pre-check ────────────────────────────────────────
    data_availability: Optional[Dict[str, Any]]  # set by data_availability_node
    # Shape: {symbol, timeframe, indicators_available, bars_available,
    #         trades_available, indicator_rows, bar_count, trade_count,
    #         latest_indicator_ts, latest_bar_ts, checked_at}

    # ── Intent classification ───────────────────────────────────────────────
    intent: Optional[str]       # "portfolio" | "quant" | "backtest" | "full_analysis"
    symbol: Optional[str]       # extracted ticker e.g. "AAPL"
    bt_workflow: Optional[str]  # "A" | "B" | "C" (backtest sub-workflow)
    routing_error: Optional[str]  # set by guards → short-circuits to synthesizer
    _query_intent: Optional[Dict[str, Any]]  # full QueryIntent.model_dump() from classifier

    # ── PM reasoning routing flags (ephemeral — used only by conditional edges)
    _delegate_quant: Optional[bool]
    _delegate_backtester: Optional[bool]
    _quant_query: Optional[str]
    _backtester_query: Optional[str]

    # ── Task queues (List[dict] — serialized TaskItem.model_dump()) ─────────
    portfolio_task_queue: Optional[List[Dict[str, Any]]]
    quant_task_queue: Optional[List[Dict[str, Any]]]
    backtester_task_queue: Optional[List[Dict[str, Any]]]

    # ── Reasoning traces (shown to user + stored in DB) ──────────────────────
    portfolio_reasoning: Optional[str]
    quant_reasoning: Optional[str]
    backtester_reasoning: Optional[str]

    # ── PM supervisor review of sub-agent task plans ──────────────────────────
    pm_review_approved: Optional[bool]          # True → proceed; False → short-circuit
    pm_review_notes: Optional[str]              # shown to user at HITL approval
    pm_review_edits: Optional[List[Dict[str, Any]]]  # serialized PMFeedback for agents on revision
    review_iteration: Optional[int]             # 0-based; incremented on each PM rejection (max 2)

    # ── Function execution results (task_id → result dict) ───────────────────
    execution_results: Optional[Dict[str, Any]]

    # ── Final output ─────────────────────────────────────────────────────────
    final_response: Optional[str]

    # ── Metadata ─────────────────────────────────────────────────────────────
    error: Optional[str]
    execution_time_ms: Optional[int]
    timestamp: str
    tool_timings: Optional[List[Dict[str, Any]]]


def make_initial_state(
    query: str,
    thread_id: str,
    backtest_mode: bool = False,
    conversation_id: Optional[str] = None,
) -> GraphState:
    """Create a minimal initial GraphState for a new query.

    Args:
        query: User natural-language query.
        thread_id: LangGraph MemorySaver checkpoint key.
        backtest_mode: If True, bypass market/portfolio guards.
        conversation_id: App-level session UUID; generated if None.

    Returns:
        Fully initialised GraphState with all optional fields set to None.
    """
    import uuid as _uuid
    return {  # type: ignore[return-value]
        "query": query,
        "thread_id": thread_id,
        "backtest_mode": backtest_mode,
        "conversation_id": conversation_id or str(_uuid.uuid4()),
        "turn_number": None,
        "prior_turns": None,
        "intent": None,
        "symbol": None,
        "bt_workflow": None,
        "routing_error": None,
        "_query_intent": None,
        "_delegate_quant": None,
        "_delegate_backtester": None,
        "_quant_query": None,
        "_backtester_query": None,
        "portfolio_task_queue": None,
        "quant_task_queue": None,
        "backtester_task_queue": None,
        "portfolio_reasoning": None,
        "quant_reasoning": None,
        "backtester_reasoning": None,
        "pm_review_approved": None,
        "pm_review_notes": None,
        "pm_review_edits": None,
        "review_iteration": 0,
        "execution_results": None,
        "final_response": None,
        "error": None,
        "execution_time_ms": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_timings": None,
        "data_availability": None,
    }


if __name__ == "__main__":
    """Smoke test: verify TypedDict can be instantiated."""
    state = make_initial_state(
        query="What is my portfolio status?",
        thread_id="test-thread-001",
        backtest_mode=True,
    )

    print("[OK] GraphState instantiated successfully")
    print(f"     Fields: {list(state.keys())}")
    assert state["query"] == "What is my portfolio status?"
    assert state["backtest_mode"] is True
    assert state["conversation_id"] is not None
    assert state["prior_turns"] is None
    print("[OK] Field access verified")
    print(f"     conversation_id auto-generated: {state['conversation_id']}")
    print("\n[ALL OK] state.py smoke test passed")
