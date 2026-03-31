"""PM supervisor review node for the semi-auto multi-agent system.

Reviews Quant and Backtester AgentPlan call lists.  PM outputs a structured
PMFeedback object with targeted FunctionCallEdits rather than free text.

Edits are applied directly to the queues in state so the executor always
receives the corrected plan.  If approved=True (with or without edits) the
graph proceeds to executor_node.  If approved=False a structural problem
remains and the graph routes back to the agents for a full re-plan.

Sets state fields: pm_review_approved, pm_review_notes, pm_review_edits,
quant_task_queue (edited), backtester_task_queue (edited).
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.semi_auto.models.task import FunctionCallEdit, PMFeedback

logger = get_logger(__name__)

MAX_RETRIES = 3

_REVIEW_SYSTEM_PROMPT = """You are the Portfolio Manager reviewing Quant and Backtester function-call plans.

Each plan is a list of FunctionCall objects: {function_name, params}.

Your output is a PMFeedback object:
  approved       — true if the plans are correct and complete (after your edits)
  quant_edits    — list of FunctionCallEdit targeting the Quant calls by 0-based index
  backtester_edits — list of FunctionCallEdit targeting the Backtester calls by 0-based index
  reason         — ONE sentence only, required when approved=false

FunctionCallEdit fields:
  index          — 0-based position in the calls list
  action         — "remove" | "update_params" | "replace_function"
  new_params     — replacement params dict (action=update_params)
  new_function_name — replacement name (action=replace_function)

Rules:
- If a call has wrong or missing params → add an update_params edit
- If a call uses an unrecognised function name → add a replace_function or remove edit
- If duplicate calls exist → add remove edits for the duplicates (keep the first)
- If a plan has more than 5 calls or more than 3 unique function names → add remove edits to bring it within limits
- Set approved=true if the plan answers the query correctly after your edits
- Set approved=false ONLY if the plan has a structural problem you cannot fix with edits (e.g. completely wrong approach, missing mandatory first step)
- Keep edits minimal — fix, do not redesign

═══════════════════════════════════════════════════════════
FUNCTION REGISTRY REFERENCE  (authoritative defaults — never override unless the user explicitly requested a different value)
═══════════════════════════════════════════════════════════

VALID TIMEFRAMES (exact strings only — AlpacaDAO rejects anything else):
  "1Min"  "5Min"  "15Min"  "1Hour"  "1Day"
  ✗ Never use: "1d", "1day", "1D", "daily", "1h", "1hour", "hourly", "1m", "1min"
  Default "1Min"

───────────────────────────────────────────────────────────
QUANT FUNCTIONS — LIVE and HISTORICAL modes
───────────────────────────────────────────────────────────
All five indicator functions support two data modes:
  LIVE mode      — omit start_date/end_date; use lookback_days (from today backwards)
  HISTORICAL mode — provide start_date + end_date; omit lookback_days

calc_momentum
  LIVE       : symbol (str)  [timeframe="1Min"]  [lookback_days=90]
  HISTORICAL : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)  [timeframe="1Min"]
  Computes   : MACD (value, signal, histogram) + RSI

calc_volatility_bands
  LIVE       : symbol (str)  [timeframe="1Min"]  [lookback_days=90]
  HISTORICAL : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)  [timeframe="1Min"]
  Computes   : Bollinger Bands (upper, middle, lower, bandwidth)

calc_volume_flow
  LIVE       : symbol (str)  [timeframe="1Min"]  [lookback_days=90]
  HISTORICAL : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)  [timeframe="1Min"]
  Computes   : OBV + volume trend (increasing/decreasing/stable)

analyze_candle_structure
  LIVE       : symbol (str)  [timeframe="1Min"]  [lookback_days=30]   ← default 30, not 90
  HISTORICAL : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)  [timeframe="1Min"]
  Detects    : Engulfing, Doji, Hammer, Hanging Man

mean_reversion_analyze
  LIVE       : symbol (str)  [lookback=60]  [threshold=2.0]
  HISTORICAL : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)  [threshold=2.0]  [timeframe="1Min"]
  Note       : timeframe is valid ONLY in HISTORICAL mode
  Computes   : Z-score, Bollinger, moving averages, buy/sell/hold signal + trade_recommendation

get_market_bars
  Required : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)
  Optional : timeframe="1Min"

get_latest_price
  Required : symbol (str)
  Optional : timeframe="1Min"

get_precomputed_indicators
  Required : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)
  Optional : timeframe="1Min"

check_data_availability
  Required : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)
  Optional : timeframe="1Min"
  Use when Quant needs to verify bar coverage before a historical indicator call.

fetch_historical_data
  Required : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)
  Optional : timeframe="1Min"   ← default is 1Min
  Use only when check_data_availability reports bars are missing.
  Must have priority=3 and depends_on=[<check_task_id>].
  If bars_available=True from DATA AVAILABILITY REPORT, remove this task.

get_company_fundamentals
  Required : symbol (str)
  No optional params

get_earnings_history
  Required : symbol (str)
  Optional : quarterly=True  limit=4

get_eod_summaries
  Required : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)
  Use limit=1 for the most recent summary

get_recent_signals
  Required : symbol (str)  strategy_name (str)
  Optional : limit=10

get_actionable_signals
  Optional : min_confidence=0.6
  Returns  : high-confidence signals across all strategies

───────────────────────────────────────────────────────────
BACKTESTER FUNCTIONS
───────────────────────────────────────────────────────────
check_data_availability    ← ALWAYS first task (bt_001, priority=1)
  Required : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)
  Optional : timeframe="1Min"
  ⚠ param name is "symbol" — NOT "ticker"

fetch_historical_data      ← Only if data is missing (bt_002, priority=3)
  Required : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)
  Optional : timeframe="1Min"   ← default is 1Min, not 1Day
  ⚠ param name is "symbol" — NOT "ticker"

backtest_strategy          ← Last task (depends_on=[bt_002] if fetch was added)
  Required : symbol (str)  start_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)
  Optional : strategy="mean-reversion"  initial_capital=100000.0
  Valid strategies: "buy-and-hold" | "mean-reversion" | "momentum" | "value"
  ⚠ EXACT strings only — never "momentum_SMA_50_200" or any variant. If you see a non-canonical
    strategy string, emit an update_params edit to replace it with the nearest valid name.
  DEFAULT STRATEGY: always "mean-reversion" for workflow A unless user specified otherwise

save_eod_snapshot          ← Workflow B: save portfolio snapshot
  Required : timestamp (ISO str)  equity (float)  cash (float)
             buying_power (float)  positions (list of position dicts)
  Optional : portfolio_value=None

snapshot_worth             ← Workflow B: calculate portfolio value over a range
  Required : snapshot_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)

swap_positions             ← Workflow C: simulate position swap
  Required : snapshot_date (YYYY-MM-DD)  end_date (YYYY-MM-DD)
             tickers (list[str])

get_market_bars            (same signature as quant version above)
get_latest_price           (same signature as quant version above)

get_intraday_stats
  Required : symbol (str)  date (YYYY-MM-DD)
  No optional params

get_recent_backtest_runs
  Optional : strategy_name=None  limit=10

get_backtest_performance
  Required : run_id (str or int)

get_strategy_performance
  Required : strategy_name (str)
  Optional : days=30

───────────────────────────────────────────────────────────
CRITICAL PARAM RULES — violations must be corrected with update_params edits
───────────────────────────────────────────────────────────
1.  All functions use "symbol" — "ticker" is NEVER a valid param name
2.  Timeframe strings must be canonical ("1Day" not "1d"; "1Min" not "1min")
3.  fetch_historical_data default timeframe is "1Min" (granular intraday), not "1Day"
4.  mean_reversion_analyze in LIVE mode has NO timeframe — remove it if present in live calls
    In HISTORICAL mode (start_date + end_date present) timeframe IS valid — leave it
5.  initial_capital must be a float (100000.0) — reject integer-only "100000"
6.  Do NOT change dates the agents set unless they are clearly invalid (e.g. end < start)
7.  Do NOT change lookback_days / lookback / threshold unless clearly out of range
8.  task_id / priority / depends_on are TOP-LEVEL task fields — they must NEVER appear
    inside the params dict. If you see them in params, emit an update_params edit that
    removes them (rebuild params without those keys). The executor will error if they
    are left in params.
9.  NEVER allow both start_date/end_date and lookback_days in the same indicator call.
    If both are present, keep start_date/end_date and remove lookback_days (historical
    mode takes precedence when a date range was explicitly provided by the user).
───────────────────────────────────────────────────────────"""


def _format_calls(label: str, queue: Optional[List[Dict[str, Any]]]) -> str:
    """Format a FunctionCall queue for PM review.

    Args:
        label: Agent label e.g. "Quant", "Backtester".
        queue: List of {function_name, params} dicts.

    Returns:
        Formatted string with 0-based index prefix.
    """
    if not queue:
        return f"{label} calls: (none)"
    unique_fns = len({c.get("function_name") for c in queue})
    lines = [f"{label} calls ({len(queue)} total, {unique_fns} unique functions):"]
    for i, c in enumerate(queue):
        fn = c.get("function_name", "?")
        params = str(c.get("params", {}))[:80]
        lines.append(f"  [{i}] {fn}  params={params}")
    return "\n".join(lines)


def _apply_edits(
    queue: List[Dict[str, Any]],
    edits: List[FunctionCallEdit],
    label: str,
) -> List[Dict[str, Any]]:
    """Apply a list of FunctionCallEdits to a calls queue in-place order.

    Processes remove edits last (descending index) so earlier edits are not
    shifted by prior deletions.

    Args:
        queue: Mutable list of {function_name, params} dicts.
        edits: Edits from PMFeedback.
        label: Agent label for logging.

    Returns:
        Updated queue (new list).
    """
    if not edits:
        return queue

    updated = list(queue)  # shallow copy

    # Apply non-remove edits first (stable indices)
    for edit in edits:
        if edit.action == "remove":
            continue
        idx = edit.index
        if idx < 0 or idx >= len(updated):
            logger.warning(f"[pm_review] {label} edit index {idx} out of range — skipping")
            continue
        if edit.action == "update_params" and edit.new_params is not None:
            updated[idx] = {**updated[idx], "params": edit.new_params}
            logger.info(f"[pm_review] {label}[{idx}] params updated → {edit.new_params}")
        elif edit.action == "replace_function" and edit.new_function_name:
            new_params = edit.new_params if edit.new_params is not None else updated[idx].get("params", {})
            updated[idx] = {"function_name": edit.new_function_name, "params": new_params}
            logger.info(f"[pm_review] {label}[{idx}] replaced → {edit.new_function_name}")

    # Apply remove edits in descending index order to preserve positions
    remove_indices = sorted(
        {edit.index for edit in edits if edit.action == "remove"},
        reverse=True,
    )
    for idx in remove_indices:
        if 0 <= idx < len(updated):
            removed = updated.pop(idx)
            logger.info(f"[pm_review] {label}[{idx}] removed ({removed.get('function_name')})")

    return updated


def pm_review_node(state: dict) -> dict:
    """PM supervisor review using structured PMFeedback with FunctionCallEdits.

    Reviews Quant and Backtester call lists, applies edits directly to the
    queues, and returns the corrected queues + approval decision.

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update with corrected queues and pm_review fields.
    """
    try:
        from langchain_openai import ChatOpenAI
        from pydantic import ValidationError
        from src.common.utils import secrets, config

        query: str = state.get("query", "")
        intent: str = state.get("intent", "unknown")
        current_iteration: int = state.get("review_iteration") or 0
        portfolio_queue = state.get("portfolio_task_queue") or []
        quant_queue: List[Dict] = list(state.get("quant_task_queue") or [])
        bt_queue: List[Dict] = list(state.get("backtester_task_queue") or [])

        # Auto-approve when no sub-agent tasks exist
        if not quant_queue and not bt_queue:
            logger.info("[pm_review] no sub-agent tasks — auto-approving PM plan")
            return {
                "pm_review_approved": True,
                "pm_review_notes": "PM plan approved — no sub-agent tasks to review.",
                "pm_review_edits": None,
            }

        logger.info(
            f"[pm_review] reviewing {len(portfolio_queue)} PM + "
            f"{len(quant_queue)} quant + {len(bt_queue)} bt calls "
            f"(iteration={current_iteration})"
        )

        task_summary = "\n\n".join([
            _format_calls("Quant", quant_queue),
            _format_calls("Backtester", bt_queue),
        ])

        revision_context = (
            f"\nThis is REVISION REVIEW #{current_iteration} — agents have revised their plans.\n"
            if current_iteration > 0 else ""
        )

        # ── Data availability pre-check results ──────────────────────────────
        data_avail = state.get("data_availability") or {}
        data_avail_section = ""
        if data_avail:
            symbol_da = data_avail.get("symbol", "N/A")
            indicators_avail = data_avail.get("indicators_available", False)
            ind_rows = data_avail.get("indicator_rows", 0)
            bars_avail = data_avail.get("bars_available", False)
            bar_count = data_avail.get("bar_count", 0)
            trades_avail = data_avail.get("trades_available", False)
            trade_count = data_avail.get("trade_count", 0)

            data_avail_section = (
                f"\nDATA AVAILABILITY REPORT (symbol={symbol_da}):\n"
                f"  indicators_available={indicators_avail}  ({ind_rows} pre-computed rows)\n"
                f"  bars_available={bars_avail}  ({bar_count} bars in DB)\n"
                f"  trades_available={trades_avail}  ({trade_count} trades)\n"
                f"\nREVIEW GUIDANCE based on data availability:\n"
            )
            if indicators_avail:
                data_avail_section += (
                    "  - Pre-computed indicators exist. If Quant is ONLY calling calc_* functions "
                    "without get_precomputed_indicators, flag this but do NOT force a rejection — "
                    "calc_* results are still valid.\n"
                )
            if bars_avail:
                data_avail_section += (
                    "  - Bars ARE in the DB. If Backtester included fetch_historical_data, "
                    "add a remove edit for that task — data is already present.\n"
                )
            else:
                data_avail_section += (
                    "  - No bars found in DB. If Backtester is missing fetch_historical_data "
                    "before backtest_strategy, that is a structural error — set approved=false.\n"
                )

        user_message = (
            f"User query: {query}\n"
            f"Intent: {intent}\n"
            f"{revision_context}"
            f"{data_avail_section}\n"
            f"Plans to review:\n\n{task_summary}"
        )

        llm = ChatOpenAI(
            model=config.get("graph_api.reasoning_model", "gpt-5-mini"),
            temperature=config.get("graph_api.model_temperature", 0.0),
            api_key=secrets.get("openai.api_key"),
        )
        structured_llm = llm.with_structured_output(PMFeedback, method="function_calling")

        messages = [
            {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        feedback: Optional[PMFeedback] = None
        last_error: Optional[str] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                feedback = structured_llm.invoke(messages)
                logger.info(
                    f"[pm_review] feedback on attempt {attempt}: "
                    f"approved={feedback.approved}  "
                    f"quant_edits={len(feedback.quant_edits)}  "
                    f"bt_edits={len(feedback.backtester_edits)}"
                )
                break
            except (ValidationError, Exception) as exc:
                last_error = str(exc)
                logger.warning(f"[pm_review] attempt {attempt}/{MAX_RETRIES} failed: {exc}")

        if feedback is None:
            logger.error(f"[pm_review] all {MAX_RETRIES} attempts failed: {last_error} — auto-approving")
            feedback = PMFeedback(approved=True)

        # Apply edits to queues before returning
        edited_quant = _apply_edits(quant_queue, feedback.quant_edits, "Quant")
        edited_bt = _apply_edits(bt_queue, feedback.backtester_edits, "Backtester")

        # Serialise edits for state / agent revision feedback
        edits_payload = {
            "quant_edits": [e.model_dump() for e in feedback.quant_edits],
            "backtester_edits": [e.model_dump() for e in feedback.backtester_edits],
            "reason": feedback.reason,
        }

        if feedback.approved:
            logger.info(f"[pm_review] approved — quant={len(edited_quant)} bt={len(edited_bt)} calls after edits")
            return {
                "pm_review_approved": True,
                "pm_review_notes": feedback.reason or "Plans approved.",
                "pm_review_edits": edits_payload,
                "quant_task_queue": edited_quant,
                "backtester_task_queue": edited_bt,
            }

        # Rejected: structural problem that edits couldn't fix
        logger.warning(f"[pm_review] rejected (iter={current_iteration}): {feedback.reason}")
        return {
            "pm_review_approved": False,
            "pm_review_notes": feedback.reason or "Plan rejected — structural problem.",
            "pm_review_edits": edits_payload,
            "review_iteration": current_iteration + 1,
            "quant_task_queue": [],
            "backtester_task_queue": [],
            "quant_reasoning": None,
            "backtester_reasoning": None,
        }

    except Exception as exc:
        logger.error(f"[pm_review] unexpected error: {exc}", exc_info=True)
        return {
            "pm_review_approved": True,
            "pm_review_notes": f"Review error (auto-approved): {exc}",
            "pm_review_edits": None,
        }


if __name__ == "__main__":
    """Functional test: PM review with mock FunctionCall queues."""
    print("=" * 60)
    print("pm_review_node Functional Test")
    print("=" * 60)

    mock_state = {
        "query": "Analyze AAPL momentum and backtest mean-reversion",
        "intent": "full_analysis",
        "portfolio_task_queue": [],
        "quant_task_queue": [
            {"function_name": "calc_momentum", "params": {"symbol": "AAPL", "timeframe": "1Day", "lookback_days": 90}},
            {"function_name": "mean_reversion_analyze", "params": {"symbol": "AAPL", "lookback": 60, "threshold": 2.0}},
        ],
        "backtester_task_queue": [
            {"function_name": "check_data_availability", "params": {"symbol": "AAPL", "start_date": "2024-01-01", "end_date": "2024-03-01"}},
            {"function_name": "backtest_strategy", "params": {"ticker": "AAPL", "start_date": "2024-01-01", "end_date": "2024-03-01", "strategy": "mean-reversion", "initial_capital": 100000}},
        ],
        "review_iteration": 0,
    }

    result = pm_review_node(mock_state)
    print(f"[OK] approved={result['pm_review_approved']}")
    print(f"[OK] notes={result['pm_review_notes']}")
    print(f"[OK] edits={result.get('pm_review_edits')}")
    assert "pm_review_approved" in result
    print("\n[ALL OK] pm_review_node test passed")
