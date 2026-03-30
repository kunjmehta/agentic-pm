"""LangGraph StateGraph assembly for the semi-auto multi-agent system.

Graph topology:

    START
      ↓
    context_node              ← load prior_turns, resolve conversation_id/turn_number
      ↓
    classify_intent           ← keyword tier1 + LLM tier2 fallback
      ↓
    market_hours_guard        ← bypass if backtest_mode
      ↓ routing_error? ─yes─→ synthesizer_node → END
      ↓ no
    portfolio_reasoning_node  ← plans PM tasks + sets delegation flags
      ↓
      ├─ _delegate_quant ──→ quant_reasoning_node ──┐
      │                    (_delegate_backtester?)  │
      │                             ↓ yes           │
      │                    backtester_reasoning_node┤
      │                             ↓ no            │
      ├─ _delegate_backtester only ─────────────────┤
      │                             ↓               │
      │                      pm_review_node ←───────┘
      └─ neither ──────────────────↑
                                   ↓ approved=True
                        *** interrupt_before=["executor_node"] ***
                                executor_node
                                   ↓ approved=False → synthesizer_node
                             synthesizer_node → END

All sub-agent task lists propagate through shared state so pm_review_node
sees the full combined plan before presenting a single HITL approval to the user.
"""

import sys
from pathlib import Path
from typing import Literal, Optional

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.semi_auto.state import GraphState, make_initial_state
from src.semi_auto.nodes.classifier import classify_intent
from src.semi_auto.nodes.context_node import context_node
from src.semi_auto.nodes.guards import market_hours_guard
from src.semi_auto.nodes.portfolio_node import portfolio_reasoning_node
from src.semi_auto.nodes.quant_node import quant_reasoning_node
from src.semi_auto.nodes.backtester_node import backtester_reasoning_node
from src.semi_auto.nodes.pm_review_node import pm_review_node
from src.semi_auto.nodes.executor_node import executor_node
from src.semi_auto.nodes.synthesizer import synthesizer_node
from src.common.utils import get_logger

logger = get_logger(__name__)


# ── Conditional edge functions ────────────────────────────────────────────────


def route_after_market_guard(
    state: GraphState,
) -> Literal["portfolio_reasoning_node", "synthesizer_node"]:
    """Route to synthesizer if market hours guard blocked, else continue.

    Args:
        state: Current GraphState.

    Returns:
        Next node name.
    """
    if state.get("routing_error"):
        logger.info("[route] market_hours_guard blocked → synthesizer_node")
        return "synthesizer_node"
    return "portfolio_reasoning_node"


def route_after_pm_reasoning(state: GraphState) -> str:
    """Route after PM reasoning based on intent and delegation flags.

    Intent-aware routing:
    - backtest  → backtester only (skip quant even if _delegate_quant is set)
    - quant     → quant only (no backtester chain)
    - full_analysis → quant first, then backtester via route_after_quant
    - portfolio → pm_review (no sub-agents)

    Short-circuits to synthesizer on error.

    Args:
        state: Current GraphState.

    Returns:
        Next node name string.
    """
    if state.get("error"):
        logger.info("[route] error after PM → synthesizer_node")
        return "synthesizer_node"
    intent = state.get("intent", "")
    # backtest intent: go directly to backtester — do not run quant
    if intent == "backtest":
        if state.get("_delegate_backtester"):
            logger.info("[route] PM → backtester_reasoning_node (backtest intent)")
            return "backtester_reasoning_node"
        logger.info("[route] PM → pm_review_node (backtest, no backtester delegation)")
        return "pm_review_node"
    # quant intent: quant only — route_after_quant will not chain to backtester
    if intent == "quant":
        if state.get("_delegate_quant"):
            logger.info("[route] PM → quant_reasoning_node (quant intent)")
            return "quant_reasoning_node"
        logger.info("[route] PM → pm_review_node (quant, no quant delegation)")
        return "pm_review_node"
    # full_analysis / portfolio / unknown: use delegation flags (quant first if set)
    if state.get("_delegate_quant"):
        logger.info("[route] PM → quant_reasoning_node")
        return "quant_reasoning_node"
    if state.get("_delegate_backtester"):
        logger.info("[route] PM → backtester_reasoning_node (no quant)")
        return "backtester_reasoning_node"
    logger.info("[route] PM → pm_review_node (no sub-agents)")
    return "pm_review_node"


def route_after_quant(state: GraphState) -> str:
    """After quant: chain to backtester only for full_analysis, else go to review.

    For quant-only intent the backtester is never run even if _delegate_backtester
    is set, keeping the two agents independent.

    Args:
        state: Current GraphState.

    Returns:
        Next node name string.
    """
    if state.get("error"):
        logger.info("[route] error after quant → synthesizer_node")
        return "synthesizer_node"
    if state.get("intent") == "full_analysis" and state.get("_delegate_backtester"):
        logger.info("[route] quant done → backtester_reasoning_node (full_analysis)")
        return "backtester_reasoning_node"
    logger.info("[route] quant done → pm_review_node")
    return "pm_review_node"


def route_after_backtester(state: GraphState) -> str:
    """After backtester: always go to PM review.

    Args:
        state: Current GraphState.

    Returns:
        Next node name string.
    """
    if state.get("error"):
        logger.info("[route] error after backtester → synthesizer_node")
        return "synthesizer_node"
    logger.info("[route] backtester done → pm_review_node")
    return "pm_review_node"


def route_after_pm_review(state: GraphState) -> str:
    """PM review gate: approved → executor (HITL), rejected → revise or synthesizer.

    On rejection, routes back to quant/backtester for up to 2 revision iterations
    before giving up and routing to synthesizer.

    Args:
        state: Current GraphState.

    Returns:
        Next node name string.
    """
    if state.get("error"):
        logger.info("[route] error after pm_review → synthesizer_node")
        return "synthesizer_node"
    if state.get("pm_review_approved") is False:
        iteration = state.get("review_iteration") or 0
        if iteration < 2:
            # Route back to the sub-agent that owns this intent for revision
            intent = state.get("intent", "")
            if intent == "backtest" and state.get("_delegate_backtester"):
                logger.info(f"[route] PM rejected (iter={iteration}) → backtester_reasoning_node for revision")
                return "backtester_reasoning_node"
            if state.get("_delegate_quant"):
                logger.info(f"[route] PM rejected (iter={iteration}) → quant_reasoning_node for revision")
                return "quant_reasoning_node"
            if state.get("_delegate_backtester"):
                logger.info(f"[route] PM rejected (iter={iteration}) → backtester_reasoning_node for revision")
                return "backtester_reasoning_node"
        logger.warning(f"[route] PM rejected plan (iter={iteration}, max reached) → synthesizer_node")
        return "synthesizer_node"
    logger.info("[route] PM approved → executor_node (HITL)")
    return "executor_node"


# ── Graph assembly ─────────────────────────────────────────────────────────────


def build_graph(checkpointer: Optional[MemorySaver] = None) -> StateGraph:
    """Build and compile the semi-auto multi-agent StateGraph.

    Args:
        checkpointer: Optional MemorySaver for conversation persistence.
                      Defaults to a new MemorySaver instance.

    Returns:
        Compiled LangGraph StateGraph with interrupt_before=["executor_node"].
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder = StateGraph(GraphState)

    # ── Register nodes ─────────────────────────────────────────────────────
    builder.add_node("context_node", context_node)
    builder.add_node("classify_intent", classify_intent)
    builder.add_node("market_hours_guard", market_hours_guard)
    builder.add_node("portfolio_reasoning_node", portfolio_reasoning_node)
    builder.add_node("quant_reasoning_node", quant_reasoning_node)
    builder.add_node("backtester_reasoning_node", backtester_reasoning_node)
    builder.add_node("pm_review_node", pm_review_node)
    builder.add_node("executor_node", executor_node)
    builder.add_node("synthesizer_node", synthesizer_node)

    # ── Fixed edges ────────────────────────────────────────────────────────
    builder.add_edge(START, "context_node")
    builder.add_edge("context_node", "classify_intent")
    builder.add_edge("classify_intent", "market_hours_guard")
    builder.add_edge("executor_node", "synthesizer_node")
    builder.add_edge("synthesizer_node", END)

    # ── Conditional edges ──────────────────────────────────────────────────
    builder.add_conditional_edges(
        "market_hours_guard",
        route_after_market_guard,
        {
            "portfolio_reasoning_node": "portfolio_reasoning_node",
            "synthesizer_node": "synthesizer_node",
        },
    )

    builder.add_conditional_edges(
        "portfolio_reasoning_node",
        route_after_pm_reasoning,
        {
            "quant_reasoning_node": "quant_reasoning_node",
            "backtester_reasoning_node": "backtester_reasoning_node",
            "pm_review_node": "pm_review_node",
            "synthesizer_node": "synthesizer_node",
        },
    )

    builder.add_conditional_edges(
        "quant_reasoning_node",
        route_after_quant,
        {
            "backtester_reasoning_node": "backtester_reasoning_node",
            "pm_review_node": "pm_review_node",
            "synthesizer_node": "synthesizer_node",
        },
    )

    builder.add_conditional_edges(
        "backtester_reasoning_node",
        route_after_backtester,
        {
            "pm_review_node": "pm_review_node",
            "synthesizer_node": "synthesizer_node",
        },
    )

    builder.add_conditional_edges(
        "pm_review_node",
        route_after_pm_review,
        {
            "executor_node": "executor_node",
            "quant_reasoning_node": "quant_reasoning_node",          # revision cycle
            "backtester_reasoning_node": "backtester_reasoning_node", # revision cycle
            "synthesizer_node": "synthesizer_node",
        },
    )

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["executor_node"],  # HITL: unified task approval pause
    )


if __name__ == "__main__":
    """Topology verification and smoke test."""
    import time

    print("=" * 60)
    print("Semi-Auto Graph Assembly Verification")
    print("=" * 60)

    print("\n[1/3] Building graph...")
    g = build_graph()
    print("[OK] Graph compiled with interrupt_before=['executor_node']")

    print("\n[2/3] Graph topology:")
    graph_repr = g.get_graph()
    node_names = [n.name for n in graph_repr.nodes.values()]
    edge_list = [(e.source, e.target) for e in graph_repr.edges]
    print(f"     Nodes ({len(node_names)}): {node_names}")
    print(f"     Edges ({len(edge_list)}):")
    for src, tgt in edge_list:
        print(f"       {src} -> {tgt}")

    expected_nodes = {
        "context_node", "classify_intent", "market_hours_guard",
        "portfolio_reasoning_node", "quant_reasoning_node",
        "backtester_reasoning_node", "pm_review_node",
        "executor_node", "synthesizer_node",
    }
    for node in expected_nodes:
        assert node in node_names, f"Missing node: {node}"
    print("[OK] All expected nodes present")

    print("\n[3/3] Smoke test — portfolio query with backtest_mode=True")
    initial = make_initial_state(
        query="What is my portfolio status?",
        thread_id="smoke-test-semi-002",
        backtest_mode=True,
    )
    config = {"configurable": {"thread_id": "smoke-test-semi-002"}}

    start = time.monotonic()
    snapshot = g.invoke(initial, config=config)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    print(f"[OK] First invoke completed in {elapsed_ms}ms")
    print(f"     intent:              {snapshot.get('intent')}")
    print(f"     portfolio_reasoning: {str(snapshot.get('portfolio_reasoning', ''))[:60]}...")
    print(f"     pm_task_queue:       {len(snapshot.get('portfolio_task_queue') or [])} tasks")
    print(f"     pm_review_approved:  {snapshot.get('pm_review_approved')}")
    print(f"     pm_review_notes:     {str(snapshot.get('pm_review_notes', ''))[:80]}")

    exec_results = snapshot.get("execution_results")
    if exec_results is None:
        print("[OK] Graph interrupted before executor (HITL checkpoint active)")
    else:
        print(f"[INFO] execution_results already populated ({len(exec_results)} results)")

    print("\n" + "=" * 60)
    print("Semi-auto graph tests complete!")
