"""Agent Delegation Skill - Delegate tasks to specialized agents."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import argparse
from datetime import datetime
from typing import Dict

from src.common.utils import get_logger
from src.common.core.thread_context import get_bt_thread_id, get_qa_thread_id

logger = get_logger(__name__)


def delegate_to_quant_analyst_core(query: str, thread_id: str = "default") -> Dict:
    """Delegate technical analysis to Quant Analyst.

    Thread ID is derived from the active client context (qa-<client_uuid>)
    to preserve conversation continuity across the PM -> Quant boundary.

    Args:
        query: Analysis query
        thread_id: Ignored — resolved from ContextVar for consistency

    Returns:
        Dict with analysis response or error
    """
    from src.agentic.agents.quant.analyst import QuantAnalyst

    # Always use the context-derived thread ID for continuity
    qa_thread_id = get_qa_thread_id()
    logger.info(f"[DELEGATION] PM -> Quant Analyst | thread: {qa_thread_id}")

    try:
        quant = QuantAnalyst(backtest_mode=True)
        result = quant.invoke(query, thread_id=qa_thread_id, apply_middleware=True)

        if "error" in result:
            return {
                "status": "error",
                "error": result["error"],
                "delegated_to": "quant_analyst",
                "thread_id": qa_thread_id,
                "timestamp": result.get("timestamp", datetime.now().isoformat())
            }

        return {
            "status": "success",
            "response": result.get("response", str(result)),
            "delegated_to": "quant_analyst",
            "thread_id": qa_thread_id,
            "timestamp": result.get("timestamp", datetime.now().isoformat())
        }

    except Exception as e:
        logger.error(f"Quant Analyst delegation failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "delegated_to": "quant_analyst",
            "thread_id": qa_thread_id,
            "timestamp": datetime.now().isoformat()
        }


def delegate_to_backtester_core(
    symbol: str,
    strategy: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1Min",
    initial_capital: float = 100000.0,
    thread_id: str = "default"
) -> Dict:
    """Delegate backtesting to Backtester agent with structured parameters.

    Builds an unambiguous machine-generated command so the backtester executes
    immediately without asking clarifying questions.

    Thread ID is derived from the active client context (bt-<client_uuid>)
    to preserve conversation continuity across the PM -> Backtester boundary.

    Args:
        symbol: Stock ticker (e.g. 'AAPL')
        strategy: Strategy name — 'buy-and-hold', 'mean-reversion', or 'momentum'
        start_date: Start date YYYY-MM-DD (data already verified as available)
        end_date: End date YYYY-MM-DD
        timeframe: Bar timeframe (default: '1Min')
        initial_capital: Starting capital (default: 100000)
        thread_id: Ignored — resolved from ContextVar for consistency

    Returns:
        Dict with backtest results or error
    """
    from src.agentic.agents.backtester.backtester import Backtester

    bt_thread_id = get_bt_thread_id()
    logger.info(f"[DELEGATION] PM -> Backtester | {symbol} {strategy} {start_date}→{end_date} | thread: {bt_thread_id}")

    # Build a precise, unambiguous instruction — no room for the agent to ask questions.
    command = (
        f"EXECUTE IMMEDIATELY. DO NOT ASK QUESTIONS.\n"
        f"Run backtest-strategy skill with these exact parameters:\n"
        f"  symbol={symbol}, strategy={strategy}, "
        f"start_date={start_date}, end_date={end_date}, "
        f"timeframe={timeframe}, initial_capital={initial_capital}\n"
        f"Historical data has already been verified as available.\n"
        f"Return the JSON result from the skill. Do not add commentary."
    )

    try:
        backtester = Backtester(model="gpt-5-mini")
        result = backtester.invoke(command, thread_id=bt_thread_id, apply_middleware=True)

        if "error" in result:
            return {
                "status": "error",
                "error": result["error"],
                "delegated_to": "backtester",
                "thread_id": bt_thread_id,
                "timestamp": result.get("timestamp", datetime.now().isoformat())
            }

        return {
            "status": "success",
            "response": result.get("response", str(result)),
            "delegated_to": "backtester",
            "thread_id": bt_thread_id,
            "timestamp": result.get("timestamp", datetime.now().isoformat())
        }

    except Exception as e:
        logger.error(f"Backtester delegation failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "delegated_to": "backtester",
            "thread_id": bt_thread_id,
            "timestamp": datetime.now().isoformat()
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delegate to specialized agents")
    parser.add_argument("--agent", choices=["quant", "backtester"], required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--thread-id", default="test-thread-001")
    args = parser.parse_args()

    # Seed the context var so derived IDs work in CLI testing
    from src.common.core.thread_context import set_thread_id
    set_thread_id(args.thread_id)

    try:
        if args.agent == "quant":
            result = delegate_to_quant_analyst_core(args.query)
        else:
            # CLI test: parse query as "symbol strategy start_date end_date"
            parts = args.query.split()
            result = delegate_to_backtester_core(
                symbol=parts[0] if len(parts) > 0 else "AAPL",
                strategy=parts[1] if len(parts) > 1 else "buy-and-hold",
                start_date=parts[2] if len(parts) > 2 else "2024-01-01",
                end_date=parts[3] if len(parts) > 3 else "2024-01-31",
            )

        print(json.dumps(result, indent=2))

    except Exception as e:
        logger.error(f"Delegation failed: {e}", exc_info=True)
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)
