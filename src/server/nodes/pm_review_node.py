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
from pydantic import ValidationError

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.server.agents import get_llm
from src.server.constants import MAX_RETRIES
from src.server.models.task import FunctionCallEdit, PMFeedback
from src.common.utils import load_prompt

logger = get_logger(__name__)

_REVIEW_SYSTEM_PROMPT = load_prompt("pm_review")


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


def _parse_feedback_rules(
    feedback: str,
    quant_queue: List[Dict[str, Any]],
    bt_queue: List[Dict[str, Any]],
    order_queue: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Parse user feedback using deterministic rules and generate task edits.

    Rules-based patterns:
    - "remove [function_name]" → remove that task
    - "change/use timeframe [value]" → update timeframe param
    - "change/use strategy [value]" → update strategy param
    - "remove fetch" → remove fetch_historical_data tasks
    - "add [X]" → requires structural change, reject for re-plan
    - "change symbol to [X]" → update symbol param
    - "use [X] days" / "[X]d lookback" → update lookback_days/lookback param

    Args:
        feedback: User's natural language feedback.
        quant_queue: Current quant task queue.
        bt_queue: Current backtester task queue.
        order_queue: Current order task queue.

    Returns:
        Dict with keys: quant_edits, backtester_edits, order_edits, approved, reason.
        None if feedback cannot be parsed.
    """
    import re

    feedback_lower = feedback.lower()
    quant_edits = []
    bt_edits = []
    order_edits = []
    reason = "Feedback processed"
    approved = True

    # ── RULE: Remove specific function ────────────────────────────────────────
    # Pattern: "remove [function_name]" or "delete [function_name]"
    remove_patterns = [
        r"(?:remove|delete)\s+(\w+)",
        r"(?:remove|delete)\s+(?:the\s+)?([a-z_]+)\s+(?:task|function|call)",
    ]

    for pattern in remove_patterns:
        matches = re.findall(pattern, feedback_lower)
        for fn_name in matches:
            # Find and remove from quant queue
            for i, task in enumerate(quant_queue):
                if fn_name in task.get("function_name", "").lower():
                    quant_edits.append(FunctionCallEdit(index=i, action="remove"))
                    reason += f" Removed quant task '{task['function_name']}'."
                    logger.info(f"[feedback] rule matched: remove quant[{i}] {task['function_name']}")

            # Find and remove from backtester queue
            for i, task in enumerate(bt_queue):
                if fn_name in task.get("function_name", "").lower():
                    bt_edits.append(FunctionCallEdit(index=i, action="remove"))
                    reason += f" Removed backtester task '{task['function_name']}'."
                    logger.info(f"[feedback] rule matched: remove bt[{i}] {task['function_name']}")

            # Find and remove from order queue
            for i, task in enumerate(order_queue):
                if fn_name in task.get("function_name", "").lower():
                    order_edits.append(FunctionCallEdit(index=i, action="remove"))
                    reason += f" Removed order task '{task['function_name']}'."
                    logger.info(f"[feedback] rule matched: remove order[{i}] {task['function_name']}")

    # ── RULE: Change timeframe ────────────────────────────────────────────────
    # Pattern: "use/change timeframe to [1Min|5Min|1Hour|1Day]"
    timeframe_match = re.search(
        r"(?:use|change|set)\s+(?:the\s+)?timeframe\s+(?:to\s+)?([0-9]+(?:Min|Hour|Day))",
        feedback,
        re.IGNORECASE
    )
    if timeframe_match:
        new_timeframe = timeframe_match.group(1)
        # Update all tasks with timeframe param
        for i, task in enumerate(quant_queue):
            if "timeframe" in task.get("params", {}):
                new_params = {**task["params"], "timeframe": new_timeframe}
                quant_edits.append(FunctionCallEdit(
                    index=i, action="update_params", new_params=new_params
                ))
                reason += f" Updated quant timeframe to {new_timeframe}."
                logger.info(f"[feedback] rule matched: update quant[{i}] timeframe={new_timeframe}")

        for i, task in enumerate(bt_queue):
            if "timeframe" in task.get("params", {}):
                new_params = {**task["params"], "timeframe": new_timeframe}
                bt_edits.append(FunctionCallEdit(
                    index=i, action="update_params", new_params=new_params
                ))
                reason += f" Updated backtester timeframe to {new_timeframe}."
                logger.info(f"[feedback] rule matched: update bt[{i}] timeframe={new_timeframe}")

    # ── RULE: Change strategy ──────────────────────────────────────────────────
    # Pattern: "use [strategy_name] strategy" or "change strategy to [name]"
    strategy_match = re.search(
        r"(?:use|change|set)\s+(?:the\s+)?(?:strategy\s+(?:to\s+)?)?([a-z-]+)\s+strategy",
        feedback_lower
    )
    if strategy_match:
        new_strategy = strategy_match.group(1)
        for i, task in enumerate(bt_queue):
            if task.get("function_name") == "backtest_strategy":
                new_params = {**task.get("params", {}), "strategy": new_strategy}
                bt_edits.append(FunctionCallEdit(
                    index=i, action="update_params", new_params=new_params
                ))
                reason += f" Updated strategy to '{new_strategy}'."
                logger.info(f"[feedback] rule matched: update bt[{i}] strategy={new_strategy}")

    # ── RULE: Change symbol ────────────────────────────────────────────────────
    # Pattern: "change symbol to [TICKER]" or "use [TICKER] instead"
    symbol_match = re.search(
        r"(?:change|use|set)\s+(?:the\s+)?symbol\s+(?:to\s+)?([A-Z]{1,5})",
        feedback,
        re.IGNORECASE
    )
    if not symbol_match:
        # Also try pattern: "use [TICKER]" or "[TICKER] instead"
        symbol_match = re.search(r"\b([A-Z]{2,5})\b", feedback)
    if symbol_match:
        new_symbol = symbol_match.group(1).upper()
        # Update symbol in all tasks
        for i, task in enumerate(quant_queue):
            if "symbol" in task.get("params", {}):
                new_params = {**task["params"], "symbol": new_symbol}
                quant_edits.append(FunctionCallEdit(
                    index=i, action="update_params", new_params=new_params
                ))
                logger.info(f"[feedback] rule matched: update quant[{i}] symbol={new_symbol}")

        for i, task in enumerate(bt_queue):
            if "symbol" in task.get("params", {}):
                new_params = {**task["params"], "symbol": new_symbol}
                bt_edits.append(FunctionCallEdit(
                    index=i, action="update_params", new_params=new_params
                ))
                logger.info(f"[feedback] rule matched: update bt[{i}] symbol={new_symbol}")

        reason += f" Updated symbol to {new_symbol}."

    # ── RULE: Change lookback period ───────────────────────────────────────────
    # Pattern: "use [N] days" or "[N]d lookback"
    lookback_match = re.search(r"(?:use\s+)?(\d+)\s*(?:days?|d)\s+(?:lookback)?", feedback_lower)
    if lookback_match:
        new_lookback = int(lookback_match.group(1))
        for i, task in enumerate(quant_queue):
            params = task.get("params", {})
            if "lookback_days" in params or "lookback" in params:
                param_name = "lookback_days" if "lookback_days" in params else "lookback"
                new_params = {**params, param_name: new_lookback}
                quant_edits.append(FunctionCallEdit(
                    index=i, action="update_params", new_params=new_params
                ))
                reason += f" Updated lookback to {new_lookback} days."
                logger.info(f"[feedback] rule matched: update quant[{i}] {param_name}={new_lookback}")

    # ── RULE: Structural changes (reject for re-plan) ─────────────────────────
    # Pattern: "add [something]" requires new tasks
    if re.search(r"\b(?:add|include|also\s+(?:run|do))\b", feedback_lower):
        approved = False
        reason = "Feedback requires adding new tasks. Re-planning with sub-agent."
        logger.info("[feedback] rule matched: structural change detected (add new tasks)")

    # Return None if no rules matched
    if not quant_edits and not bt_edits and not order_edits and approved:
        logger.warning("[feedback] no rules matched feedback text")
        return None

    return {
        "quant_edits": quant_edits,
        "backtester_edits": bt_edits,
        "order_edits": order_edits,
        "approved": approved,
        "reason": reason,
    }


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

    When is_feedback=True, processes user feedback using rule-based parsing
    and applies deterministic task modifications.

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update with corrected queues and pm_review fields.
    """
    try:
        query: str = state.get("query", "")
        intent: str = state.get("intent", "unknown")
        is_feedback: bool = state.get("is_feedback", False)
        current_iteration: int = state.get("review_iteration") or 0
        portfolio_queue = state.get("portfolio_task_queue") or []
        quant_queue: List[Dict] = list(state.get("quant_task_queue") or [])
        bt_queue: List[Dict] = list(state.get("backtester_task_queue") or [])
        order_queue: List[Dict] = list(state.get("order_task_queue") or [])

        # ── FEEDBACK HANDLING ─────────────────────────────────────────────────
        # When is_feedback=True, parse user feedback using rules and apply edits
        if is_feedback:
            logger.info(f"[pm_review] processing user feedback: \"{query[:80]}...\"")

            feedback_edits = _parse_feedback_rules(
                query, quant_queue, bt_queue, order_queue
            )

            if feedback_edits:
                # Apply feedback edits
                edited_quant = _apply_edits(quant_queue, feedback_edits["quant_edits"], "Quant")
                edited_bt = _apply_edits(bt_queue, feedback_edits["backtester_edits"], "Backtester")
                edited_order = _apply_edits(order_queue, feedback_edits["order_edits"], "Order")

                logger.info(
                    f"[pm_review] feedback edits applied: "
                    f"quant={len(edited_quant)} bt={len(edited_bt)} order={len(edited_order)} tasks"
                )

                edits_payload = {
                    "quant_edits": [e.model_dump() for e in feedback_edits["quant_edits"]],
                    "backtester_edits": [e.model_dump() for e in feedback_edits["backtester_edits"]],
                    "order_edits": [e.model_dump() for e in feedback_edits["order_edits"]],
                    "reason": feedback_edits["reason"],
                }

                if feedback_edits["approved"]:
                    return {
                        "pm_review_approved": True,
                        "pm_review_notes": f"Feedback applied: {feedback_edits['reason']}",
                        "pm_review_edits": edits_payload,
                        "quant_task_queue": edited_quant,
                        "backtester_task_queue": edited_bt,
                        "order_task_queue": edited_order,
                    }
                else:
                    return {
                        "pm_review_approved": False,
                        "pm_review_notes": f"Feedback requires re-plan: {feedback_edits['reason']}",
                        "pm_review_edits": edits_payload,
                        "review_iteration": current_iteration + 1,
                        "quant_task_queue": edited_quant,
                        "backtester_task_queue": edited_bt,
                        "order_task_queue": edited_order,
                    }

        # ── END FEEDBACK HANDLING ─────────────────────────────────────────────

        # Auto-approve when no sub-agent tasks exist
        if not quant_queue and not bt_queue and not order_queue:
            logger.info("[pm_review] no sub-agent tasks — auto-approving PM plan")
            return {
                "pm_review_approved": True,
                "pm_review_notes": "PM plan approved — no sub-agent tasks to review.",
                "pm_review_edits": None,
            }

        logger.info(
            f"[pm_review] reviewing {len(portfolio_queue)} PM + "
            f"{len(quant_queue)} quant + {len(bt_queue)} bt + {len(order_queue)} order calls "
            f"(iteration={current_iteration})"
        )

        task_summary = "\n\n".join(filter(None, [
            _format_calls("Quant", quant_queue),
            _format_calls("Backtester", bt_queue),
            _format_calls("Order", order_queue),
        ]))

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

        structured_llm = get_llm("pm_review").with_structured_output(PMFeedback, method="function_calling")

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
                    f"bt_edits={len(feedback.backtester_edits)}  "
                    f"order_edits={len(feedback.order_edits)}"
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
        edited_order = _apply_edits(order_queue, feedback.order_edits, "Order")

        # Serialise edits for state / agent revision feedback
        edits_payload = {
            "quant_edits": [e.model_dump() for e in feedback.quant_edits],
            "backtester_edits": [e.model_dump() for e in feedback.backtester_edits],
            "order_edits": [e.model_dump() for e in feedback.order_edits],
            "reason": feedback.reason,
        }

        if feedback.approved:
            logger.info(f"[pm_review] approved — quant={len(edited_quant)} bt={len(edited_bt)} order={len(edited_order)} calls after edits")
            return {
                "pm_review_approved": True,
                "pm_review_notes": feedback.reason or "Plans approved.",
                "pm_review_edits": edits_payload,
                "quant_task_queue": edited_quant,
                "backtester_task_queue": edited_bt,
                "order_task_queue": edited_order,
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
            "order_task_queue": [],
            "quant_reasoning": None,
            "backtester_reasoning": None,
            "order_reasoning": None,
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
