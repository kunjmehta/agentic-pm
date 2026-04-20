"""Order Agent reasoning node for the semi-auto multi-agent system.

Receives a focused order-management query from the Portfolio Manager and uses
LLM with_structured_output(AgentPlan) to plan Alpaca order function calls.

No orders are placed here — this node only reasons about WHICH order functions
to call and with what parameters.  All execution is gated by HITL at executor_node.

Sets state fields: order_task_queue, order_reasoning.

Covers:
  - Fetching open/closed orders          (fetch_orders)
  - Placing market orders                (place_market_order)
  - Placing limit orders                 (place_limit_order)
  - Cancelling a specific order          (cancel_order)
  - Cancelling all open orders           (cancel_all_orders)
  - Closing a specific position          (close_position)
  - Closing all open positions           (close_all_positions)
  - Composite signal-driven execution    (execute_order, execute_strategy_signal, scale_position)

Middleware: Model retry up to MAX_RETRIES on ValidationError or LLM failure.
"""

import sys
from pathlib import Path
from typing import Optional
from pydantic import ValidationError

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.server.agents import get_llm
from src.server.constants import MAX_RETRIES
from src.server.models.task import AgentPlan
from src.common.utils import load_prompt

logger = get_logger(__name__)

_ORDER_SYSTEM_PROMPT = load_prompt("order_agent")


def order_reasoning_node(state: dict) -> dict:
    """Plan order management tasks via LLM structured output.

    Reads ``_order_query`` from state (set by portfolio_reasoning_node) and
    produces a serialised ``AgentPlan`` stored in ``order_task_queue``.

    Args:
        state: Current GraphState.

    Returns:
        Partial state update with ``order_task_queue`` and ``order_reasoning``.
    """
    try:
        query: str = state.get("_order_query") or state.get("query", "")
        symbol: Optional[str] = state.get("symbol")
        intent: Optional[str] = state.get("intent")
        prior_results: Optional[str] = None

        # Attach any quant/backtester reasoning for context
        reasoning_ctx = "\n".join(filter(None, [
            state.get("quant_reasoning"),
            state.get("backtester_reasoning"),
        ]))

        user_message = (
            f"Order request: {query}\n"
            f"Classified intent: {intent}\n"
            f"Extracted symbol: {symbol or 'None'}\n"
        )
        if reasoning_ctx:
            user_message += f"\nPrior agent reasoning (context):\n{reasoning_ctx}"

        logger.info(f"[order_node] planning for query='{query[:60]}' symbol={symbol}")

        structured_llm = get_llm("order").with_structured_output(AgentPlan, method="function_calling")

        messages = [
            {"role": "system", "content": _ORDER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        result: Optional[AgentPlan] = None
        last_error: Optional[str] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = structured_llm.invoke(messages)
                logger.info(
                    f"[order_node] planning complete on attempt {attempt}: "
                    f"{len(result.calls)} tasks"
                )
                break
            except (ValidationError, Exception) as exc:
                last_error = str(exc)
                logger.warning(f"[order_node] attempt {attempt}/{MAX_RETRIES} failed: {exc}")

        if result is None:
            logger.error(f"[order_node] all {MAX_RETRIES} attempts failed: {last_error}")
            result = AgentPlan(
                calls=[],
                reasoning_summary="Order planning failed — no tasks planned.",
            )

        # Auto-assign task_ids if missing
        for idx, fc in enumerate(result.calls, start=1):
            if not fc.task_id:
                fc.task_id = f"ord_{idx:03d}"

        task_queue = [fc.model_dump() for fc in result.calls]

        return {
            "order_task_queue": task_queue,
            "order_reasoning": result.reasoning_summary,
        }

    except Exception as exc:
        logger.error(f"[order_node] unexpected error: {exc}", exc_info=True)
        return {
            "order_task_queue": [],
            "order_reasoning": None,
            "error": f"Order reasoning failed: {exc}",
        }


if __name__ == "__main__":
    """Functional tests for order_reasoning_node."""
    print("=" * 60)
    print("order_node Functional Tests")
    print("=" * 60)

    base_state = {
        "intent": "order",
        "symbol": "AAPL",
        "quant_reasoning": None,
        "backtester_reasoning": None,
    }

    tests = [
        ("Buy 10 shares of AAPL at market",   "Buy 10 shares of AAPL at market price"),
        ("Limit order",                        "Place a limit buy of AAPL at $175 for 5 shares"),
        ("Cancel all",                         "Cancel all open orders"),
        ("Close AAPL",                         "Close my AAPL position"),
        ("Scale MSFT",                         "Scale up MSFT to 7% of my portfolio"),
        ("Fetch orders",                       "Show me all open orders"),
    ]
    for label, query in tests:
        print(f"\n[{label}]")
        state = {**base_state, "query": query, "_order_query": query}
        result = order_reasoning_node(state)
        tasks = result.get("order_task_queue", [])
        print(f"  tasks ({len(tasks)}): {[t['function_name'] for t in tasks]}")
        print(f"  reasoning: {result.get('order_reasoning', '')[:80]}")

    print("\n[ALL OK] order_node tests complete")
