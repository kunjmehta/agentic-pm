"""LangGraph StateGraph assembly for the deterministic portfolio manager.

All routing is governed by explicit conditional edge functions — zero LLM
involvement in graph flow. LLMs are used only inside node functions for
analysis and synthesis.

Graph topology:

    START
      ↓
    classify_intent          ← keyword tier 1; LLM tier 2 (ambiguous only)
      ↓
    market_hours_guard       ← reuses MarketHoursGuardMiddleware
      ↓ routing_error? ─yes─→ synthesizer → END
      ↓ no
    portfolio_guard          ← reuses PortfolioGuardMiddleware
      ↓ routing_error? ─yes─→ synthesizer → END
      ↓ no (conditional on intent)
      ├─ "portfolio"     → portfolio_node → synthesizer → END
      ├─ "quant"         → quant_node → synthesizer → END
      ├─ "backtest"      → portfolio_node → backtester_node → synthesizer → END
      └─ "full_analysis" → portfolio_node → quant_node → backtester_node → synthesizer → END
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.langgraph.state import GraphState
from src.langgraph.nodes.classifier import classify_intent
from src.langgraph.nodes.guards import market_hours_guard, portfolio_guard
from src.langgraph.nodes.portfolio_node import portfolio_node
from src.langgraph.nodes.quant_node import quant_node
from src.langgraph.nodes.backtester_node import backtester_node
from src.langgraph.nodes.synthesizer import synthesizer
from src.common.utils import get_logger

logger = get_logger(__name__)

# ── Conditional edge functions ────────────────────────────────────────────────


def route_after_market_guard(
    state: GraphState,
) -> Literal["portfolio_guard", "synthesizer"]:
    """Route to synthesizer if market hours guard blocked, else continue.

    Args:
        state: Current GraphState.

    Returns:
        Next node name.
    """
    if state.get("routing_error"):
        logger.info("[route] market_hours_guard blocked → synthesizer")
        return "synthesizer"
    return "portfolio_guard"


def route_after_portfolio_guard(
    state: GraphState,
) -> Literal["portfolio_node", "quant_node", "backtester_node", "synthesizer"]:
    """Route by intent after portfolio guard passes, or to synthesizer on error.

    Args:
        state: Current GraphState.

    Returns:
        Next node name based on intent.
    """
    if state.get("routing_error"):
        logger.info("[route] portfolio_guard blocked → synthesizer")
        return "synthesizer"

    intent = state.get("intent", "portfolio")
    logger.info(f"[route] intent='{intent}'")

    if intent in ("portfolio",):
        return "portfolio_node"
    if intent == "quant":
        return "quant_node"
    if intent in ("backtest", "full_analysis"):
        return "portfolio_node"

    # Default fallback
    logger.warning(f"[route] unknown intent '{intent}' → portfolio_node")
    return "portfolio_node"


def route_after_portfolio_node(
    state: GraphState,
) -> Literal["quant_node", "backtester_node", "synthesizer"]:
    """Route after portfolio_node based on intent.

    portfolio     → synthesizer (done)
    backtest      → backtester_node
    full_analysis → quant_node (then backtester_node)

    Args:
        state: Current GraphState.

    Returns:
        Next node name.
    """
    intent = state.get("intent", "portfolio")

    if intent == "portfolio":
        return "synthesizer"
    if intent == "backtest":
        return "backtester_node"
    if intent == "full_analysis":
        return "quant_node"

    return "synthesizer"


def route_after_quant_node(
    state: GraphState,
) -> Literal["backtester_node", "synthesizer"]:
    """Route after quant_node: continue to backtester for full_analysis or stop.

    Args:
        state: Current GraphState.

    Returns:
        Next node name.
    """
    intent = state.get("intent", "quant")
    if intent == "full_analysis":
        return "backtester_node"
    return "synthesizer"


# ── Graph assembly ────────────────────────────────────────────────────────────


def build_graph(checkpointer: Optional[MemorySaver] = None) -> StateGraph:
    """Build and compile the deterministic portfolio manager StateGraph.

    Args:
        checkpointer: Optional MemorySaver for conversation persistence.
                      Defaults to a new MemorySaver instance.

    Returns:
        Compiled LangGraph StateGraph.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder = StateGraph(GraphState)

    # ── Register nodes ────────────────────────────────────────────────────────
    builder.add_node("classify_intent", classify_intent)
    builder.add_node("market_hours_guard", market_hours_guard)
    builder.add_node("portfolio_guard", portfolio_guard)
    builder.add_node("portfolio_node", portfolio_node)
    builder.add_node("quant_node", quant_node)
    builder.add_node("backtester_node", backtester_node)
    builder.add_node("synthesizer", synthesizer)

    # ── Fixed edges ───────────────────────────────────────────────────────────
    builder.add_edge(START, "classify_intent")
    builder.add_edge("classify_intent", "market_hours_guard")
    builder.add_edge("backtester_node", "synthesizer")
    builder.add_edge("synthesizer", END)

    # ── Conditional edges ─────────────────────────────────────────────────────
    builder.add_conditional_edges(
        "market_hours_guard",
        route_after_market_guard,
        {
            "portfolio_guard": "portfolio_guard",
            "synthesizer": "synthesizer",
        },
    )

    builder.add_conditional_edges(
        "portfolio_guard",
        route_after_portfolio_guard,
        {
            "portfolio_node": "portfolio_node",
            "quant_node": "quant_node",
            "backtester_node": "backtester_node",
            "synthesizer": "synthesizer",
        },
    )

    builder.add_conditional_edges(
        "portfolio_node",
        route_after_portfolio_node,
        {
            "quant_node": "quant_node",
            "backtester_node": "backtester_node",
            "synthesizer": "synthesizer",
        },
    )

    builder.add_conditional_edges(
        "quant_node",
        route_after_quant_node,
        {
            "backtester_node": "backtester_node",
            "synthesizer": "synthesizer",
        },
    )

    return builder.compile(checkpointer=checkpointer)


def _make_initial_state(
    query: str,
    thread_id: str = "default",
    backtest_mode: bool = False,
) -> GraphState:
    """Create a minimal initial GraphState for a query.

    Args:
        query: User query string.
        thread_id: Conversation thread identifier.
        backtest_mode: Bypass market/portfolio guards if True.

    Returns:
        GraphState TypedDict with required fields populated.
    """
    return {  # type: ignore[return-value]
        "query": query,
        "thread_id": thread_id,
        "backtest_mode": backtest_mode,
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


if __name__ == "__main__":
    """Topology verification and smoke test."""
    import time

    print("=" * 60)
    print("LangGraph Graph Assembly")
    print("=" * 60)

    # Build and print topology
    print("\n[1/3] Building graph...")
    g = build_graph()
    print("[OK] Graph compiled successfully")

    print("\n[2/3] Graph topology (nodes + edges):")
    graph_repr = g.get_graph()
    node_names = [n.name for n in graph_repr.nodes.values()]
    edge_list = [(e.source, e.target) for e in graph_repr.edges]
    print(f"     Nodes ({len(node_names)}): {node_names}")
    print(f"     Edges ({len(edge_list)}):")
    for src, tgt in edge_list:
        print(f"       {src} -> {tgt}")

    # End-to-end smoke test (backtest_mode=True bypasses guards)
    print("\n[3/3] Smoke test — portfolio query")
    start = time.time()
    initial_state = _make_initial_state(
        query="What is my portfolio status?",
        thread_id="smoke-test-001",
        backtest_mode=True,
    )
    config = {"configurable": {"thread_id": "smoke-test-001"}}
    final_state = g.invoke(initial_state, config=config)
    elapsed_ms = int((time.time() - start) * 1000)

    print(f"[OK] completed in {elapsed_ms}ms")
    print(f"     intent:         {final_state.get('intent')}")
    print(f"     final_response: {str(final_state.get('final_response', ''))[:100]}...")
    assert final_state.get("final_response"), "Expected final_response to be set"

    print("\n" + "=" * 60)
    print("Graph tests complete!")
