"""Quant Analyst reasoning node for the semi-auto multi-agent system.

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

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.semi_auto.models.task import AgentPlan

logger = get_logger(__name__)

MAX_RETRIES = 3

_QUANT_SYSTEM_PROMPT = """You are a Quant Analyst AI. Your ONLY job is to reason about which technical analysis functions to call — you do NOT execute them yourself.

Given the analysis request, output a TaskList of quant function calls with the exact parameters.

TECHNICAL INDICATOR FUNCTIONS:
- calc_momentum: params={symbol, timeframe="1Day", lookback_days=90}
  Computes: MACD (value, signal, histogram) and RSI
- calc_volatility_bands: params={symbol, timeframe="1Day", lookback_days=90}
  Computes: Bollinger Bands (upper, middle, lower, bandwidth)
- calc_volume_flow: params={symbol, timeframe="1Day", lookback_days=90}
  Computes: OBV and volume trend (increasing/decreasing/stable)
- analyze_candle_structure: params={symbol, timeframe="1Day", lookback_days=30}
  Detects: Engulfing, Doji, Hammer, Hanging Man patterns
- mean_reversion_analyze: params={symbol, lookback=60, threshold=2.0}
  Computes: Z-score, Bollinger, moving averages, generates buy/sell/hold signal

MARKET DATA FUNCTIONS:
- get_market_bars: params={symbol, start_date, end_date, timeframe="1Day"}
  Fetch raw OHLCV bars from DB for a date range
- get_latest_price: params={symbol, timeframe="1Day"}
  Get most recent bar (open, high, low, close, volume)
- get_precomputed_indicators: params={symbol, start_date, end_date, timeframe="1Day"}
  Retrieve pre-computed technical indicators stored in DB

FUNDAMENTAL DATA FUNCTIONS:
- get_company_fundamentals: params={symbol}
  Company overview: PE ratio, market cap, sector, EPS, 52-week range
- get_earnings_history: params={symbol, quarterly=True, limit=4}
  Historical earnings: reported vs estimated EPS, surprise %

ANALYST & SIGNAL FUNCTIONS:
- get_latest_eod: params={symbol}
  Most recent end-of-day analyst summary for the symbol
- get_latest_signal: params={symbol, strategy_name}
  Most recent strategy signal (buy/sell/hold) with confidence score

SELECTION RULES:
- For momentum/RSI queries: include calc_momentum
- For Bollinger/volatility queries: include calc_volatility_bands
- For volume/OBV queries: include calc_volume_flow
- For candlestick pattern queries: include analyze_candle_structure
- For mean reversion / z-score queries: include mean_reversion_analyze
- For "full analysis" or "all indicators": include all 5 indicator functions
- For RSI only: just calc_momentum
- Add get_company_fundamentals for valuation context in comprehensive analysis
- Add get_latest_price when current price is needed
- Minimum: pick only what the query explicitly asks for

TASK STRUCTURE — each TaskList item has these TOP-LEVEL fields:
  task_id      — e.g. "qa_001"  (string, required)
  function_name — e.g. "calc_momentum"
  params       — ONLY the function's own parameters (see TECHNICAL INDICATOR FUNCTIONS above)
  priority     — always 1  (top-level field, NOT inside params)
  depends_on   — always []  (top-level field, NOT inside params)

⚠ NEVER put task_id, priority, or depends_on inside the params dict.
  params must contain ONLY the keys listed in the function signatures above.

HARD LIMITS — these are non-negotiable:
- MAXIMUM 5 tasks total.
- MAXIMUM 3 unique function names across all tasks.
- NO duplicate tasks: same function_name + same params = duplicate. Different symbols or timeframes are fine.
- If PM FEEDBACK is included in the user message, you MUST address every issue raised before outputting tasks.
"""


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
        from langchain_openai import ChatOpenAI
        from pydantic import ValidationError
        from src.common.utils import secrets

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

        user_message = (
            f"Analysis request: {query}\n"
            f"Symbol: {symbol or 'Not specified'}\n"
            f"Intent: {intent}\n\n"
            f"Plan the minimum set of indicator functions needed to answer this request."
        )

        prior_turns = state.get("prior_turns") or []
        if prior_turns:
            turns_str = "\n".join(
                f"  [{t.get('turn_number', i+1)}] {str(t.get('user_query', ''))[:60]}"
                f" → {str(t.get('agent_response', ''))[:80]}"
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

        llm = ChatOpenAI(
            model="gpt-5-mini",
            temperature=0,
            api_key=secrets.get("openai.api_key"),
        )
        structured_llm = llm.with_structured_output(AgentPlan, method="function_calling")

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
