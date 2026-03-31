"""Synthesizer node for the semi-auto multi-agent system.

Reads the fully populated state (reasoning traces + execution results) and
produces a final structured SemiAutoResponse using LLM synthesis.
Also persists the complete turn to portfolio.duckdb via PortfolioDAO.

Sets state fields: final_response, execution_time_ms.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

_SYNTHESIZER_SYSTEM_PROMPT = """You are a Portfolio Manager AI synthesizing multi-agent results into a compact SynthesisResult.

FIELD GUIDANCE:

headline — concise title: e.g. "AAPL — Mean-Reversion Backtest", "MSFT Technical Analysis", "Portfolio Status"

intent — one of: "backtest" | "quant" | "portfolio" | "mixed"

verdict — BACKTEST ONLY: "RECOMMENDED" or "NOT RECOMMENDED"

summary_quote — BACKTEST ONLY: one verbatim sentence from the backtest summary field

overall_signal — QUANT ONLY: "BUY", "SELL", or "HOLD"

signal_confidence — QUANT ONLY: "High" (≥2 confirming), "Medium" (split), "Low" (insufficient data)

sections — use minimal sections:
  * Backtest: "Returns", "Risk", "Trade Statistics"
  * Quant: "Momentum", "Volatility", "Volume" (only if data exists per indicator)
  * Portfolio: ONE section titled "Portfolio" — consolidate ALL metrics (account + positions + health) into one table
  Each section:
    - table: {metric, value} rows for numeric data only — pre-format values ("+12.50%", "$100,000")
    - bullets: ONLY if the observation adds genuine insight NOT already visible in the table. Max 1 bullet/section. OMIT bullets for portfolio sections unless a position needs highlighting.
    - note: ONLY for actual errors, missing data, or real warnings. Leave empty otherwise.

takeaway — ONE short sentence: the single most actionable conclusion

agents_used — only agents that actually ran

error_note — only if a task failed or returned no data; leave empty if everything succeeded

RULES:
- Never repeat table data as a bullet (if the table shows equity=$100k, do NOT add a bullet saying 'Equity is $100k')
- Never invent or estimate metrics not present in the results
- For portfolio with no open positions: table shows zeros; one bullet max; skip the note
- If backtest has multiple strategies, one "Strategy: <name>" section group per strategy
- Omit empty sections/tables entirely
"""


def _format_backtest_result(result_data: dict) -> str:
    """Format a backtest_strategy result dict into a readable grouped block.

    Groups metrics into Returns, Risk, and Trade-Stats sections so the
    LLM receives all key numbers without truncation and in logical order.

    Args:
        result_data: The ``result`` field from an executor task result.

    Returns:
        Formatted multi-line string.
    """

    def _pct(v):
        try:
            return f"{float(v):+.2f}%"
        except (TypeError, ValueError):
            return str(v)

    def _money(v):
        try:
            fv = float(v)
            return f"-${abs(fv):,.2f}" if fv < 0 else f"${fv:,.2f}"
        except (TypeError, ValueError):
            return str(v)

    def _ratio(v):
        try:
            return f"{float(v):.3f}"
        except (TypeError, ValueError):
            return str(v)

    def _rate(v):
        try:
            fv = float(v)
            return f"{fv * 100:.1f}%" if fv <= 1.0 else f"{fv:.1f}%"
        except (TypeError, ValueError):
            return str(v)

    def _int(v):
        try:
            return str(int(v))
        except (TypeError, ValueError):
            return str(v)

    lines = []

    # ── Header ──────────────────────────────────────────────────────────
    ticker = result_data.get("ticker") or result_data.get("symbol") or "?"
    strategy = result_data.get("strategy") or "?"
    start = result_data.get("start_date") or ""
    end = result_data.get("end_date") or ""
    run_id = result_data.get("run_id")
    header_parts = [f"strategy={strategy}", f"ticker={ticker}"]
    if start and end:
        header_parts.append(f"{start} to {end}")
    if run_id:
        header_parts.append(f"run_id={run_id}")
    sep = "=" * 64
    lines.append(sep)
    lines.append("  BACKTEST RESULT: " + "  |  ".join(header_parts))
    lines.append(sep)

    # ── Verdict & Summary ──────────────────────────────────────────────
    if result_data.get("recommendation"):
        rec = result_data["recommendation"].upper()
        icon = "[OK]" if "RECOMMEND" in rec and "NOT" not in rec else "[NO]"
        lines.append(f"  Verdict  : {icon} {rec}")
    if result_data.get("summary"):
        lines.append(f"  Summary  : {result_data['summary']}")
    lines.append("")

    metrics = result_data.get("metrics") or result_data.get("performance") or {}
    if not metrics:
        lines.append("  (no metrics available)")
        return "\n".join(lines)

    # ── Returns section ────────────────────────────────────────────────
    RETURNS = [
        ("total_return_pct",     "Total Return",     _pct),
        ("total_return_dollars", "Total Return $",   _money),
        ("sharpe_ratio",         "Sharpe Ratio",     _ratio),
        ("sortino_ratio",        "Sortino Ratio",    _ratio),
        ("profit_factor",        "Profit Factor",    _ratio),
        ("initial_capital",      "Initial Capital",  _money),
        ("final_capital",        "Final Capital",    _money),
    ]
    RISK = [
        ("max_drawdown_pct",     "Max Drawdown %",   _pct),
        ("max_drawdown_dollars", "Max Drawdown $",   _money),
        ("volatility",           "Volatility",       _ratio),
        ("calmar_ratio",         "Calmar Ratio",     _ratio),
    ]
    TRADES = [
        ("total_trades",         "Total Trades",      _int),
        ("win_rate",             "Win Rate",          _rate),
        ("winning_trades",       "Winning Trades",    _int),
        ("losing_trades",        "Losing Trades",     _int),
        ("avg_win",              "Avg Win",           _money),
        ("avg_loss",             "Avg Loss",          _money),
        ("avg_trade",            "Avg Trade",         _money),
        ("largest_win",          "Largest Win",       _money),
        ("largest_loss",         "Largest Loss",      _money),
    ]

    seen = set()

    def _section(title: str, fields):
        rows = [(label, fmt(metrics[key])) for key, label, fmt in fields
                if key in metrics and metrics[key] is not None]
        if not rows:
            return
        lines.append(f"  --- {title} ---")
        for label, val in rows:
            lines.append(f"  {label:<26} {val}")
            seen.add(next(k for k, l, _ in fields if l == label))
        lines.append("")

    _section("RETURNS", RETURNS)
    _section("RISK", RISK)
    _section("TRADE STATISTICS", TRADES)

    # Any leftover metrics not in the canonical sets
    extra = [(k, v) for k, v in metrics.items() if k not in seen and v is not None]
    if extra:
        lines.append("  --- ADDITIONAL METRICS ---")
        for k, v in extra:
            lines.append(f"  {k:<26} {v}")

    return "\n".join(lines)


def _format_execution_results(execution_results: Dict[str, Any]) -> str:
    """Format execution results for the synthesis prompt.

    Backtest results receive full metric/summary/recommendation treatment.
    Other results are JSON-serialised with a generous limit.

    Args:
        execution_results: Dict of task_id → result dicts.

    Returns:
        Formatted string of results.
    """
    if not execution_results:
        return "No functions were executed."

    lines = []
    for task_id, result in execution_results.items():
        fn = result.get("function_name", "unknown")
        status = result.get("status", "unknown")
        duration = result.get("timing", {}).get("duration_ms", 0) if isinstance(result.get("timing"), dict) else 0
        lines.append(f"\n[{task_id}] {fn} — {status} ({duration}ms)")

        if status == "error":
            lines.append(f"Error: {result.get('error', 'unknown')}")
            continue

        result_data = result.get("result")
        if not result_data:
            continue

        # Backtest results get full structured formatting
        if fn == "backtest_strategy" or (isinstance(result_data, dict) and ("metrics" in result_data or "summary" in result_data)):
            lines.append(_format_backtest_result(result_data))
        else:
            # Generic results: JSON with a larger budget than before
            result_str = json.dumps(result_data, indent=2, default=str)
            lines.append(result_str[:1200] + ("..." if len(result_str) > 1200 else ""))

    return "\n".join(lines)


def _build_synthesis_prompt(state: dict) -> str:
    """Build the user message for the synthesis LLM call.

    Args:
        state: Current GraphState dict.

    Returns:
        Formatted prompt string.
    """
    query = state.get("query", "")
    intent = state.get("intent", "unknown")
    symbol = state.get("symbol")
    turn = state.get("turn_number", 1)

    sections = [
        f"User query: {query}",
        f"Intent: {intent}",
        f"Symbol: {symbol or 'N/A'}",
        f"Turn: {turn}",
    ]

    if state.get("portfolio_reasoning"):
        sections.append(f"\n=== PM Reasoning ===\n{state['portfolio_reasoning']}")

    if state.get("quant_reasoning"):
        sections.append(f"\n=== Quant Reasoning ===\n{state['quant_reasoning']}")

    if state.get("backtester_reasoning"):
        sections.append(f"\n=== Backtester Reasoning ===\n{state['backtester_reasoning']}")

    exec_results = state.get("execution_results") or {}
    sections.append(f"\n=== Execution Results ===\n{_format_execution_results(exec_results)}")

    if state.get("error"):
        sections.append(f"\n=== Error ===\n{state['error']}")

    return "\n".join(sections)


def _persist_turn(state: dict, final_response: str, start_time: float) -> None:
    """Persist the completed turn to portfolio.duckdb.

    Args:
        state: Final GraphState dict.
        final_response: Synthesized response string.
        start_time: monotonic time when graph started (for execution_time_ms).
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO

        thread_id = state.get("thread_id", "unknown")
        query = state.get("query", "")
        turn_number = state.get("turn_number", 1)

        tool_sequence = []
        for agent_key in ("portfolio_task_queue", "quant_task_queue", "backtester_task_queue"):
            queue = state.get(agent_key) or []
            if queue:
                agent = agent_key.replace("_task_queue", "")
                tool_sequence.append({
                    "agent": agent,
                    "tasks": [t.get("function_name") for t in queue],
                    "reasoning": state.get(f"{agent}_reasoning", ""),
                })

        exec_results = state.get("execution_results") or {}
        success_count = sum(1 for r in exec_results.values() if r.get("status") == "success")
        tool_timings = state.get("tool_timings") or []

        dao = PortfolioDAO()
        dao.save_interaction(
            thread_id=thread_id,
            agent_name="semi_auto_pm",
            user_query=query,
            tool_sequence=tool_sequence,
            agent_response=final_response[:1000],
            model_used="gpt-5-mini",
            token_count=None,
            execution_time_ms=int((time.monotonic() - start_time) * 1000),
            tool_timings=tool_timings,
            delegated_to=",".join(
                a for a in ("quant", "backtester")
                if state.get(f"_delegate_{a}")
            ),
            delegation_result=f"{success_count}/{len(exec_results)} tasks succeeded",
        )
        dao.close()
        logger.info(f"[synthesizer] turn {turn_number} persisted for thread={thread_id}")
    except Exception as exc:
        logger.warning(f"[synthesizer] DB persistence failed (non-critical): {exc}")


def synthesizer_node(state: dict) -> dict:
    """Synthesize final response from all collected state data.

    Handles routing_error short-circuit (from market hours guard).
    Otherwise calls LLM synthesis and persists turn to DB.

    Args:
        state: Current GraphState dict with all populated fields.

    Returns:
        Partial state update with final_response and execution_time_ms.
    """
    start_time = time.monotonic()

    # Short-circuit: guard already set a response
    if state.get("routing_error") and state.get("final_response"):
        logger.info("[synthesizer] short-circuit: routing_error set, skipping LLM")
        return {}

    logger.info(f"[synthesizer] synthesizing intent='{state.get('intent')}'")

    # Call LLM synthesis
    final_response = _call_llm(state)

    execution_time_ms = int((time.monotonic() - start_time) * 1000)

    _persist_turn(state, final_response, start_time)

    return {
        "final_response": final_response,
        "execution_time_ms": execution_time_ms,
    }


def _render_synthesis_result(result) -> str:
    """Render a SynthesisResult Pydantic object into well-formatted Markdown.

    This is a deterministic rendering step — no LLM involved.  The LLM fills
    the structured model; this function converts it to the Markdown string that
    the UI displays.

    Args:
        result: A ``SynthesisResult`` instance.

    Returns:
        Markdown string suitable for the stream_client.html renderer.
    """
    lines: List[str] = []

    # ── Headline ──────────────────────────────────────────────────────────
    lines.append(f"## {result.headline}")
    lines.append("")

    # ── Verdict (backtest) ────────────────────────────────────────────────
    if result.verdict:
        is_rec = "NOT" not in result.verdict.upper()
        icon = "✅" if is_rec else "❌"
        lines.append(f"**Verdict: {icon} {result.verdict}**")
        lines.append("")

    # ── Summary quote (backtest) ──────────────────────────────────────────
    if result.summary_quote:
        lines.append(f"> {result.summary_quote}")
        lines.append("")

    # ── Overall signal (quant) ────────────────────────────────────────────
    if result.overall_signal:
        signal_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(
            result.overall_signal.upper(), "⚪"
        )
        lines.append(
            f"**Signal: {signal_emoji} {result.overall_signal}**"
            + (f"  |  **Confidence: {result.signal_confidence}**" if result.signal_confidence else "")
        )
        lines.append("")

    # ── Sections ──────────────────────────────────────────────────────────
    for section in result.sections:
        lines.append(f"### {section.title}")

        if section.table:
            lines.append("| Metric | Value |")
            lines.append("|--------|------:|")
            for row in section.table:
                lines.append(f"| {row.metric} | {row.value} |")

        if section.bullets:
            lines.append("")
            for bullet in section.bullets:
                lines.append(f"- {bullet}")

        if section.note:
            lines.append(f"")
            lines.append(f"*{section.note}*")

        lines.append("")

    # ── Takeaway ──────────────────────────────────────────────────────────
    if result.takeaway:
        lines.append(f"> **Bottom line:** {result.takeaway}")
        lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────
    footer_parts: List[str] = []
    if result.agents_used:
        footer_parts.append(f"Agents: {', '.join(result.agents_used)}")
    if result.error_note:
        footer_parts.append(f"⚠ {result.error_note}")
    if footer_parts:
        lines.append("---")
        lines.append(" · ".join(f"*{p}*" for p in footer_parts))

    return "\n".join(lines)


def _call_llm(state: dict) -> str:
    """Call gpt-5-mini with structured output to synthesize final response from state.

    Uses ``with_structured_output(SynthesisResult)`` so the LLM fills a typed
    Pydantic model instead of producing free-form Markdown.  The model is then
    rendered to Markdown by ``_render_synthesis_result``.

    Args:
        state: Current GraphState dict.

    Returns:
        Synthesized response as a Markdown string.
    """
    try:
        from langchain_openai import ChatOpenAI
        from src.common.utils import secrets, config
        from src.semi_auto.models.responses import SynthesisResult

        llm = ChatOpenAI(
            model=config.get("graph_api.routing_model", "gpt-4o-mini"),
            temperature=config.get("graph_api.synthesizer_temperature", 0.2),
            api_key=secrets.get("openai.api_key"),
        )
        structured_llm = llm.with_structured_output(SynthesisResult)
        prompt = _build_synthesis_prompt(state)
        result: SynthesisResult = structured_llm.invoke([
            {"role": "system", "content": _SYNTHESIZER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        return _render_synthesis_result(result)
    except Exception as exc:
        logger.warning(f"[synthesizer] LLM call failed: {exc}")
        # Graceful degradation
        exec_results = state.get("execution_results") or {}
        success = [k for k, v in exec_results.items() if v.get("status") == "success"]
        return (
            f"Analysis complete (synthesis unavailable). "
            f"Intent: {state.get('intent', 'unknown')}. "
            f"{len(success)}/{len(exec_results)} tasks succeeded."
        )


if __name__ == "__main__":
    """Functional test: synthesizer with mock state."""
    print("=" * 60)
    print("synthesizer_node Functional Tests")
    print("=" * 60)

    # Test 1: short-circuit on routing_error
    print("\n[1/3] Short-circuit on routing_error")
    result = synthesizer_node({
        "routing_error": "Market is closed",
        "final_response": "Market Hours Guard — Market is closed.",
        "query": "Analyze AAPL",
        "intent": "quant",
    })
    assert result == {}, f"Expected empty dict, got: {result}"
    print("[OK] short-circuit returns empty dict")

    # Test 2: portfolio synthesis with mock execution results
    print("\n[2/3] Portfolio synthesis with mock results")
    mock_state = {
        "query": "What is my portfolio status?",
        "intent": "portfolio",
        "symbol": None,
        "thread_id": "test-thread-001",
        "turn_number": 1,
        "routing_error": None,
        "portfolio_reasoning": "Fetched portfolio status and positions.",
        "quant_reasoning": None,
        "backtester_reasoning": None,
        "execution_results": {
            "pm_001": {
                "task_id": "pm_001",
                "function_name": "get_portfolio_status",
                "status": "success",
                "result": {"equity": 100000.0, "cash": 50000.0},
                "timing": {"tool": "get_portfolio_status", "duration_ms": 340},
            }
        },
        "portfolio_task_queue": [{"function_name": "get_portfolio_status"}],
        "quant_task_queue": None,
        "backtester_task_queue": None,
        "tool_timings": [],
    }
    result2 = synthesizer_node(mock_state)
    assert "final_response" in result2
    assert "execution_time_ms" in result2
    print(f"[OK] final_response generated ({len(result2['final_response'])} chars)")
    print(f"[OK] execution_time_ms: {result2['execution_time_ms']}ms")
    print(f"     preview: {result2['final_response'][:120]}...")

    # Test 3: no data graceful degradation
    print("\n[3/3] Graceful degradation — no results")
    result3 = synthesizer_node({
        "query": "Analyze MSFT",
        "intent": "quant",
        "thread_id": "test-003",
        "turn_number": 1,
        "routing_error": None,
        "execution_results": {},
        "portfolio_task_queue": None,
        "quant_task_queue": None,
        "backtester_task_queue": None,
    })
    assert "final_response" in result3
    print(f"[OK] degraded response: {result3['final_response'][:80]}...")

    print("\n[ALL OK] synthesizer_node tests complete")
