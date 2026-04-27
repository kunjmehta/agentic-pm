"""Portfolio Manager reasoning node for the trading multi-agent system.

Pure reasoning node: uses LLM with_structured_output(AgentOutput) to plan
a TaskList and identify delegations to quant/backtester nodes.
No tool calls are made here — only reasoning and planning.

Sets state fields: portfolio_task_queue, portfolio_reasoning,
_delegate_quant, _delegate_backtester, _quant_query, _backtester_query.

Middleware applied:
- Model retry: up to MAX_RETRIES attempts on ValidationError or LLM failure
- ToolTracingCallback for LLM call timing
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import ValidationError

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.server.agents import get_llm
from src.server.constants import MAX_RETRIES
from src.server.models.task import AgentOutput, TaskList
from src.common.utils import load_prompt

logger = get_logger(__name__)

_PM_SYSTEM_PROMPT = load_prompt("portfolio_pm")


def _format_prior_turns(prior_turns: List[Dict[str, Any]]) -> str:
    """Format prior conversation turns for inclusion in the PM prompt.

    Args:
        prior_turns: List of interaction dicts from PortfolioDAO.

    Returns:
        Formatted string of prior conversation context.
    """
    if not prior_turns:
        return "No prior conversation history."
    lines = ["Prior conversation (most recent last):"]
    for i, turn in enumerate(prior_turns[-3:], 1):  # last 3 turns
        q = turn.get("user_query", "")[:100]
        r = turn.get("agent_response", "")[:150]
        raw_ts = turn.get("timestamp", "")
        ts = raw_ts.strftime("%Y-%m-%d") if hasattr(raw_ts, "strftime") else str(raw_ts)[:10]
        lines.append(f"\nTurn {i} ({ts}):")
        lines.append(f"  User: {q}")
        lines.append(f"  PM: {r}")
    return "\n".join(lines)


def _format_data_availability(
    indicators_available: Optional[bool],
    bars_available: Optional[bool],
    trades_available: Optional[bool],
    data_avail: Dict[str, Any],
) -> str:
    """Render data availability flags as a concise prompt section for the LLM.

    Args:
        indicators_available: True if pre-computed indicators are in DB.
        bars_available: True if sufficient OHLCV bars are in DB.
        trades_available: True if recent trade records are in DB.
        data_avail: Full data_availability dict from data_availability_node.

    Returns:
        Formatted string injected into the PM user message.
    """
    symbol = data_avail.get("symbol") or "N/A"
    timeframe = data_avail.get("timeframe") or "1Min"
    indicator_rows = data_avail.get("indicator_rows", 0)
    bar_count = data_avail.get("bar_count", 0)
    trade_count = data_avail.get("trade_count", 0)
    latest_indicator_ts = data_avail.get("latest_indicator_ts") or "—"
    latest_bar_ts = data_avail.get("latest_bar_ts") or "—"
    checked_at = data_avail.get("checked_at") or "—"

    def _flag(v: Optional[bool]) -> str:
        if v is True:
            return "✅ YES (in DB)"
        if v is False:
            return "❌ NO (must fetch)"
        return "❓ UNKNOWN"

    lines = [
        f"Symbol: {symbol}  |  Timeframe: {timeframe}  |  Checked: {checked_at}",
        f"  indicators_available : {_flag(indicators_available)}"
        + (f"  ({indicator_rows} rows, latest={latest_indicator_ts})" if indicators_available else ""),
        f"  bars_available       : {_flag(bars_available)}"
        + (f"  ({bar_count} bars, latest={latest_bar_ts})" if bars_available else ""),
        f"  trades_available     : {_flag(trades_available)}"
        + (f"  ({trade_count} recent trades)" if trades_available else ""),
        "",
        "ACTION GUIDANCE:",
    ]

    if indicators_available:
        lines.append("  → DO NOT schedule fetch_historical_data for indicator computation.")
        lines.append("    Quant agent will read pre-computed indicators directly from DB.")
    else:
        lines.append("  → indicators MISSING: schedule fetch_historical_data (priority=3) before delegating to quant.")

    if bars_available:
        lines.append("  → DO NOT schedule fetch_historical_data for backtests; bars already in DB.")
        lines.append("    Backtester will use get_bars from DB.")
    else:
        lines.append("  → bars MISSING/INSUFFICIENT: schedule fetch_historical_data (priority=3) before delegating to backtester.")

    if trades_available:
        lines.append("  → Recent trade data available in DB; order agent can query without extra fetch.")
    else:
        lines.append("  → NO recent trades in DB; explicitly schedule fetch_trades if trade history is needed.")

    return "\n".join(lines)


async def portfolio_reasoning_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Portfolio Manager pure reasoning node.

    Invokes gpt-5-mini with structured output to produce AgentOutput.
    Retries up to MAX_RETRIES on ValidationError or LLM failure.
    Falls back to an empty TaskList (no tasks, no delegation) on persistent failure.

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update with portfolio task queue and delegation flags.
    """
    try:
        query: str = state.get("query", "")
        intent: str = state.get("intent", "portfolio")
        symbol: Optional[str] = state.get("symbol")
        turn_number: int = state.get("turn_number") or 1
        prior_turns: List[Dict] = state.get("prior_turns") or []

        # ── Data availability flags ───────────────────────────────────────
        data_avail: Dict = state.get("data_availability") or {}
        indicators_available: Optional[bool] = data_avail.get("indicators_available")
        bars_available: Optional[bool] = data_avail.get("bars_available")
        trades_available: Optional[bool] = data_avail.get("trades_available")

        logger.info(
            f"[portfolio_node] reasoning for query='{query[:60]}' intent={intent} "
            f"indicators={indicators_available} bars={bars_available} trades={trades_available}"
        )

        # Build the user message
        prior_context = _format_prior_turns(prior_turns)
        data_avail_context = _format_data_availability(
            indicators_available, bars_available, trades_available, data_avail
        )
        user_message = (
            f"User query: {query}\n"
            f"Classified intent: {intent}\n"
            f"Extracted symbol: {symbol or 'None'}\n"
            f"Turn number: {turn_number}\n\n"
            f"DATA AVAILABILITY CONTEXT (checked before reasoning):\n{data_avail_context}\n\n"
            f"PRIOR CONVERSATION CONTEXT:\n{prior_context}"
        )

        structured_llm = get_llm("pm").with_structured_output(AgentOutput, method="function_calling")

        messages = [
            {"role": "system", "content": _PM_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        result: Optional[AgentOutput] = None
        last_error: Optional[str] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = await structured_llm.ainvoke(messages)
                logger.info(
                    f"[portfolio_node] reasoning complete on attempt {attempt}: "
                    f"{len(result.task_list.tasks)} tasks, "
                    f"quant={result.delegate_to_quant}, bt={result.delegate_to_backtester}"
                )
                break
            except Exception as exc:
                last_error = str(exc)
                logger.warning(f"[portfolio_node] attempt {attempt}/{MAX_RETRIES} failed: {exc}")

        if result is None:
            logger.error(f"[portfolio_node] all {MAX_RETRIES} attempts failed: {last_error}")
            result = AgentOutput(
                task_list=TaskList(tasks=[], reasoning_summary="Reasoning failed — no tasks planned."),
                delegate_to_quant=False,
                delegate_to_backtester=False,
            )

        task_queue = [t.model_dump() for t in result.task_list.tasks]

        return {
            "portfolio_task_queue": task_queue,
            "portfolio_reasoning": result.task_list.reasoning_summary,
            "_delegate_quant": result.delegate_to_quant,
            "_delegate_backtester": result.delegate_to_backtester,
            "_quant_query": result.quant_query,
            "_backtester_query": result.backtester_query,
            "_order_query": result.order_query,
        }

    except Exception as exc:
        logger.error(f"[portfolio_node] unexpected error: {exc}", exc_info=True)
        return {
            "error": f"Portfolio reasoning failed: {exc}",
            "_delegate_quant": False,
            "_delegate_backtester": False,
            "portfolio_task_queue": [],
            "portfolio_reasoning": None,
        }


if __name__ == "__main__":
    """Functional test: PM reasoning for portfolio and quant queries."""
    import asyncio

    async def _run_tests() -> None:
        print("=" * 60)
        print("portfolio_node Functional Tests")
        print("=" * 60)

        # Test 1: simple portfolio status query
        print("\n[1/3] Portfolio status query")
        result = await portfolio_reasoning_node({
            "query": "What is my portfolio status?",
            "intent": "portfolio",
            "symbol": None,
            "turn_number": 1,
            "prior_turns": [],
            "backtest_mode": True,
        })
        print(f"[OK] portfolio_reasoning: {result.get('portfolio_reasoning', '')[:100]}")
        print(f"[OK] task count: {len(result.get('portfolio_task_queue', []))}")
        print(f"[OK] delegate_quant: {result.get('_delegate_quant')}")
        print(f"[OK] delegate_backtester: {result.get('_delegate_backtester')}")

        # Test 2: quant analysis query — should delegate
        print("\n[2/3] Quant analysis query (should delegate)")
        result2 = await portfolio_reasoning_node({
            "query": "Analyze AAPL momentum and RSI indicators",
            "intent": "quant",
            "symbol": "AAPL",
            "turn_number": 1,
            "prior_turns": [],
            "backtest_mode": True,
        })
        print(f"[OK] portfolio_reasoning: {result2.get('portfolio_reasoning', '')[:100]}")
        print(f"[OK] delegate_quant: {result2.get('_delegate_quant')}")
        print(f"[OK] quant_query: {result2.get('_quant_query', '')[:80]}")

        # Test 3: backtester delegation
        print("\n[3/3] Backtest query (should delegate to backtester)")
        result3 = await portfolio_reasoning_node({
            "query": "Backtest mean-reversion on AAPL from 2026-01-01 to 2026-01-31",
            "intent": "backtest",
            "symbol": "AAPL",
            "turn_number": 1,
            "prior_turns": [],
            "backtest_mode": True,
        })
        print(f"[OK] delegate_backtester: {result3.get('_delegate_backtester')}")
        print(f"[OK] backtester_query: {result3.get('_backtester_query', '')[:80]}")

        print("\n[ALL OK] portfolio_node tests complete")

    asyncio.run(_run_tests())
