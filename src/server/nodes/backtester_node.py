"""Backtester reasoning node for the trading multi-agent system.

Receives a focused backtesting query (via LangGraph Send API payload)
and uses LLM with_structured_output(TaskList) to plan backtest function calls.
No tool calls are made here — only reasoning about what to backtest.

Sets state fields: backtester_task_queue, backtester_reasoning.

Middleware: Model retry up to MAX_RETRIES on ValidationError or LLM failure.
"""

import sys
from datetime import datetime, timedelta, timezone
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

_BT_SYSTEM_PROMPT = load_prompt("backtester")


def backtester_reasoning_node(state: dict) -> dict:
    """Backtester pure reasoning node.

    May receive a partial Send payload (only _backtester_query, symbol, etc.)
    or a full GraphState dict depending on routing.

    Args:
        state: Current GraphState dict or Send payload dict.

    Returns:
        Partial state update with backtester_task_queue and backtester_reasoning.
    """
    try:
        # Support both Send payload (partial) and full state
        query: str = (
            state.get("_backtester_query")
            or state.get("query", "")
        )
        symbol: Optional[str] = state.get("symbol")
        bt_workflow: str = state.get("bt_workflow", "A")

        if not query:
            logger.warning("[backtester_node] no query in state — returning empty task list")
            return {
                "backtester_task_queue": [],
                "backtester_reasoning": "No backtester query provided.",
            }

        logger.info(f"[backtester_node] reasoning for query='{query[:100]}' symbol={symbol} workflow={bt_workflow}")

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

        system_prompt = _BT_SYSTEM_PROMPT.format(today=today)

        pm_notes: str = state.get("pm_review_notes") or ""
        review_iteration: int = state.get("review_iteration") or 0

        # ── Data availability pre-check results ──────────────────────────────
        data_avail = state.get("data_availability") or {}
        data_avail_section = ""
        if data_avail:
            symbol_da = data_avail.get("symbol", "N/A")
            bars_avail = data_avail.get("bars_available", False)
            bar_count = data_avail.get("bar_count", 0)
            latest_bar_ts = data_avail.get("latest_bar_ts", "N/A")
            trades_avail = data_avail.get("trades_available", False)
            trade_count = data_avail.get("trade_count", 0)

            if bars_avail:
                data_avail_section = (
                    f"\nDATA AVAILABILITY REPORT (symbol={symbol_da}):\n"
                    f"  bars_available=True  ({bar_count} bars in DB, latest={latest_bar_ts})\n"
                    f"  trades_available={trades_avail}  ({trade_count} trades)\n"
                    f"\nDATA GUIDANCE:\n"
                    f"  - Bars ARE already in the DB. DO NOT include fetch_historical_data.\n"
                    f"  - check_data_availability (bt_001) is still required to confirm date-range coverage.\n"
                    f"  - Recommended sequence: check_data_availability → backtest_strategy.\n"
                )
            else:
                data_avail_section = (
                    f"\nDATA AVAILABILITY REPORT (symbol={symbol_da}):\n"
                    f"  bars_available=False  (no bars found in DB)\n"
                    f"  trades_available={trades_avail}  ({trade_count} trades)\n"
                    f"\nDATA GUIDANCE:\n"
                    f"  - No bars in DB. MUST include fetch_historical_data (bt_002, priority=3).\n"
                    f"  - Required sequence: check_data_availability → fetch_historical_data → backtest_strategy.\n"
                )

        user_message = (
            f"Backtest request: {query}\n"
            f"Symbol: {symbol or 'Not specified'}\n"
            f"Workflow type: {bt_workflow} (A=strategy backtest, B=snapshot worth, C=swap positions)\n"
            f"Default date range: {thirty_days_ago} to {today}\n"
            f"{data_avail_section}\n"
            f"Plan the exact function calls needed. Include check_data_availability first."
        )

        prior_turns = state.get("prior_turns") or []
        if prior_turns:
            turns_str = "\n".join(
                f"  [{t.get('turn_number', i+1)}] {t.get('user_query', '')[:60]}"
                f" → {t.get('agent_response', '')[:80]}"
                for i, t in enumerate(prior_turns[-3:])
            )
            user_message += f"\n\nPRIOR CONTEXT (last {min(len(prior_turns), 3)} turns):\n{turns_str}"

        if review_iteration > 0:
            edits_payload = state.get("pm_review_edits") or {}
            bt_edits = edits_payload.get("backtester_edits") or []
            reason = edits_payload.get("reason") or pm_notes
            if bt_edits or reason:
                edits_str = "\n".join(
                    f"  [{e['index']}] action={e['action']}"
                    + (f"  new_params={e['new_params']}" if e.get("new_params") else "")
                    + (f"  new_function={e['new_function_name']}" if e.get("new_function_name") else "")
                    for e in bt_edits
                ) or "  (none)"
                user_message += (
                    f"\n\nPM FEEDBACK — REVISION {review_iteration}/2:\n"
                    f"Reason: {reason}\n"
                    f"Required edits to your previous plan:\n{edits_str}\n"
                    f"Produce a corrected plan that resolves these issues. "
                    f"Hard limits: max 5 calls, max 3 unique function names, no duplicates."
                )

        structured_llm = get_llm("backtester").with_structured_output(AgentPlan, method="function_calling")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        result: Optional[AgentPlan] = None
        last_error: Optional[str] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = structured_llm.invoke(messages)
                logger.info(
                    f"[backtester_node] plan complete on attempt {attempt}: "
                    f"{len(result.calls)} calls"
                )
                break
            except (ValidationError, Exception) as exc:
                last_error = str(exc)
                logger.warning(f"[backtester_node] attempt {attempt}/{MAX_RETRIES} failed: {exc}")

        if result is None:
            logger.error(f"[backtester_node] all {MAX_RETRIES} attempts failed: {last_error}")
            result = AgentPlan(calls=[], reasoning_summary="Backtester reasoning failed — no calls planned.")

        task_queue = [
            {
                "task_id": c.task_id or f"bt_{i+1:03d}",
                "function_name": c.function_name,
                "params": c.params,
                "priority": c.priority,
                "depends_on": c.depends_on,
            }
            for i, c in enumerate(result.calls)
        ]

        unique_fns = len({c["function_name"] for c in task_queue})
        logger.info(
            f"[backtester_node] plan ({len(task_queue)} calls, {unique_fns} unique functions):\n"
            + "\n".join(
                f"  [{i}] {c['function_name']}  params={c['params']}"
                for i, c in enumerate(task_queue)
            )
        )

        return {
            "backtester_task_queue": task_queue,
            "backtester_reasoning": result.reasoning_summary,
        }

    except Exception as exc:
        logger.error(f"[backtester_node] unexpected error: {exc}", exc_info=True)
        return {
            "error": f"Backtester reasoning failed: {exc}",
            "backtester_task_queue": [],
            "backtester_reasoning": None,
        }


if __name__ == "__main__":
    """Functional test: backtester reasoning for various queries."""
    print("=" * 60)
    print("backtester_node Functional Tests")
    print("=" * 60)

    # Test 1: standard backtest query
    print("\n[1/3] Strategy backtest query")
    result = backtester_reasoning_node({
        "_backtester_query": "Backtest mean-reversion strategy on AAPL from 2026-01-01 to 2026-01-31",
        "symbol": "AAPL",
        "bt_workflow": "A",
    })
    print(f"[OK] backtester_reasoning: {result.get('backtester_reasoning', '')[:100]}")
    print(f"[OK] task count: {len(result.get('backtester_task_queue', []))}")
    for task in result.get("backtester_task_queue", []):
        print(f"     - {task['task_id']}: {task['function_name']} params={task['params']}")

    # Test 2: no dates (use defaults)
    print("\n[2/3] No explicit dates (use defaults)")
    result2 = backtester_reasoning_node({
        "_backtester_query": "Run momentum backtest on TSLA",
        "symbol": "TSLA",
        "bt_workflow": "A",
    })
    print(f"[OK] task count: {len(result2.get('backtester_task_queue', []))}")

    # Test 3: no query (graceful)
    print("\n[3/3] No query (graceful degradation)")
    result3 = backtester_reasoning_node({"symbol": "AAPL"})
    assert result3["backtester_task_queue"] == []
    print("[OK] empty task list returned")

    print("\n[ALL OK] backtester_node tests complete")
