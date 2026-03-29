"""Backtester node for the deterministic LangGraph agent.

Calls skill core functions directly (no subprocess). Dispatches to one of
three sub-workflows based on bt_workflow state:
  A — backtest_strategy_core (backtest-strategy/strategy.py)
  B — snapshot_worth_core (snapshot-worth/worth.py)
  C — swap_positions_core (swap-positions/swap.py)

Each sub-workflow calls the core function once, then uses LLM to interpret
the performance metrics using AGENTS.MD thresholds.

Sets state fields: backtest_result, backtest_run_id.
"""

import json
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import importlib.util

from src.common.utils import get_logger

logger = get_logger(__name__)


def _to_native(obj: Any) -> Any:
    """Recursively convert numpy/pandas types to Python native types.

    LangGraph's MemorySaver uses msgpack which cannot serialize numpy scalars.

    Args:
        obj: Any value that may contain numpy types.

    Returns:
        Object with all numpy scalars replaced by Python primitives.
    """
    try:
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
    except ImportError:
        pass

    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_to_native(v) for v in obj)
    return obj


# ── Skill modules (folder names use hyphens — load via importlib) ─────────────
_BT_SKILLS_DIR = project_root / "src" / "agentic" / "agents" / "backtester" / "skills"


def _load_bt_skill(folder: str, filename: str):
    """Load a backtester skill module from a hyphenated folder.

    Args:
        folder: Skill folder name (may contain hyphens).
        filename: Python script file name.

    Returns:
        Loaded module object.
    """
    path = _BT_SKILLS_DIR / folder / filename
    spec = importlib.util.spec_from_file_location(
        f"bt_skill_{folder.replace('-', '_')}", path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    _strategy_mod = _load_bt_skill("backtest-strategy", "strategy.py")
    backtest_strategy_core = _strategy_mod.backtest_strategy_core
except Exception as _e:
    logger.warning(f"[backtester_node] strategy module load failed: {_e}")
    backtest_strategy_core = None

try:
    _worth_mod = _load_bt_skill("snapshot-worth", "worth.py")
    snapshot_worth_core = _worth_mod.snapshot_worth_core
except Exception as _e:
    logger.warning(f"[backtester_node] snapshot-worth module load failed: {_e}")
    snapshot_worth_core = None

try:
    _swap_mod = _load_bt_skill("swap-positions", "swap.py")
    swap_positions_core = _swap_mod.swap_positions_core
except Exception as _e:
    logger.warning(f"[backtester_node] swap-positions module load failed: {_e}")
    swap_positions_core = None


def _extract_dates(query: str) -> tuple[str, str]:
    """Extract start/end dates from query with sensible defaults.

    Args:
        query: Raw user query string.

    Returns:
        Tuple (start_date, end_date) as YYYY-MM-DD strings.
    """
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", query)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if len(dates) >= 2:
        return dates[0], dates[1]
    if len(dates) == 1:
        return dates[0], today
    start = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    return start, today


def _extract_strategy(query: str) -> str:
    """Extract strategy name from query, defaulting to mean-reversion.

    Args:
        query: Raw user query string.

    Returns:
        Strategy name string.
    """
    query_lower = query.lower()
    if "momentum" in query_lower:
        return "momentum"
    if "value" in query_lower:
        return "value"
    if "buy and hold" in query_lower or "buy-and-hold" in query_lower:
        return "buy-and-hold"
    return "mean-reversion"


def _interpret_metrics(raw_result: dict, query: str) -> str:
    """LLM interpretation of backtest performance metrics.

    Uses thresholds from AGENTS.MD:
    - Sharpe >2 = excellent, 1-2 = promising, <0 = not recommended
    - Drawdown <-20% = dangerous
    - Win rate >60% = good, >70% = excellent

    Args:
        raw_result: Parsed result dict from skill core function.
        query: Original user query for context.

    Returns:
        Human-readable interpretation string.
    """
    try:
        from langchain_openai import ChatOpenAI

        from src.common.utils import secrets
        llm = ChatOpenAI(model="gpt-5-mini", temperature=0.1, api_key=secrets.get("openai.api_key"))
        system_prompt = """You are a quantitative analyst interpreting backtest results.

Use these thresholds (from Portfolio Manager AGENTS.MD):
- Sharpe: <0 = NOT RECOMMENDED | 0-1 = NEEDS IMPROVEMENT | 1-2 = PROMISING | >2 = EXCELLENT
- Max Drawdown: 0 to -5% = CONSERVATIVE | -5% to -10% = ACCEPTABLE | -10% to -20% = RISKY | >-20% = DANGEROUS
- Win Rate: <40% = POOR | 40-60% = AVERAGE | >60% = GOOD | >70% = EXCELLENT
- Profit Factor: <1.0 = UNPROFITABLE | 1.0-1.5 = MARGINAL | 1.5-2.0 = GOOD | >2.0 = EXCELLENT

Recommendation framework:
- Sharpe >2 AND drawdown > -10%: STRONG CANDIDATE
- Sharpe >1 AND drawdown > -15%: CONSIDER with position sizing
- Sharpe >0 AND drawdown > -20%: PROFITABLE but risky
- Otherwise: NOT RECOMMENDED

Provide: metrics summary, recommendation, and 2-3 risk factors."""

        response = llm.invoke([
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"User query: {query}\n\n"
                    f"Results:\n{json.dumps(raw_result, indent=2, default=str)}"
                ),
            },
        ])
        return response.content

    except Exception as exc:
        logger.warning(f"[backtester_node] LLM interpretation failed: {exc}")
        # Graceful degradation — format metrics as plain text
        lines = ["**Backtest Results**\n"]
        for k, v in raw_result.items():
            if not isinstance(v, (dict, list)):
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)


# ── Workflow implementations ──────────────────────────────────────────────────

def _workflow_a(symbol: str, query: str) -> dict:
    """Workflow A — Strategy backtest via backtest_strategy_core.

    Args:
        symbol: Stock ticker.
        query: Raw user query for date/strategy extraction.

    Returns:
        Dict with backtest result and interpretation.
    """
    start_date, end_date = _extract_dates(query)
    strategy = _extract_strategy(query)

    logger.info(
        f"[backtester_node] workflow A: {symbol} {strategy} "
        f"{start_date} → {end_date}"
    )

    if not backtest_strategy_core:
        return {"status": "error", "error": "backtest_strategy_core skill not available"}
    try:
        result = backtest_strategy_core(
            ticker=symbol,
            start_date=start_date,
            end_date=end_date,
            strategy=strategy,
            initial_capital=100000.0,
            save_to_db=True,
        )
        result["interpretation"] = _interpret_metrics(result, query)
        return result
    except Exception as exc:
        logger.error(f"[backtester_node] workflow A failed: {exc}")
        return {"status": "error", "error": str(exc)}


def _workflow_b(query: str) -> dict:
    """Workflow B — Snapshot worth via snapshot_worth_core.

    Args:
        query: Raw user query for date extraction.

    Returns:
        Dict with valuation results and interpretation.
    """
    snapshot_date, end_date = _extract_dates(query)

    logger.info(
        f"[backtester_node] workflow B: snapshot {snapshot_date} → {end_date}"
    )

    if not snapshot_worth_core:
        return {"status": "error", "error": "snapshot_worth_core skill not available"}
    try:
        result = snapshot_worth_core(
            snapshot_date=snapshot_date,
            end_date=end_date,
        )
        result["interpretation"] = _interpret_metrics(result, query)
        return result
    except Exception as exc:
        logger.error(f"[backtester_node] workflow B failed: {exc}")
        return {"status": "error", "error": str(exc)}


def _workflow_c(query: str) -> dict:
    """Workflow C — Swap positions via swap_positions_core.

    Args:
        query: Raw user query for dates and swap details.

    Returns:
        Dict with swap comparison results.
    """
    snapshot_date, end_date = _extract_dates(query)

    # Extract swap pairs: "swap[ped] [N] TICKER for/to TICKER"
    swap_match = re.search(
        r"swap\w*\s+(?:(\d+)\s+)?([A-Z]{1,5})\s+(?:for|to|with)\s+([A-Z]{1,5})",
        query,
        re.IGNORECASE,
    )

    if swap_match:
        qty = int(swap_match.group(1) or 0) or 100
        from_ticker = swap_match.group(2).upper()
        to_ticker = swap_match.group(3).upper()
        tickers = {from_ticker: {"swap_to": to_ticker, "quantity": qty}}
    else:
        logger.warning("[backtester_node] workflow C: no swap pattern found, using empty swaps")
        tickers = {}

    logger.info(
        f"[backtester_node] workflow C: snapshot {snapshot_date} → {end_date} "
        f"swaps={tickers}"
    )

    if not swap_positions_core:
        return {"status": "error", "error": "swap_positions_core skill not available"}
    try:
        result = swap_positions_core(
            snapshot_date=snapshot_date,
            end_date=end_date,
            tickers=tickers,
        )
        result["interpretation"] = _interpret_metrics(result, query)
        return result
    except Exception as exc:
        logger.error(f"[backtester_node] workflow C failed: {exc}")
        return {"status": "error", "error": str(exc)}


def _log_interaction(
    thread_id: str,
    query: str,
    response: str,
    node_name: str = "backtester_node",
) -> None:
    """Log node execution to portfolio DB for observability.

    Args:
        thread_id: Conversation thread UUID.
        query: Original user query.
        response: Node output summary string.
        node_name: Name of this graph node.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        dao.save_interaction(
            thread_id=thread_id,
            agent_name=node_name,
            user_query=query,
            tool_sequence=[{"tool": "backtest_strategy_core", "node": node_name}],
            agent_response=response,
            model_used="langgraph",
        )
        dao.close()
    except Exception as exc:
        logger.warning(f"[{node_name}] interaction log failed: {exc}")


def backtester_node(state: dict) -> dict:
    """Dispatch to the appropriate backtest sub-workflow.

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update with backtest_result and backtest_run_id.
    """
    bt_workflow: str = state.get("bt_workflow") or "A"
    symbol: Optional[str] = state.get("symbol")
    query: str = state.get("query", "")
    thread_id: str = state.get("thread_id", "unknown")

    logger.info(f"[backtester_node] workflow='{bt_workflow}' symbol='{symbol}'")

    run_id = str(uuid.uuid4())

    if bt_workflow == "A":
        if not symbol:
            result = {
                "status": "error",
                "error": "No ticker symbol found. Specify a stock for backtesting.",
            }
        else:
            result = _workflow_a(symbol, query)

    elif bt_workflow == "B":
        result = _workflow_b(query)

    elif bt_workflow == "C":
        result = _workflow_c(query)

    else:
        result = {"status": "error", "error": f"Unknown bt_workflow: {bt_workflow}"}

    native_result = _to_native(result)

    # Log interaction for observability
    response_summary = result.get("interpretation") or result.get("status", "completed")
    _log_interaction(thread_id, query, str(response_summary)[:500])

    return {
        "backtest_result": native_result,
        "backtest_run_id": run_id,
    }


if __name__ == "__main__":
    """Functional test: all three workflows."""
    print("=" * 60)
    print("Backtester Node Functional Tests")
    print("=" * 60)

    print("\n[1/3] Workflow A — strategy backtest (AAPL)")
    result = backtester_node({
        "bt_workflow": "A",
        "symbol": "AAPL",
        "backtest_mode": True,
        "query": "Backtest mean-reversion on AAPL from 2026-01-01 to 2026-01-31",
    })
    print(f"[OK] keys: {list(result.keys())}")
    assert "backtest_result" in result and "backtest_run_id" in result
    print(f"     status: {result['backtest_result'].get('status', 'N/A')}")

    print("\n[2/3] Workflow B — snapshot worth")
    result = backtester_node({
        "bt_workflow": "B",
        "backtest_mode": True,
        "query": "What would my 2026-01-15 portfolio be worth today?",
    })
    print(f"[OK] keys: {list(result.keys())}")
    print(f"     result keys: {list(result['backtest_result'].keys())[:5]}")

    print("\n[3/3] Workflow C — swap positions")
    result = backtester_node({
        "bt_workflow": "C",
        "backtest_mode": True,
        "query": "What if I swapped 50 AAPL for TSLA on 2026-01-15?",
    })
    print(f"[OK] keys: {list(result.keys())}")
    print(f"     result keys: {list(result['backtest_result'].keys())[:5]}")

    print("\n" + "=" * 60)
    print("Backtester node tests complete!")
