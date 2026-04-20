"""Quant Analyst reasoning node for the trading multi-agent system.

Receives a focused technical analysis query (via LangGraph Send API payload)
and uses LLM with_structured_output(TaskList) to plan quant function calls.
No tool calls are made here — only reasoning about which indicator functions
to call and with what parameters.

Sets state fields: quant_task_queue, quant_reasoning.

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

_QUANT_SYSTEM_PROMPT = load_prompt("quant_analyst")


def quant_reasoning_node(state: dict) -> dict:
    """Quant Analyst pure reasoning node.

    May receive a partial Send payload (only _quant_query, symbol, etc.)
    or a full GraphState dict depending on the routing path.

    Args:
        state: Current GraphState dict or Send payload dict.

    Returns:
        Partial state update with quant_task_queue and quant_reasoning.
    """
    try:
        # Support both Send payload (partial) and full state
        query: str = (
            state.get("_quant_query")
            or state.get("query", "")
        )
        symbol: Optional[str] = state.get("symbol")
        intent: str = state.get("intent", "quant")

        if not query:
            logger.warning("[quant_node] no query in state — returning empty task list")
            return {
                "quant_task_queue": [],
                "quant_reasoning": "No quant query provided.",
            }

        logger.info(f"[quant_node] reasoning for query='{query[:60]}' symbol={symbol}")

        pm_notes: str = state.get("pm_review_notes") or ""
        review_iteration: int = state.get("review_iteration") or 0

        # ── DATA AVAILABILITY BLOCK ───────────────────────────────────────────
        da: dict = state.get("data_availability") or {}
        indicators_avail: bool = bool(da.get("indicators_available", False))
        bars_avail: bool = bool(da.get("bars_available", False))
        trades_avail: bool = bool(da.get("trades_available", False))
        ind_rows: int = int(da.get("indicator_rows", 0))
        bar_count: int = int(da.get("bar_count", 0))
        trade_count: int = int(da.get("trade_count", 0))
        latest_ind_ts: str = da.get("latest_indicator_ts") or "unknown"
        latest_bar_ts: str = da.get("latest_bar_ts") or "unknown"

        if indicators_avail:
            avail_guidance = (
                "✅ PRE-COMPUTED INDICATORS ARE AVAILABLE.\n"
                f"   {ind_rows} indicator rows exist for {symbol}/1Min (latest: {latest_ind_ts}).\n"
                "   → You MUST include get_precomputed_indicators as task qa_001 with\n"
                "     params={symbol, start_date=<today minus 2 hours>, end_date=<now>, timeframe=\"1Min\"}.\n"
                "   → Only add calc_* functions if the query explicitly needs something\n"
                "     NOT in the pre-computed set (e.g. candlestick patterns, mean_reversion_analyze).\n"
                "   → mean_reversion_analyze ALWAYS runs fresh (it generates the trade recommendation)."
            )
        elif bars_avail:
            avail_guidance = (
                "⚠️  BARS ARE AVAILABLE BUT INDICATORS ARE NOT PRE-COMPUTED.\n"
                f"   {bar_count} market bars found (latest: {latest_bar_ts}).\n"
                "   → Do NOT call get_precomputed_indicators — it will return empty.\n"
                "   → Use calc_momentum / calc_volatility_bands / calc_volume_flow directly.\n"
                "   → mean_reversion_analyze is available (it fetches bars internally)."
            )
        else:
            avail_guidance = (
                "❌ NO LOCAL DATA FOUND for this symbol.\n"
                "   → Do NOT call get_precomputed_indicators or get_market_bars — both will return empty.\n"
                "   → You may still call mean_reversion_analyze (live mode fetches from broker API).\n"
                "   → For other indicators, note in your reasoning_summary that data is unavailable\n"
                "     and request data ingestion before re-analysis."
            )

        trades_note = (
            f"   Trade data: {trade_count} trades in last 24 h — available for get_latest_price."
            if trades_avail
            else "   Trade data: NOT available — skip get_latest_price unless essential."
        )

        data_avail_section = (
            f"\nDATA AVAILABILITY REPORT (verified {da.get('checked_at', 'now')}):\n"
            f"{avail_guidance}\n{trades_note}\n"
        )
        # ── END DATA AVAILABILITY BLOCK ───────────────────────────────────────

        user_message = (
            f"Analysis request: {query}\n"
            f"Symbol: {symbol or 'Not specified'}\n"
            f"Intent: {intent}\n"
            f"{data_avail_section}\n"
            f"Plan the minimum set of indicator functions needed to answer this request."
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
            quant_edits = edits_payload.get("quant_edits") or []
            reason = edits_payload.get("reason") or pm_notes
            if quant_edits or reason:
                edits_str = "\n".join(
                    f"  [{e['index']}] action={e['action']}"
                    + (f"  new_params={e['new_params']}" if e.get("new_params") else "")
                    + (f"  new_function={e['new_function_name']}" if e.get("new_function_name") else "")
                    for e in quant_edits
                ) or "  (none)"
                user_message += (
                    f"\n\nPM FEEDBACK — REVISION {review_iteration}/2:\n"
                    f"Reason: {reason}\n"
                    f"Required edits to your previous plan:\n{edits_str}\n"
                    f"Produce a corrected plan that resolves these issues. "
                    f"Hard limits: max 5 calls, max 3 unique function names, no duplicates."
                )

        structured_llm = get_llm("quant").with_structured_output(AgentPlan, method="function_calling")

        messages = [
            {"role": "system", "content": _QUANT_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        result: Optional[AgentPlan] = None
        last_error: Optional[str] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = structured_llm.invoke(messages)
                logger.info(
                    f"[quant_node] plan complete on attempt {attempt}: "
                    f"{len(result.calls)} calls"
                )
                break
            except (ValidationError, Exception) as exc:
                last_error = str(exc)
                logger.warning(f"[quant_node] attempt {attempt}/{MAX_RETRIES} failed: {exc}")

        if result is None:
            logger.error(f"[quant_node] all {MAX_RETRIES} attempts failed: {last_error}")
            result = AgentPlan(calls=[], reasoning_summary="Quant reasoning failed — no calls planned.")

        task_queue = [
            {
                "task_id": c.task_id or f"qa_{i+1:03d}",
                "function_name": c.function_name,
                "params": c.params,
                "priority": c.priority,
                "depends_on": c.depends_on,
            }
            for i, c in enumerate(result.calls)
        ]

        unique_fns = len({c["function_name"] for c in task_queue})
        logger.info(
            f"[quant_node] plan ({len(task_queue)} calls, {unique_fns} unique functions):\n"
            + "\n".join(
                f"  [{i}] {c['function_name']}  params={c['params']}"
                for i, c in enumerate(task_queue)
            )
        )

        return {
            "quant_task_queue": task_queue,
            "quant_reasoning": result.reasoning_summary,
        }

    except Exception as exc:
        logger.error(f"[quant_node] unexpected error: {exc}", exc_info=True)
        return {
            "error": f"Quant reasoning failed: {exc}",
            "quant_task_queue": [],
            "quant_reasoning": None,
        }


if __name__ == "__main__":
    """Functional test: quant reasoning for various queries."""
    print("=" * 60)
    print("quant_node Functional Tests")
    print("=" * 60)

    # Test 1: RSI and MACD query
    print("\n[1/3] Momentum query (RSI + MACD)")
    result = quant_reasoning_node({
        "_quant_query": "Analyze AAPL momentum indicators including RSI and MACD",
        "symbol": "AAPL",
        "intent": "quant",
    })
    print(f"[OK] quant_reasoning: {result.get('quant_reasoning', '')[:100]}")
    print(f"[OK] task count: {len(result.get('quant_task_queue', []))}")
    for task in result.get("quant_task_queue", []):
        print(f"     - {task['task_id']}: {task['function_name']} params={task['params']}")

    # Test 2: mean reversion query
    print("\n[2/3] Mean reversion query")
    result2 = quant_reasoning_node({
        "_quant_query": "Is AAPL showing a mean reversion opportunity?",
        "symbol": "AAPL",
        "intent": "quant",
    })
    print(f"[OK] task count: {len(result2.get('quant_task_queue', []))}")
    for task in result2.get("quant_task_queue", []):
        print(f"     - {task['task_id']}: {task['function_name']}")

    # Test 3: no query
    print("\n[3/3] No query (graceful degradation)")
    result3 = quant_reasoning_node({"symbol": "AAPL"})
    assert result3["quant_task_queue"] == []
    print("[OK] empty task list returned")

    print("\n[ALL OK] quant_node tests complete")
