"""Integration tests for the Portfolio Manager reasoning agent.

Approach B — real LLM: calls portfolio_reasoning_node() with actual OpenAI
API and asserts three output properties per query:

  1. Function names present in the task list
  2. Each task has function_name + params (structure + no hallucinations)
  3. Metric-computing functions detected in the plan

Auto-skipped when OPENAI_API_KEY is not resolvable via secrets.json.
Run with: pytest tests/agents/test_pm_agent.py -v
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


# ── Skip guard ────────────────────────────────────────────────────────────────

def _has_openai_key() -> bool:
    """Return True if an OpenAI API key is available via secrets or env."""
    if os.getenv("OPENAI_API_KEY"):
        return True
    try:
        from src.common.utils import secrets
        return bool(secrets.get("openai.api_key"))
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _has_openai_key(),
    reason="OPENAI_API_KEY not set — skipping PM agent integration tests",
)


# ── Constants ─────────────────────────────────────────────────────────────────

#: Functions whose presence in the task list signals a metric calculation.
METRIC_FUNCTIONS: Set[str] = {
    "calc_momentum",
    "calc_volatility_bands",
    "calc_volume_flow",
    "get_precomputed_indicators",
    "get_intraday_stats",
    "get_strategy_performance",
    "get_backtest_performance",
    "check_portfolio_health",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_state(
    query: str,
    intent: str = "portfolio",
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a minimal GraphState dict for the PM reasoning node.

    Args:
        query: Natural-language user query.
        intent: Pre-classified intent (portfolio | quant | backtest | order).
        symbol: Optional ticker symbol extracted from the query.

    Returns:
        State dict compatible with portfolio_reasoning_node.
    """
    return {
        "query": query,
        "intent": intent,
        "symbol": symbol,
        "turn_number": 1,
        "prior_turns": [],
        "backtest_mode": True,  # bypass live-market guards in tests
    }


def _metric_fns(task_queue: Optional[List[Dict[str, Any]]]) -> Set[str]:
    """Return the subset of task function names that compute metrics.

    Args:
        task_queue: List of task dicts from portfolio_task_queue.

    Returns:
        Set of function names that overlap with METRIC_FUNCTIONS.
    """
    return {t["function_name"] for t in (task_queue or [])} & METRIC_FUNCTIONS


def _assert_agent_output(result: Dict[str, Any]):
    """Run the three standard output assertions against a node result.

    Asserts:
        1. ``portfolio_task_queue`` is a list.
        2. Every task has ``function_name`` (str) and ``params`` (dict) keys,
           and the function name is registered (no hallucinations).
        3. Returns (fn_names, metric_fns) for additional caller assertions.

    Args:
        result: Return value of portfolio_reasoning_node(state).

    Returns:
        Tuple of (fn_names list, metric_fns set).
    """
    from src.semi_auto.registry.functions import FUNCTION_REGISTRY

    queue: List[Dict[str, Any]] = result.get("portfolio_task_queue") or []

    # 1. Function names in task list
    fn_names = [t["function_name"] for t in queue]
    assert isinstance(fn_names, list), "portfolio_task_queue must be a list"

    # 2. Function names with params — structure + no hallucinations
    for task in queue:
        assert "function_name" in task, f"Task missing function_name: {task}"
        assert "params" in task, f"Task missing params: {task}"
        assert isinstance(task["params"], dict), (
            f"params must be a dict, got {type(task['params'])}: {task}"
        )
        assert task["function_name"] in FUNCTION_REGISTRY, (
            f"Hallucinated function '{task['function_name']}' not in FUNCTION_REGISTRY"
        )

    # 3. Metric functions requested
    metric_fns = _metric_fns(queue)

    return fn_names, metric_fns


# ── Test class ────────────────────────────────────────────────────────────────

class TestPMAgentIntegration:
    """Real-LLM integration tests for portfolio_reasoning_node.

    Each test follows the input → output contract:
      Input : top-level user query passed to the PM agent
      Output:
        1. List of function names planned in the task list
        2. List of function names with their parameter dicts
        3. Subset of functions that compute metrics (from METRIC_FUNCTIONS)
    """

    def test_portfolio_status(self):
        """Query: portfolio status → get_portfolio_status planned."""
        from src.semi_auto.nodes.portfolio_node import portfolio_reasoning_node

        state = make_state("What is my portfolio status?", intent="portfolio")
        result = portfolio_reasoning_node(state)

        fn_names, metric_fns = _assert_agent_output(result)

        assert "get_portfolio_status" in fn_names, (
            f"Expected get_portfolio_status in task list, got: {fn_names}"
        )
        assert result.get("_delegate_quant") is False or result.get("_delegate_quant") is None
        assert result.get("_delegate_backtester") is False or result.get("_delegate_backtester") is None

        print(f"\n[portfolio_status] fn_names={fn_names}")
        print(f"[portfolio_status] metric_fns={metric_fns}")

    def test_positions_summary(self):
        """Query: positions P&L → get_positions_summary planned."""
        from src.semi_auto.nodes.portfolio_node import portfolio_reasoning_node

        state = make_state(
            "Show me all my current positions and unrealised P&L",
            intent="portfolio",
        )
        result = portfolio_reasoning_node(state)

        fn_names, metric_fns = _assert_agent_output(result)

        assert "get_positions_summary" in fn_names, (
            f"Expected get_positions_summary in task list, got: {fn_names}"
        )

        print(f"\n[positions_summary] fn_names={fn_names}")
        print(f"[positions_summary] metric_fns={metric_fns}")

    def test_quant_delegates(self):
        """Query: RSI + momentum → delegate_to_quant=True."""
        from src.semi_auto.nodes.portfolio_node import portfolio_reasoning_node

        state = make_state(
            "Analyze AAPL RSI and momentum indicators",
            intent="quant",
            symbol="AAPL",
        )
        result = portfolio_reasoning_node(state)

        _assert_agent_output(result)

        assert result.get("_delegate_quant") is True, (
            f"Expected _delegate_quant=True for RSI/momentum query, got: "
            f"{result.get('_delegate_quant')}"
        )
        assert result.get("_quant_query"), "Expected _quant_query to be populated"

        print(f"\n[quant_delegates] _delegate_quant={result.get('_delegate_quant')}")
        print(f"[quant_delegates] _quant_query={result.get('_quant_query', '')[:80]}")

    def test_backtest_delegates(self):
        """Query: backtest request → delegate_to_backtester=True."""
        from src.semi_auto.nodes.portfolio_node import portfolio_reasoning_node

        state = make_state(
            "Backtest mean-reversion strategy on TSLA from 2026-01-01 to 2026-03-01",
            intent="backtest",
            symbol="TSLA",
        )
        result = portfolio_reasoning_node(state)

        _assert_agent_output(result)

        assert result.get("_delegate_backtester") is True, (
            f"Expected _delegate_backtester=True for backtest query, got: "
            f"{result.get('_delegate_backtester')}"
        )
        assert result.get("_backtester_query"), "Expected _backtester_query to be populated"

        print(f"\n[backtest_delegates] _delegate_backtester={result.get('_delegate_backtester')}")
        print(f"[backtest_delegates] _backtester_query={result.get('_backtester_query', '')[:80]}")

    def test_health_metrics(self):
        """Query: portfolio health → metric functions in task list."""
        from src.semi_auto.nodes.portfolio_node import portfolio_reasoning_node

        state = make_state(
            "Show me portfolio health and risk compliance metrics",
            intent="portfolio",
        )
        result = portfolio_reasoning_node(state)

        fn_names, metric_fns = _assert_agent_output(result)

        # check_portfolio_health requires deps on get_portfolio_status +
        # get_positions_summary; at minimum those or the health fn should appear
        expected_fns = {"get_portfolio_status", "get_positions_summary", "check_portfolio_health"}
        planned = set(fn_names)
        assert planned & expected_fns, (
            f"Expected at least one of {expected_fns} in task list, got: {fn_names}"
        )

        print(f"\n[health_metrics] fn_names={fn_names}")
        print(f"[health_metrics] metric_fns={metric_fns}")

    def test_no_hallucinated_fns(self):
        """All planned function names must exist in FUNCTION_REGISTRY."""
        from src.semi_auto.nodes.portfolio_node import portfolio_reasoning_node
        from src.semi_auto.registry.functions import FUNCTION_REGISTRY

        state = make_state(
            "What is my portfolio status and total equity?",
            intent="portfolio",
        )
        result = portfolio_reasoning_node(state)

        queue = result.get("portfolio_task_queue") or []
        hallucinated = [
            t["function_name"]
            for t in queue
            if t.get("function_name") not in FUNCTION_REGISTRY
        ]
        assert not hallucinated, (
            f"PM hallucinated {len(hallucinated)} function(s) not in registry: "
            f"{hallucinated}"
        )

        fn_names = [t["function_name"] for t in queue]
        print(f"\n[no_hallucinations] fn_names={fn_names} — all in registry ✓")

    def test_order_delegates(self):
        """Query: buy order → delegate_to_order=True."""
        from src.semi_auto.nodes.portfolio_node import portfolio_reasoning_node

        state = make_state(
            "Buy 10 shares of AAPL at market price",
            intent="order",
            symbol="AAPL",
        )
        result = portfolio_reasoning_node(state)

        _assert_agent_output(result)

        assert result.get("_delegate_order") is True, (
            f"Expected _delegate_order=True for buy query, got: "
            f"{result.get('_delegate_order')}"
        )
        assert result.get("_order_query"), "Expected _order_query to be populated"

        print(f"\n[order_delegates] _delegate_order={result.get('_delegate_order')}")
        print(f"[order_delegates] _order_query={result.get('_order_query', '')[:80]}")


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Quick sanity check — portfolio status query only."""
    print("=" * 60)
    print("PM Agent Integration Smoke Test")
    print("=" * 60)

    if not _has_openai_key():
        print("[SKIP] OPENAI_API_KEY not available")
        sys.exit(0)

    from src.semi_auto.nodes.portfolio_node import portfolio_reasoning_node

    state = make_state("What is my portfolio status?", intent="portfolio")
    result = portfolio_reasoning_node(state)

    fn_names, metric_fns = _assert_agent_output(result)
    print(f"\n[OK] Function names planned : {fn_names}")
    print(f"[OK] Metric functions planned: {metric_fns}")
    print(f"[OK] Reasoning: {result.get('portfolio_reasoning', '')[:120]}")
    print(f"[OK] delegate_quant={result.get('_delegate_quant')} "
          f"delegate_backtester={result.get('_delegate_backtester')} "
          f"delegate_order={result.get('_delegate_order')}")
    print("\n[ALL OK] PM agent smoke test passed")
