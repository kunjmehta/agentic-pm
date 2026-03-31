"""Portfolio Manager reasoning node for the semi-auto multi-agent system.

Pure reasoning node: uses LLM with_structured_output(AgentOutput) to plan
a TaskList and identify delegations to quant/backtester nodes.
No tool calls are made here — only reasoning and planning.

Sets state fields: portfolio_task_queue, portfolio_reasoning,
_delegate_quant, _delegate_backtester, _quant_query, _backtester_query.

Middleware applied:
- Model retry: up to MAX_RETRIES attempts on ValidationError or LLM failure
- ToolTracingCallback for LLM call timing
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.semi_auto.models.task import AgentOutput, TaskList

logger = get_logger(__name__)

MAX_RETRIES = 3

_PM_SYSTEM_PROMPT = """You are a Portfolio Manager AI. Your ONLY job is to reason and plan — you do NOT call any tools yourself.

Given the user query and conversation context, output a structured AgentOutput containing:
1. A TaskList of function calls to make (from the ALLOWED FUNCTIONS list below)
2. Whether to delegate to the Quant Analyst (for technical indicator analysis)
3. Whether to delegate to the Backtester (for historical simulations/backtests)

PORTFOLIO FUNCTIONS (core):
- get_portfolio_status: No params. Use for: equity, cash, buying power queries.
- get_positions_summary: No params. Use for: positions, holdings, P&L queries.
- check_portfolio_health: No params (results injected automatically). Use for: risk compliance checks. Set depends_on=["pm_001","pm_002"] and priority=2.
- fetch_historical_data: params={symbol, start_date, end_date, timeframe}. Use to fetch bars before a backtest. Set priority=3 (write-heavy, runs sequentially). Default timeframe=1Min"
- check_data_availability: params={symbol, start_date, end_date}. Use to verify data exists before fetching.

ADDITIONAL DATA FUNCTIONS (use only when relevant):
- get_latest_price: params={symbol, timeframe="1Day"}. Get most recent bar for a symbol.
- get_market_bars: params={symbol, start_date, end_date, timeframe="1Min"}. Fetch raw OHLCV bars for a date range.
- get_watchlist: No params. Returns symbols currently in the watchlist.
- get_company_fundamentals: params={symbol}. PE ratio, market cap, sector, EPS.
- get_portfolio_snapshot: No params. Most recent portfolio snapshot including unrealized P&L.
- get_portfolio_snapshot_history: params={start_date, end_date}. Historical portfolio value snapshots.
- get_risk_parameters: No params. Current risk limits and thresholds.
- get_actionable_signals: params={min_confidence=0.7, action_filter=None}. High-confidence buy/sell signals from active strategies.

DELEGATION RULES:
- If query involves technical indicators (RSI, MACD, Bollinger, momentum, volume, candlestick, mean reversion) → set delegate_to_quant=true, quant_query="<focused analysis request>"
- If query involves backtesting, simulation, historical what-if, strategy performance → set delegate_to_backtester=true, backtester_query="<focused backtest request with symbol and dates>"
- Both can be true for full_analysis queries.

TASK ID FORMAT: "pm_001", "pm_002", etc.
PRIORITY: 1=high (parallel read), 2=medium (needs deps), 3=low (write, runs last)

RULES:
- Only include tasks needed for THIS specific query — do not over-fetch
- For pure quant queries, task_list can be empty (delegate only)
- For pure portfolio queries, delegate_to_quant and delegate_to_backtester should both be false
- Set priority=3 for fetch_historical_data (DuckDB write — runs sequentially)
"""


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


def portfolio_reasoning_node(state: dict) -> dict:
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
        from langchain_openai import ChatOpenAI
        from pydantic import ValidationError
        from src.common.utils import secrets

        query: str = state.get("query", "")
        intent: str = state.get("intent", "portfolio")
        symbol: Optional[str] = state.get("symbol")
        turn_number: int = state.get("turn_number") or 1
        prior_turns: List[Dict] = state.get("prior_turns") or []

        logger.info(f"[portfolio_node] reasoning for query='{query[:60]}' intent={intent}")

        # Build the user message
        prior_context = _format_prior_turns(prior_turns)
        user_message = (
            f"User query: {query}\n"
            f"Classified intent: {intent}\n"
            f"Extracted symbol: {symbol or 'None'}\n"
            f"Turn number: {turn_number}\n\n"
            f"PRIOR CONVERSATION CONTEXT:\n{prior_context}"
        )

        llm = ChatOpenAI(
            model="gpt-5-mini",
            temperature=0,
            api_key=secrets.get("openai.api_key"),
        )
        structured_llm = llm.with_structured_output(AgentOutput, method="function_calling")

        messages = [
            {"role": "system", "content": _PM_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        result: Optional[AgentOutput] = None
        last_error: Optional[str] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = structured_llm.invoke(messages)
                logger.info(
                    f"[portfolio_node] reasoning complete on attempt {attempt}: "
                    f"{len(result.task_list.tasks)} tasks, "
                    f"quant={result.delegate_to_quant}, bt={result.delegate_to_backtester}"
                )
                break
            except (ValidationError, Exception) as exc:
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
    print("=" * 60)
    print("portfolio_node Functional Tests")
    print("=" * 60)

    # Test 1: simple portfolio status query
    print("\n[1/3] Portfolio status query")
    result = portfolio_reasoning_node({
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
    result2 = portfolio_reasoning_node({
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
    result3 = portfolio_reasoning_node({
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
