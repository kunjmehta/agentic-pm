"""GraphState TypedDict for the deterministic LangGraph agent.

Defines the shared state schema passed between all graph nodes.
Each field is Optional to allow nodes to populate incrementally.
"""

from typing import List, Optional, TypedDict


class GraphState(TypedDict):
    """Shared state for the deterministic portfolio manager graph.

    Populated incrementally as nodes execute. All fields except
    query, thread_id, backtest_mode, and timestamp are optional.
    """

    # ── Input ──────────────────────────────────────────────────────────────
    query: str
    thread_id: str
    backtest_mode: bool

    # ── Routing ────────────────────────────────────────────────────────────
    intent: Optional[str]       # "portfolio" | "quant" | "backtest" | "full_analysis"
    bt_workflow: Optional[str]  # "A" | "B" | "C"  (backtest sub-workflow)
    routing_error: Optional[str]  # set by guards → short-circuits to synthesizer
    symbol: Optional[str]       # extracted ticker (e.g. "AAPL")

    # ── Portfolio node outputs ──────────────────────────────────────────────
    portfolio_status: Optional[dict]
    positions_summary: Optional[dict]
    health_check: Optional[dict]
    data_availability: Optional[dict]
    data_fetched: Optional[bool]

    # ── Quant node outputs ──────────────────────────────────────────────────
    quant_analysis: Optional[str]
    indicators: Optional[dict]

    # ── Backtester node outputs ─────────────────────────────────────────────
    backtest_result: Optional[dict]
    backtest_run_id: Optional[str]

    # ── PM synthesis ────────────────────────────────────────────────────────
    final_response: Optional[str]

    # ── Metadata ────────────────────────────────────────────────────────────
    error: Optional[str]
    execution_time_ms: Optional[int]
    timestamp: str
    tool_timings: Optional[List[dict]]


if __name__ == "__main__":
    """Smoke-test: verify TypedDict can be instantiated with required fields."""
    from datetime import datetime, timezone

    state: GraphState = {  # type: ignore[assignment]
        "query": "What is my portfolio status?",
        "thread_id": "test-thread-001",
        "backtest_mode": True,
        "intent": None,
        "bt_workflow": None,
        "routing_error": None,
        "symbol": None,
        "portfolio_status": None,
        "positions_summary": None,
        "health_check": None,
        "data_availability": None,
        "data_fetched": None,
        "quant_analysis": None,
        "indicators": None,
        "backtest_result": None,
        "backtest_run_id": None,
        "final_response": None,
        "error": None,
        "execution_time_ms": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_timings": None,
    }

    print("[OK] GraphState instantiated successfully")
    print(f"     Fields: {list(state.keys())}")
    assert state["query"] == "What is my portfolio status?"
    assert state["backtest_mode"] is True
    print("[OK] Field access verified")
