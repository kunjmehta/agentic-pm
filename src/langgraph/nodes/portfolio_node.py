"""Portfolio data collection node for the deterministic LangGraph agent.

No LLM calls — pure data collection via the portfolio skill functions.
Populates: portfolio_status, positions_summary, health_check,
           data_availability, data_fetched.

Caching: results are stored in state; the graph does not re-invoke this
node within a single execution, so a per-request run is sufficient.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.agentic.agents.portfolio.skills.portfoliostatus.status import (
    get_portfolio_status_core,
    get_positions_summary_core,
)
from src.agentic.agents.portfolio.skills.health.health import check_portfolio_health_core
from src.agentic.agents.portfolio.skills.datamanagement.data import (
    check_data_availability_core,
    fetch_historical_data_core,
)
from src.common.utils import get_logger

logger = get_logger(__name__)


def _log_portfolio_interaction(
    thread_id: str,
    query: str,
    portfolio_status: dict,
    intent: str,
) -> None:
    """Log portfolio_node execution to agent_interactions for observability.

    Args:
        thread_id: Conversation thread UUID.
        query: Original user query.
        portfolio_status: Fetched portfolio status dict.
        intent: Classified intent.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO

        equity = portfolio_status.get("equity", "N/A")
        response_summary = f"Portfolio status fetched: equity={equity}, intent={intent}"

        dao = PortfolioDAO()
        dao.save_interaction(
            thread_id=thread_id,
            agent_name="portfolio_node",
            user_query=query,
            tool_sequence=[
                {"tool": "get_portfolio_status_core", "node": "portfolio_node"},
                {"tool": "get_positions_summary_core", "node": "portfolio_node"},
            ],
            agent_response=response_summary,
            model_used="langgraph",
        )
        dao.close()
        logger.info(f"[portfolio_node] interaction logged for thread={thread_id}")
    except Exception as exc:
        logger.warning(f"[portfolio_node] interaction log failed (non-critical): {exc}")


def portfolio_node(state: dict) -> dict:
    """Collect portfolio data for downstream nodes.

    Behavior varies by intent:
    - All intents: fetch portfolio status + positions summary
    - "portfolio" / "full_analysis": also run health check
    - "backtest" / "full_analysis": also check data availability and
      fetch historical data when needed

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update with portfolio data fields.
    """
    intent: str = state.get("intent", "portfolio")
    symbol: Optional[str] = state.get("symbol")
    query: str = state.get("query", "")
    thread_id: str = state.get("thread_id", "unknown")

    logger.info(f"[portfolio_node] intent='{intent}' symbol='{symbol}'")

    updates: dict = {}

    # ── Always: portfolio status + positions ─────────────────────────────────
    try:
        portfolio_status = get_portfolio_status_core()
        updates["portfolio_status"] = portfolio_status
        logger.info(
            f"[portfolio_node] portfolio_status: equity={portfolio_status.get('equity')}"
        )
    except Exception as exc:
        logger.warning(f"[portfolio_node] get_portfolio_status_core failed: {exc}")
        updates["portfolio_status"] = {"error": str(exc)}

    try:
        positions_summary = get_positions_summary_core()
        updates["positions_summary"] = positions_summary
        logger.info(
            f"[portfolio_node] positions: count={positions_summary.get('count')}"
        )
    except Exception as exc:
        logger.warning(f"[portfolio_node] get_positions_summary_core failed: {exc}")
        updates["positions_summary"] = {"error": str(exc)}

    # ── Health check: portfolio and full_analysis intents ───────────────────
    if intent in ("portfolio", "full_analysis"):
        try:
            port_status = updates.get("portfolio_status", {})
            pos_summary = updates.get("positions_summary", {})
            health = check_portfolio_health_core(port_status, pos_summary)
            updates["health_check"] = health
            logger.info(
                f"[portfolio_node] health_status='{health.get('health_status')}'"
            )
        except Exception as exc:
            logger.warning(f"[portfolio_node] check_portfolio_health_core failed: {exc}")
            updates["health_check"] = {"error": str(exc)}

    # ── Data availability: backtest and full_analysis intents ────────────────
    if intent in ("backtest", "full_analysis") and symbol:
        start_date, end_date = _extract_date_range(query)
        try:
            availability = check_data_availability_core(symbol, start_date, end_date)
            updates["data_availability"] = availability
            logger.info(
                f"[portfolio_node] data_availability for {symbol}: "
                f"available={availability.get('available')}"
            )

            # Fetch if missing or partial
            if availability.get("available") in (False, "partial"):
                logger.info(
                    f"[portfolio_node] fetching historical data for {symbol} "
                    f"{start_date} → {end_date}"
                )
                fetch_result = fetch_historical_data_core(symbol, start_date, end_date)
                updates["data_fetched"] = fetch_result.get("status") == "success"
                logger.info(
                    f"[portfolio_node] fetch_result status='{fetch_result.get('status')}'"
                )
            else:
                updates["data_fetched"] = True

        except Exception as exc:
            logger.warning(
                f"[portfolio_node] data availability check failed: {exc}"
            )
            updates["data_availability"] = {"error": str(exc)}
            updates["data_fetched"] = False

    _log_portfolio_interaction(
        thread_id=thread_id,
        query=query,
        portfolio_status=updates.get("portfolio_status", {}),
        intent=intent,
    )

    return updates


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_date_range(query: str) -> tuple[str, str]:
    """Extract start and end dates from query, or return sensible defaults.

    Looks for YYYY-MM-DD patterns in the query text.

    Args:
        query: Raw user query string.

    Returns:
        Tuple (start_date, end_date) as YYYY-MM-DD strings.
    """
    import re

    dates = re.findall(r"\d{4}-\d{2}-\d{2}", query)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if len(dates) >= 2:
        return dates[0], dates[1]
    if len(dates) == 1:
        return dates[0], today

    # Default: last 30 days
    from datetime import timedelta
    start = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    return start, today


if __name__ == "__main__":
    """Functional test: invoke portfolio_node in backtest mode."""
    import json

    print("=" * 60)
    print("Portfolio Node Functional Tests")
    print("=" * 60)

    # Test 1: portfolio intent
    print("\n[1/3] portfolio intent")
    result = portfolio_node({"intent": "portfolio", "backtest_mode": True, "query": ""})
    print(f"[OK] keys returned: {list(result.keys())}")
    assert "portfolio_status" in result
    assert "positions_summary" in result
    assert "health_check" in result

    # Test 2: quant intent (no health check, no data fetch)
    print("\n[2/3] quant intent — data_availability should NOT be set")
    result = portfolio_node({
        "intent": "quant", "backtest_mode": True, "query": "Analyze AAPL",
        "symbol": "AAPL"
    })
    assert "data_availability" not in result or result.get("data_availability") is None
    print("[OK] data_availability not fetched for quant intent")

    # Test 3: backtest intent with symbol
    print("\n[3/3] backtest intent with symbol AAPL")
    result = portfolio_node({
        "intent": "backtest",
        "backtest_mode": True,
        "query": "Backtest AAPL from 2026-01-01 to 2026-01-31",
        "symbol": "AAPL",
    })
    print(f"[OK] keys returned: {list(result.keys())}")
    print(
        f"     data_availability={result.get('data_availability', {}).get('available', 'N/A')}"
    )
    assert "data_availability" in result

    print("\n" + "=" * 60)
    print("Portfolio node tests complete!")
