"""CLI entry point for the deterministic LangGraph portfolio manager.

Usage:
    python src/graph/main.py --query "What is my portfolio status?" --backtest-mode
    python src/graph/main.py --query "Analyze AAPL" --backtest-mode
    python src/graph/main.py --query "Backtest TSLA from 2026-01-01 to 2026-01-31" --backtest-mode
    python src/graph/main.py --query "Full analysis on MSFT" --backtest-mode --stream
"""

import argparse
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.langgraph.graph import build_graph, _make_initial_state
from src.common.core.thread_context import set_thread_id, reset_thread_id
from src.common.utils import get_logger

logger = get_logger(__name__)


def run_query(
    query: str,
    thread_id: str,
    backtest_mode: bool,
    stream: bool = False,
) -> dict:
    """Execute a query through the LangGraph agent.

    Args:
        query: User query string.
        thread_id: Conversation thread ID (UUID).
        backtest_mode: Bypass market/portfolio guards if True.
        stream: If True, stream node-by-node output to stdout.

    Returns:
        Final graph state dict.
    """
    graph = build_graph()
    token = set_thread_id(thread_id)
    config = {"configurable": {"thread_id": thread_id}}
    initial = _make_initial_state(query, thread_id, backtest_mode)

    try:
        if stream:
            final_state = {}
            for step in graph.stream(initial, config=config):
                for node_name, node_output in step.items():
                    print(f"\n--- Node: {node_name} ---")
                    if "final_response" in node_output:
                        print(node_output["final_response"])
                    elif "intent" in node_output:
                        print(f"  intent={node_output.get('intent')} symbol={node_output.get('symbol')} bt_workflow={node_output.get('bt_workflow')}")
                    elif "routing_error" in node_output:
                        print(f"  BLOCKED: {node_output['routing_error']}")
                    else:
                        keys = [k for k, v in node_output.items() if v is not None]
                        print(f"  populated: {keys}")
                final_state.update(step.get(node_name, {}))
            return final_state
        else:
            start_ms = time.time()
            result = graph.invoke(initial, config=config)
            elapsed = int((time.time() - start_ms) * 1000)
            result["execution_time_ms"] = elapsed
            return result

    finally:
        reset_thread_id(token)


def main() -> None:
    """Parse CLI arguments and run the graph agent."""
    parser = argparse.ArgumentParser(
        description="Deterministic LangGraph Portfolio Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/graph/main.py --query "What is my portfolio status?" --backtest-mode
  python src/graph/main.py --query "Analyze AAPL for buy signal" --backtest-mode
  python src/graph/main.py --query "Backtest TSLA 2026-01-01 to 2026-01-31" --backtest-mode
  python src/graph/main.py --query "Full analysis on MSFT" --backtest-mode --stream
  python src/graph/main.py --query "What would my 2026-01-15 portfolio be worth today?" --backtest-mode
        """,
    )
    parser.add_argument("--query", "-q", required=True, help="User query")
    parser.add_argument(
        "--thread-id",
        "-t",
        default=None,
        help="Thread ID for conversation continuity (default: new UUID)",
    )
    parser.add_argument(
        "--backtest-mode",
        "-b",
        action="store_true",
        default=False,
        help="Bypass market hours and portfolio guards (for testing/historical queries)",
    )
    parser.add_argument(
        "--stream",
        "-s",
        action="store_true",
        default=False,
        help="Stream node-by-node output",
    )
    args = parser.parse_args()

    thread_id = args.thread_id or str(uuid.uuid4())

    print(f"\n{'='*60}")
    print(f"Query:       {args.query}")
    print(f"Thread ID:   {thread_id}")
    print(f"Backtest:    {args.backtest_mode}")
    print(f"Stream:      {args.stream}")
    print(f"{'='*60}\n")

    try:
        result = run_query(
            query=args.query,
            thread_id=thread_id,
            backtest_mode=args.backtest_mode,
            stream=args.stream,
        )

        if not args.stream:
            print("\n" + "=" * 60)
            print("RESULT")
            print("=" * 60)
            print(f"Intent:    {result.get('intent')}")
            if result.get("symbol"):
                print(f"Symbol:    {result.get('symbol')}")
            if result.get("bt_workflow"):
                print(f"Workflow:  {result.get('bt_workflow')}")
            if result.get("execution_time_ms"):
                print(f"Time:      {result.get('execution_time_ms')}ms")
            if result.get("routing_error"):
                print(f"Blocked:   {result.get('routing_error')}")

            print("\n--- Response ---")
            print(result.get("final_response", "(no response)"))

    except Exception as exc:
        logger.error(f"Graph execution failed: {exc}", exc_info=True)
        print(f"\n[ERROR] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
