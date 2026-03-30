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

_SYNTHESIZER_SYSTEM_PROMPT = """You are a Portfolio Manager AI synthesizing the results of a multi-agent analysis.

Given the reasoning traces and function execution results below, produce a clear, concise final response.

Rules:
- Lead with the key finding or decision (e.g. "Portfolio is healthy at $X equity", "AAPL shows a Z-score of -1.8")
- Include the most critical numbers from the results
- Mention each agent's contribution briefly if applicable (PM, Quant, Backtester)
- Keep it to 2-3 short paragraphs maximum
- If tasks failed, acknowledge the missing data gracefully
- Plain prose — no bullet points, no markdown headers

For BACKTEST results specifically:
- Always quote the summary sentence from the result verbatim
- State total return %, Sharpe ratio, max drawdown %, and win rate explicitly
- Quote the recommendation field (RECOMMENDED / NOT RECOMMENDED) as your closing verdict on that strategy
- If multiple strategies were backtested, compare their Sharpe ratios and total returns side-by-side"""


def _format_backtest_result(result_data: dict) -> str:
    """Format a backtest_strategy result dict into a readable block.

    Extracts metrics, summary, and recommendation so the LLM receives
    all key numbers without truncation.

    Args:
        result_data: The ``result`` field from an executor task result.

    Returns:
        Formatted multi-line string.
    """
    lines = []

    # Top-level summary and recommendation are the most important
    if result_data.get("summary"):
        lines.append(f"  summary    : {result_data['summary']}")
    if result_data.get("recommendation"):
        lines.append(f"  verdict    : {result_data['recommendation']}")

    # Strategy / run metadata
    for field in ("strategy", "ticker", "symbol", "start_date", "end_date", "run_id"):
        if result_data.get(field):
            lines.append(f"  {field:<12}: {result_data[field]}")

    # Core performance metrics — always included fully (no truncation)
    metrics = result_data.get("metrics") or result_data.get("performance") or {}
    if metrics:
        lines.append("  metrics:")
        METRIC_ORDER = [
            "total_return_pct", "total_return_dollars",
            "sharpe_ratio", "sortino_ratio",
            "max_drawdown_pct", "max_drawdown_dollars",
            "win_rate", "profit_factor",
            "total_trades", "winning_trades", "losing_trades",
            "avg_win", "avg_loss", "avg_trade",
            "largest_win", "largest_loss",
        ]
        # Emit in canonical order first, then any extra keys
        seen = set()
        for key in METRIC_ORDER:
            if key in metrics:
                val = metrics[key]
                # Format percentages and dollars readably
                if "pct" in key:
                    lines.append(f"    {key:<30}: {val:.4f}%")
                elif "dollar" in key or key in ("avg_win", "avg_loss", "avg_trade", "largest_win", "largest_loss"):
                    lines.append(f"    {key:<30}: ${val:,.2f}")
                elif key in ("win_rate",):
                    lines.append(f"    {key:<30}: {val:.1%}")
                else:
                    lines.append(f"    {key:<30}: {val}")
                seen.add(key)
        for key, val in metrics.items():
            if key not in seen:
                lines.append(f"    {key:<30}: {val}")

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
                if state.get(f"_{a}_task_queue" if a == "quant" else "_delegate_backtester")
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


def _call_llm(state: dict) -> str:
    """Call gpt-5-mini to synthesize final response from state.

    Args:
        state: Current GraphState dict.

    Returns:
        Synthesized response string.
    """
    try:
        from langchain_openai import ChatOpenAI
        from src.common.utils import secrets

        llm = ChatOpenAI(
            model="gpt-5-mini",
            temperature=0.2,
            api_key=secrets.get("openai.api_key"),
        )
        prompt = _build_synthesis_prompt(state)
        response = llm.invoke([
            {"role": "system", "content": _SYNTHESIZER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        return response.content
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
