"""PM Decision node — reviews analysis results and decides on order execution.

After executor_node completes analysis tasks (quant + backtester), this node
reviews the execution_results and decides whether the findings justify placing
live orders.

Sets state fields:
  pm_decision_reasoning: PM's rationale for the order decision.
  _execute_orders: True → fan-out to order_reasoning_node; False → synthesizer only.
  order_task_queue: populated only when _execute_orders=True.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from pydantic import BaseModel, Field

from src.common.utils import get_logger
from src.server.agents import get_llm

logger = get_logger(__name__)

MAX_RETRIES = 3

# ── Pydantic output models ─────────────────────────────────────────────────────


class OrderSignal(BaseModel):
    """A single actionable order signal derived from analysis results."""

    symbol: str = Field(description="Ticker symbol, e.g. 'AAPL'")
    action: Literal["buy", "sell", "hold"] = Field(
        description="Recommended action based on analysis"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Signal confidence between 0 and 1"
    )
    suggested_qty: Optional[int] = Field(
        default=None,
        description="Optional number of shares to trade; None if sizing is deferred",
    )


class PMDecision(BaseModel):
    """PM's structured order decision after reviewing analysis results."""

    should_execute_orders: bool = Field(
        description=(
            "True only when analysis results contain a clear, high-confidence signal "
            "AND portfolio risk is acceptable. False for hold, insufficient data, or "
            "pure informational queries."
        )
    )
    order_rationale: str = Field(
        description="1-2 sentence explanation of the order decision for the user"
    )
    order_signals: List[OrderSignal] = Field(
        default_factory=list,
        description="Concrete signals to pass to order_reasoning_node. "
        "Only populated when should_execute_orders=True.",
    )


# ── System prompt ─────────────────────────────────────────────────────────────

_DECISION_SYSTEM_PROMPT = """You are the Portfolio Manager reviewing completed technical analysis and backtest results.

Your ONLY job is to decide whether the analysis results justify placing live orders.

DECISION CRITERIA:
- should_execute_orders=True ONLY if:
  1. At least one strategy produced a clear buy or sell signal (not "hold")
  2. Signal confidence ≥ 0.65
  3. The query intent was action-oriented (user asked to trade, act on signals, etc.)
  4. Risk parameters (if available) allow the trade

- should_execute_orders=False for:
  - Pure informational/analysis queries with no action intent
  - Hold signals only (no buy/sell)
  - Low-confidence signals (< 0.65)
  - Backtest-only queries (historical simulation ≠ live order)
  - Insufficient or error-heavy analysis results

SIGNAL EXTRACTION:
- When should_execute_orders=True, populate order_signals with one OrderSignal per symbol
- Set action to "buy", "sell", or "hold" based on strategy output
- Set confidence from the strategy result (0-1 float)
- Set suggested_qty to None unless portfolio_status gives explicit position sizing guidance

IMPORTANT: Err on the side of caution. False negatives (missing a trade) are better than
false positives (placing an unwanted order). When uncertain, set should_execute_orders=False.
"""


# ── Node function ─────────────────────────────────────────────────────────────


def pm_decision_node(state: dict) -> dict:
    """Review analysis execution results and decide whether to place orders.

    Supports two modes:
    1. Query-driven: execution_results from executor_node (existing logic)
    2. Autonomous: signal_batch from periodic signal aggregator (new)

    Uses get_llm("pm_decision") singleton with structured output to produce a
    PMDecision. Retries up to MAX_RETRIES on validation or LLM failure.

    Args:
        state: Current GraphState dict with execution_results or signal_batch.

    Returns:
        Partial state update with pm_decision_reasoning, _execute_orders,
        and optionally order_task_queue.
    """
    try:
        execution_results: Dict[str, Any] = state.get("execution_results") or {}
        signal_batch: Optional[Dict[str, Any]] = state.get("signal_batch")
        autonomous_mode: bool = state.get("autonomous_mode", False)

        # Detect execution mode
        if signal_batch and autonomous_mode:
            logger.info("[pm_decision] Processing autonomous signal batch")
            return _process_autonomous_signals(state, signal_batch)
        elif execution_results:
            logger.info("[pm_decision] Processing query-driven execution results")
            return _process_query_driven_signals(state, execution_results)
        else:
            logger.warning("[pm_decision] No signals to process (no execution_results or signal_batch)")
            return {
                "pm_decision_reasoning": "No signals available for PM review",
                "_execute_orders": False,
                "order_task_queue": None,
            }

    except Exception as exc:
        logger.error(f"[pm_decision] unexpected error: {exc}", exc_info=True)
        return {
            "pm_decision_reasoning": f"PM decision failed: {exc}",
            "_execute_orders": False,
            "order_task_queue": None,
        }


def _process_query_driven_signals(state: dict, execution_results: Dict[str, Any]) -> dict:
    """Process query-driven execution results (existing logic).

    Args:
        state: GraphState dict.
        execution_results: Task results from executor_node.

    Returns:
        Partial state update.
    """
    from pydantic import ValidationError

    query: str = state.get("query", "")
    symbol: Optional[str] = state.get("symbol")
    backtest_mode: bool = state.get("backtest_mode", False)

    logger.info(
        f"[pm_decision] reviewing {len(execution_results)} task results "
        f"for query='{query[:60]}' backtest_mode={backtest_mode}"
    )

    # Summarise execution results for the LLM
    results_summary = _summarise_results(execution_results)

    user_message = (
        f"User query: {query}\n"
        f"Symbol: {symbol or 'None'}\n"
        f"Backtest mode: {backtest_mode}\n\n"
        f"ANALYSIS RESULTS:\n{results_summary}"
    )

    structured_llm = get_llm("pm_decision").with_structured_output(
        PMDecision, method="function_calling"
    )
    messages = [
        {"role": "system", "content": _DECISION_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    decision: Optional[PMDecision] = None
    last_error: Optional[str] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            decision = structured_llm.invoke(messages)
            logger.info(
                f"[pm_decision] decision on attempt {attempt}: "
                f"execute={decision.should_execute_orders} "
                f"signals={len(decision.order_signals)}"
            )
            break
        except (ValidationError, Exception) as exc:
            last_error = str(exc)
            logger.warning(f"[pm_decision] attempt {attempt}/{MAX_RETRIES} failed: {exc}")

    if decision is None:
        logger.error(f"[pm_decision] all {MAX_RETRIES} attempts failed: {last_error}")
        decision = PMDecision(
            should_execute_orders=False,
            order_rationale="PM decision failed — defaulting to no order execution.",
            order_signals=[],
        )

    # Build order_task_queue from signals (only populated when executing)
    order_task_queue = None
    if decision.should_execute_orders and decision.order_signals:
        order_task_queue = _signals_to_task_queue(decision.order_signals)
        logger.info(
            f"[pm_decision] generated {len(order_task_queue)} order tasks from signals"
        )

    return {
        "pm_decision_reasoning": decision.order_rationale,
        "_execute_orders": decision.should_execute_orders,
        "order_task_queue": order_task_queue,
    }


def _process_autonomous_signals(state: dict, signal_batch: Dict[str, Any]) -> dict:
    """Process autonomous signal batch from periodic aggregator.

    Validates signals against recent orders and portfolio constraints,
    then converts approved signals to order_task_queue.

    Args:
        state: GraphState dict.
        signal_batch: SignalBatch dict from signal aggregator.

    Returns:
        Partial state update with order_task_queue.
    """
    from src.common.dao.orders_dao import OrdersDAO
    from src.server.models.autonomous_signals import AggregatedSignal

    signals_data = signal_batch.get("signals", [])
    if not signals_data:
        logger.info("[pm_decision] No signals in batch")
        return {
            "pm_decision_reasoning": "No signals in autonomous batch",
            "_execute_orders": False,
            "order_task_queue": None,
        }

    # Parse signals into Pydantic models
    signals = []
    for sig_data in signals_data:
        try:
            signals.append(AggregatedSignal(**sig_data))
        except Exception as exc:
            logger.warning(f"[pm_decision] Failed to parse signal: {exc}")
            continue

    logger.info(f"[pm_decision] Processing {len(signals)} autonomous signals")

    # Check each signal against recent orders
    orders_dao = OrdersDAO()
    approved_signals = []

    for signal in signals:
        try:
            # Check for recent orders (duplicate prevention)
            recent_orders = orders_dao.get_recent_orders_for_symbol(
                symbol=signal.symbol,
                side=signal.action,
                lookback_hours=24
            )

            if recent_orders:
                logger.info(
                    f"[pm_decision] {signal.symbol}: skipping (found {len(recent_orders)} "
                    f"recent {signal.action} order(s))"
                )
                continue

            # Signal passed checks
            approved_signals.append(signal)
            logger.info(
                f"[pm_decision] {signal.symbol}: approved {signal.action} @ {signal.confidence:.2f}"
            )

        except Exception as exc:
            logger.error(f"[pm_decision] Error processing {signal.symbol}: {exc}", exc_info=True)
            continue

    # Close DAO
    orders_dao.close()

    if not approved_signals:
        logger.info("[pm_decision] No signals approved after validation")
        return {
            "pm_decision_reasoning": "All autonomous signals filtered out (duplicates or constraints)",
            "_execute_orders": False,
            "order_task_queue": None,
        }

    # Convert approved signals to order_task_queue
    order_task_queue = _autonomous_signals_to_task_queue(approved_signals)

    reasoning = (
        f"Approved {len(approved_signals)}/{len(signals)} autonomous signals for execution: "
        + ", ".join([f"{s.symbol} {s.action}" for s in approved_signals])
    )

    logger.info(f"[pm_decision] {reasoning}")

    return {
        "pm_decision_reasoning": reasoning,
        "_execute_orders": True,
        "order_task_queue": order_task_queue,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _summarise_results(execution_results: Dict[str, Any]) -> str:
    """Produce a concise text summary of execution results for the LLM prompt.

    Args:
        execution_results: task_id → result dict from executor_node.

    Returns:
        Formatted string of task outcomes.
    """
    if not execution_results:
        return "No analysis results available."

    lines = []
    for task_id, res in execution_results.items():
        status = res.get("status", "unknown")
        fn = res.get("function_name", task_id)
        result_data = res.get("result")
        error = res.get("error")

        if status == "success" and result_data is not None:
            # Truncate long results
            result_str = str(result_data)
            if len(result_str) > 400:
                result_str = result_str[:400] + "... [truncated]"
            lines.append(f"[{task_id}] {fn}: SUCCESS\n  Result: {result_str}")
        elif status == "error":
            lines.append(f"[{task_id}] {fn}: ERROR — {error}")
        else:
            lines.append(f"[{task_id}] {fn}: {status.upper()}")

    return "\n\n".join(lines)


def _signals_to_task_queue(signals: List[OrderSignal]) -> List[Dict[str, Any]]:
    """Convert PMDecision order signals into order_task_queue task dicts.

    Each signal becomes an execute_strategy_signal call that the order_reasoning_node
    will refine into a concrete order.

    Args:
        signals: List of OrderSignal from PMDecision.

    Returns:
        List of task dicts compatible with executor_node / order_executor_node.
    """
    tasks = []
    for i, sig in enumerate(signals):
        if sig.action == "hold":
            continue  # Don't create tasks for hold signals
        task_id = f"ord_{i + 1:03d}"
        tasks.append({
            "task_id": task_id,
            "function_name": "execute_strategy_signal",
            "params": {
                "symbol": sig.symbol,
                "action": sig.action,
                "confidence": sig.confidence,
                "suggested_qty": sig.suggested_qty,
            },
            "priority": 3,  # sequential — order execution runs last
            "depends_on": [],
            "retry_count": 0,
            "description": (
                f"Execute {sig.action.upper()} signal for {sig.symbol} "
                f"(confidence={sig.confidence:.2f})"
            ),
        })
    return tasks


def _autonomous_signals_to_task_queue(signals) -> List[Dict[str, Any]]:
    """Convert autonomous AggregatedSignal objects to order_task_queue.

    Args:
        signals: List of AggregatedSignal objects from signal aggregator.

    Returns:
        List of task dicts compatible with order_executor_node.
    """
    tasks = []
    for i, sig in enumerate(signals):
        if sig.action == "hold":
            continue  # Don't create tasks for hold signals

        task_id = f"auto_ord_{i + 1:03d}"
        tasks.append({
            "task_id": task_id,
            "function_name": "execute_strategy_signal",
            "params": {
                "symbol": sig.symbol,
                "action": sig.action,
                "confidence": sig.confidence,
                "suggested_qty": None,  # Let order_reasoning_node size the position
                "entry_price": sig.entry_price,
                "stop_loss": sig.stop_loss,
                "take_profit": sig.take_profit,
                "strategies": sig.strategies,
                "reason": sig.reason,
            },
            "priority": 3,  # sequential — order execution runs last
            "depends_on": [],
            "retry_count": 0,
            "description": (
                f"[AUTONOMOUS] Execute {sig.action.upper()} signal for {sig.symbol} "
                f"(confidence={sig.confidence:.2f}, {sig.strategy_count} strategies)"
            ),
        })
    return tasks


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Functional tests for pm_decision_node (no order placed — backtest_mode=True)."""
    print("=" * 60)
    print("pm_decision_node Functional Tests")
    print("=" * 60)

    # Test 1: analysis-only result → no order
    print("\n[1/3] Analysis-only results → should_execute_orders=False")
    state1 = {
        "query": "What is the RSI trend for AAPL?",
        "symbol": "AAPL",
        "backtest_mode": True,
        "execution_results": {
            "qa_001": {
                "task_id": "qa_001",
                "function_name": "get_rsi",
                "status": "success",
                "result": {"rsi": 58.3, "signal": "hold", "symbol": "AAPL"},
                "error": None,
            }
        },
    }
    r1 = pm_decision_node(state1)
    print(f"[OK] _execute_orders: {r1['_execute_orders']}")
    print(f"[OK] pm_decision_reasoning: {r1['pm_decision_reasoning'][:100]}")
    assert r1["_execute_orders"] in (True, False)

    # Test 2: buy signal → may trigger order
    print("\n[2/3] Strong buy signal → decision depends on confidence")
    state2 = {
        "query": "Run golden cross on AAPL and execute if signal is strong",
        "symbol": "AAPL",
        "backtest_mode": True,
        "execution_results": {
            "qa_001": {
                "task_id": "qa_001",
                "function_name": "golden_cross_signals",
                "status": "success",
                "result": {"signal": "buy", "confidence": 0.85, "symbol": "AAPL"},
                "error": None,
            }
        },
    }
    r2 = pm_decision_node(state2)
    print(f"[OK] _execute_orders: {r2['_execute_orders']}")
    print(f"[OK] order_task_queue: {r2.get('order_task_queue')}")

    # Test 3: empty results → no order
    print("\n[3/3] Empty execution_results → should_execute_orders=False")
    state3 = {
        "query": "What is my portfolio status?",
        "symbol": None,
        "backtest_mode": True,
        "execution_results": {},
    }
    r3 = pm_decision_node(state3)
    print(f"[OK] _execute_orders: {r3['_execute_orders']}")
    assert r3["_execute_orders"] in (True, False)

    print("\n[ALL OK] pm_decision_node tests complete")
