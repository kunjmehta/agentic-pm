"""Portfolio Manager synthesis node for the deterministic LangGraph agent.

Receives all populated state fields and synthesizes a final_response
in PM format using an LLM. No tool calls — pure synthesis.

Also handles short-circuit cases where routing_error is already set
by the guard nodes (returns final_response directly without LLM call).
"""

import json
import sys
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)


def _log_synthesizer_interaction(state: dict, final_response: str) -> None:
    """Log the full conversation turn to agent_interactions for observability.

    This is the top-level interaction record capturing the complete query→response
    arc, complementing the per-node logs from portfolio_node, quant_node, etc.

    Args:
        state: Final GraphState dict.
        final_response: Synthesized response string.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO

        thread_id: str = state.get("thread_id", "unknown")
        query: str = state.get("query", "")
        intent: str = state.get("intent", "unknown")
        symbol = state.get("symbol")

        dao = PortfolioDAO()
        dao.save_interaction(
            thread_id=thread_id,
            agent_name="synthesizer",
            user_query=query,
            tool_sequence=[
                {"intent": intent, "symbol": symbol, "node": "synthesizer"}
            ],
            agent_response=final_response[:1000],
            model_used="gpt-5-mini",
        )
        dao.close()
        logger.info(f"[synthesizer] interaction logged for thread={thread_id}")
    except Exception as exc:
        logger.warning(f"[synthesizer] interaction log failed (non-critical): {exc}")


def _format_section(title: str, content: Any) -> str:
    """Format a state section for the LLM prompt.

    Args:
        title: Section heading.
        content: Data to serialize.

    Returns:
        Formatted string section.
    """
    if content is None:
        return ""
    if isinstance(content, dict):
        return f"\n### {title}\n```json\n{json.dumps(content, indent=2, default=str)}\n```\n"
    return f"\n### {title}\n{content}\n"


def synthesizer(state: dict) -> dict:
    """Synthesize final PM response from all collected state data.

    If routing_error is set (guard short-circuit), returns the
    pre-built final_response without an LLM call.

    Args:
        state: Current GraphState dict with all populated fields.

    Returns:
        Partial state update with final_response key.
    """
    # ── Short-circuit: guard already set a response ───────────────────────────
    if state.get("routing_error") and state.get("final_response"):
        logger.info(
            f"[synthesizer] short-circuit: routing_error='{state['routing_error'][:60]}'"
        )
        return {}  # final_response already in state from guard

    logger.info(f"[synthesizer] intent='{state.get('intent')}' building synthesis prompt")

    # ── Build prompt sections from non-None state fields ─────────────────────
    sections = []

    intent = state.get("intent", "unknown")
    symbol = state.get("symbol")
    query = state.get("query", "")

    if state.get("portfolio_status"):
        sections.append(_format_section("Portfolio Status", state["portfolio_status"]))

    if state.get("positions_summary"):
        sections.append(_format_section("Positions Summary", state["positions_summary"]))

    if state.get("health_check"):
        sections.append(_format_section("Health Check", state["health_check"]))

    if state.get("data_availability"):
        sections.append(_format_section("Data Availability", state["data_availability"]))

    if state.get("quant_analysis"):
        sections.append(_format_section("Technical Analysis", state["quant_analysis"]))

    if state.get("backtest_result"):
        sections.append(_format_section("Backtest Results", state["backtest_result"]))

    if state.get("error"):
        sections.append(_format_section("Errors", state["error"]))

    collected_data = "".join(sections) if sections else "No data collected."

    # ── LLM synthesis ────────────────────────────────────────────────────────
    final_response = _call_llm(query, intent, symbol, collected_data)

    _log_synthesizer_interaction(state, final_response)

    return {"final_response": final_response}


def _call_llm(query: str, intent: str, symbol: str | None, collected_data: str) -> str:
    """Call LLM to synthesize the final PM response.

    Args:
        query: Original user query.
        intent: Classified intent.
        symbol: Extracted ticker or None.
        collected_data: Formatted string of all collected state data.

    Returns:
        Synthesized response string.
    """
    try:
        from langchain_openai import ChatOpenAI

        from src.common.utils import secrets
        llm = ChatOpenAI(model="gpt-5-mini", temperature=0.2, api_key=secrets.get("openai.api_key"))

        system_prompt = """You are a Portfolio Manager AI. Given the collected data, output only a direct final conclusion or decision.

Rules:
- One short paragraph maximum
- Lead with the action/decision (e.g. "Hold AAPL", "Backtest shows X% return, not recommended", "Portfolio is healthy at $X equity")
- Include only the most critical number(s) from the data
- No headers, no bullet points, no formatting — plain prose only
- If data is missing or errored, say so in one sentence"""

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"User query: {query}\n"
                    f"Intent: {intent}\n"
                    f"Symbol: {symbol or 'N/A'}\n\n"
                    f"Collected data:\n{collected_data}"
                ),
            },
        ]

        response = llm.invoke(messages)
        return response.content

    except Exception as exc:
        logger.warning(f"[synthesizer] LLM call failed: {exc}")
        # Graceful degradation: return raw data summary
        return f"Analysis complete (synthesis unavailable). Intent: {intent}. {collected_data[:300]}"


if __name__ == "__main__":
    """Functional test: synthesizer with mock state data."""
    print("=" * 60)
    print("Synthesizer Node Functional Tests")
    print("=" * 60)

    # Test 1: short-circuit when routing_error is set
    print("\n[1/3] short-circuit on routing_error")
    result = synthesizer({
        "routing_error": "Market is CLOSED",
        "final_response": "⏰ Market Hours Guard — Market is closed.",
        "query": "Analyze AAPL",
        "intent": "quant",
    })
    assert result == {}, f"Expected empty dict on short-circuit, got: {result}"
    print("[OK] short-circuit returns empty dict (final_response already in state)")

    # Test 2: portfolio synthesis with mock data
    print("\n[2/3] portfolio intent synthesis")
    mock_state = {
        "query": "What is my portfolio status?",
        "intent": "portfolio",
        "symbol": None,
        "routing_error": None,
        "portfolio_status": {
            "equity": 100000.0,
            "cash": 50000.0,
            "buying_power": 100000.0,
            "long_positions": 2,
            "short_positions": 0,
        },
        "positions_summary": {
            "count": 2,
            "total_market_value": 50000.0,
            "total_unrealized_pl": 2500.0,
        },
        "health_check": {
            "health_status": "healthy",
            "violations": [],
            "warnings": [],
        },
    }
    result = synthesizer(mock_state)
    assert "final_response" in result
    print(f"[OK] final_response generated ({len(result['final_response'])} chars)")
    print(f"     preview: {result['final_response'][:100]}...")

    # Test 3: no data — graceful degradation
    print("\n[3/3] no data (graceful degradation)")
    result = synthesizer({
        "query": "Analyze MSFT",
        "intent": "quant",
        "symbol": "MSFT",
        "routing_error": None,
    })
    assert "final_response" in result
    print(f"[OK] degraded response ({len(result['final_response'])} chars)")

    print("\n" + "=" * 60)
    print("Synthesizer tests complete!")
