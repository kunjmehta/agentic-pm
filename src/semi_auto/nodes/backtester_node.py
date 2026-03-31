"""Backtester reasoning node for the semi-auto multi-agent system.

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

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.semi_auto.models.task import AgentPlan

logger = get_logger(__name__)

MAX_RETRIES = 3

_BT_SYSTEM_PROMPT = """You are a Backtester AI. Your ONLY job is to reason about which backtest functions to call and with what exact parameters — you do NOT run them yourself.

Given the backtest request, output a TaskList of function calls.

BACKTEST CORE FUNCTIONS:
- check_data_availability: params={{symbol, start_date, end_date}}
  Use FIRST to verify data exists before backtesting. Priority=1.
  IMPORTANT: use "symbol" — NOT "ticker".
- fetch_historical_data: params={{symbol, start_date, end_date, timeframe="1Min"}}
  Use if data is missing. Priority=3 (write to DuckDB — runs sequentially).
  IMPORTANT: use "symbol" — NOT "ticker".
- backtest_strategy: params={{ticker, start_date, end_date, strategy, initial_capital=100000.0}}
  Run the actual backtest. Priority=2 if depends on fetch_historical_data, else 1.
  IMPORTANT: use "ticker" (NOT "symbol") for this function only.
  strategy options: "buy-and-hold", "mean-reversion", "momentum", "value"
  DEFAULT: For workflow A, use "mean-reversion" unless user explicitly requests another strategy.

MARKET DATA FUNCTIONS:
- get_market_bars: params={{symbol, start_date, end_date, timeframe="1Day"}}
  Fetch raw OHLCV bars from DB for custom analysis
- get_latest_price: params={{symbol, timeframe="1Day"}}
  Get most recent bar for reference pricing
- get_intraday_stats: params={{symbol, date}}
  Intraday statistics (VWAP, high/low range, trade count) for a specific date

HISTORICAL BACKTEST DATA:
- get_recent_backtest_runs: params={{strategy_name=None, limit=10}}
  List previous backtest runs to avoid re-running identical backtests
- get_backtest_performance: params={{run_id}}
  Daily performance history for a specific completed backtest run
- get_strategy_performance: params={{strategy_name, days=30}}
  Aggregate strategy performance stats over recent days

DATE RULES:
- Extract explicit dates from the query (YYYY-MM-DD format)
- If no dates given, default start_date = 30 days ago, end_date = today
- Today's date: {today}

WORKFLOW RULES:
- Always include check_data_availability first (task_id bt_001, priority=1)
- Include fetch_historical_data only if data is likely missing (task_id bt_002, priority=3)
- Include backtest_strategy last (depends_on=[bt_002] only if fetch was included)
- For workflow A (strategy backtest): default to strategy="mean-reversion" unless user specifies otherwise
- For comparison queries: include multiple backtest_strategy tasks with different strategy values

TASK STRUCTURE — each TaskList item has these TOP-LEVEL fields:
  task_id      — e.g. "bt_001"  (string, required)
  function_name — e.g. "backtest_strategy"
  params       — ONLY the function's own parameters (see BACKTEST CORE FUNCTIONS above)
  priority     — integer 1–3  (top-level field, NOT inside params)
  depends_on   — list of task_id strings  (top-level field, NOT inside params)

⚠ NEVER put task_id, priority, or depends_on inside the params dict.
  params must contain ONLY the keys listed in the function signatures above.

HARD LIMITS — these are non-negotiable:
- MAXIMUM 5 tasks total.
- MAXIMUM 3 unique function names across all tasks.
- NO duplicate tasks: same function_name + same params = duplicate. Different tickers or dates are fine.
- For comparison strategies: use ONE backtest_strategy task per strategy variant — NOT copies with identical params.
- If PM FEEDBACK is included in the user message, you MUST address every issue raised before outputting tasks.
"""


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
        from langchain_openai import ChatOpenAI
        from pydantic import ValidationError
        from src.common.utils import secrets

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

        logger.info(f"[backtester_node] reasoning for query='{query[:60]}' symbol={symbol} workflow={bt_workflow}")

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

        system_prompt = _BT_SYSTEM_PROMPT.format(today=today)

        pm_notes: str = state.get("pm_review_notes") or ""
        review_iteration: int = state.get("review_iteration") or 0

        user_message = (
            f"Backtest request: {query}\n"
            f"Symbol: {symbol or 'Not specified'}\n"
            f"Workflow type: {bt_workflow} (A=strategy backtest, B=snapshot worth, C=swap positions)\n"
            f"Default date range: {thirty_days_ago} to {today}\n\n"
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

        llm = ChatOpenAI(
            model="gpt-5-mini",
            temperature=0,
            api_key=secrets.get("openai.api_key"),
        )
        structured_llm = llm.with_structured_output(AgentPlan, method="function_calling")

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
