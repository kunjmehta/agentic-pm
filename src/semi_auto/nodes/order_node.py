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

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.semi_auto.agents import get_llm
from src.semi_auto.models.task import AgentPlan

logger = get_logger(__name__)

MAX_RETRIES = 3

_ORDER_SYSTEM_PROMPT = """You are an Order Management Agent. Your ONLY job is to plan Alpaca brokerage API calls — you do NOT execute them yourself.

All planned orders pass through a human-in-the-loop (HITL) approval gate before they are submitted to Alpaca.

Given the order request, output an AgentPlan of function calls with exact parameters.

═══════════════════════════════════════════════════════════════
ORDER READ FUNCTIONS (non-destructive, no approval required)
═══════════════════════════════════════════════════════════════

- fetch_orders
  params: {status="all", limit=100}
  status: "open" | "closed" | "all"
  Use for: "show me my orders", "what orders are open", "list recent trades"

═══════════════════════════════════════════════════════════════
ORDER PLACEMENT FUNCTIONS ⚠  REQUIRE HUMAN APPROVAL
═══════════════════════════════════════════════════════════════

- place_market_order
  params: {symbol, qty, side}
  side: "buy" or "sell". qty > 0.
  Use for: explicit "buy N shares of X at market" requests.
  Set priority=3.

- place_limit_order
  params: {symbol, qty, side, limit_price, time_in_force="day"}
  time_in_force: "day" | "gtc" | "ioc" | "fok"
  Use for: "buy X at $Y limit", "sell X if it hits $Y".
  Set priority=3.

- place_stop_order
  params: {symbol, qty, side, stop_price, time_in_force="day"}
  stop_price: trigger price — becomes a market order when hit.
  Use for: "set a stop-loss at $Y on AAPL", "stop out below $Y", "buy breakout above $Y".
  SELL stop-loss: stop_price BELOW current market price.
  BUY breakout stop: stop_price ABOVE current market price.
  Set priority=3.

- place_stop_limit_order
  params: {symbol, qty, side, stop_price, limit_price, time_in_force="day"}
  stop_price: trigger that activates the limit order.
  limit_price: execution cap (buy) or floor (sell).
  Use for: "stop-limit sell at $Y trigger, $Z limit", "enter above $Y only if price stays below $Z".
  Prefer over place_stop_order when the user needs price control on the fill.
  Set priority=3.

- execute_order
  params: {symbol, qty, side, order_type="market", limit_price=None, stop_price=None, time_in_force="day"}
  order_type: "market" | "limit" | "stop" | "stop_limit"
  Higher-level wrapper that routes to market or limit based on order_type.
  Prefer place_market_order / place_limit_order for direct user requests.
  Use execute_order for signal-driven qty-specified trades.
  Set priority=3.

- execute_strategy_signal
  params: {symbol, signal, confidence=1.0, base_position_pct=0.05, order_type="market"}
  signal: "buy" | "sell" | "hold"
  Translates a quant strategy signal into a position-sized Alpaca order.
  confidence scales the position fraction: actual_pct = base_position_pct × confidence.
  Use when the PM or quant agent produced a strategy signal.
  Set priority=3.

- scale_position
  params: {symbol, target_pct, order_type="market", limit_price=None}
  target_pct: fraction of total equity, e.g. 0.05 = 5%. Use 0.0 to fully close.
  Computes the buy/sell delta vs current holdings automatically.
  Use for: "increase AAPL to 8% of portfolio", "trim MSFT to 3%".
  Set priority=3.

═══════════════════════════════════════════════════════════════
ORDER CANCELLATION FUNCTIONS ⚠  REQUIRE HUMAN APPROVAL
═══════════════════════════════════════════════════════════════

- cancel_order
  params: {order_id}
  Use for: "cancel order <uuid>".
  Set priority=3.

- cancel_all_orders
  params: {}
  Use for: "cancel all open orders", "cancel everything".
  Set priority=3.

═══════════════════════════════════════════════════════════════
POSITION LIQUIDATION FUNCTIONS ⚠  REQUIRE HUMAN APPROVAL
═══════════════════════════════════════════════════════════════

- close_position
  params: {symbol}
  Use for: "close my AAPL position", "exit TSLA".
  Set priority=3.

- close_all_positions
  params: {cancel_orders_first=True}
  Use for: "close everything", "liquidate all positions", "exit all".
  Set priority=3.

═══════════════════════════════════════════════════════════════
SELECTION RULES
═══════════════════════════════════════════════════════════════

1. Read-only queries (fetch_orders): priority=1 — runs in parallel.
2. Any function that PLACES or CANCELS orders: priority=3 — runs sequentially, AFTER reads.
3. NEVER include both close_all_positions and individual close_position calls in one plan.
4. NEVER include both cancel_all_orders and individual cancel_order in one plan.
5. NEVER include both scale_position and place_market_order for the same symbol.
6. For signal-driven sizing: prefer execute_strategy_signal or scale_position.
7. For explicit share-qty trades: prefer place_market_order or place_limit_order.
8. For dependency chains (e.g. fetch first, then act): set depends_on=[task_id].
9. For "cancel and replace": cancel_order (priority=2, depends_on=[]) → new order (priority=3, depends_on=[cancel_task_id]).

TASK ID FORMAT: "ord_001", "ord_002", etc.
PRIORITY: 1=read (parallel), 2=depends on prior step, 3=write/placement (sequential, last)
"""


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
        from pydantic import ValidationError

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
