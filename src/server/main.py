"""CLI entry point for the semi-auto multi-agent system.

Usage:
    python src/semi-auto/main.py --query "What is my portfolio status?" --backtest-mode
    python src/semi-auto/main.py --query "Analyze AAPL" --thread-id <uuid> --auto-approve

The CLI runs a two-phase interaction:
  Phase 1: Graph runs through reasoning nodes → shows task preview (HITL interrupt)
  Phase 2: User confirms → graph resumes through executor → shows final response

With --auto-approve: skips the confirmation prompt (non-interactive / scripted use).
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from langgraph.checkpoint.memory import MemorySaver
from src.server.graph import build_graph
from src.server.state import make_initial_state
from src.common.utils import get_logger

logger = get_logger(__name__)


def _print_divider(char: str = "=", width: int = 60) -> None:
    print(char * width)


def _print_task_preview(state: dict) -> None:
    """Print the task preview (HITL approval screen) to stdout.

    Args:
        state: Graph state after interrupt.
    """
    _print_divider()
    print("TASK PREVIEW — Review before execution")
    _print_divider()

    if state.get("portfolio_reasoning"):
        print("\n--- PM Reasoning ---")
        print(state["portfolio_reasoning"])

    if state.get("quant_reasoning"):
        print("\n--- Quant Reasoning ---")
        print(state["quant_reasoning"])

    if state.get("backtester_reasoning"):
        print("\n--- Backtester Reasoning ---")
        print(state["backtester_reasoning"])

    # Print task tables
    for queue_key, label in [
        ("portfolio_task_queue", "Portfolio"),
        ("quant_task_queue", "Quant"),
        ("backtester_task_queue", "Backtester"),
    ]:
        queue = state.get(queue_key) or []
        if queue:
            print(f"\n--- {label} Tasks ---")
            print(f"{'ID':<10} {'Function':<30} {'Priority':<10} {'Depends On'}")
            print("-" * 65)
            for task in queue:
                tid = task.get("task_id", "?")
                fn = task.get("function_name", "?")
                pri = task.get("priority", 1)
                deps = ", ".join(task.get("depends_on", []))
                print(f"{tid:<10} {fn:<30} {pri:<10} {deps or '—'}")
            print()

    _print_divider("-")


def _print_final_response(state: dict) -> None:
    """Print the final synthesized response and execution summary.

    Args:
        state: Graph state after full execution.
    """
    _print_divider()
    print("EXECUTION SUMMARY")
    _print_divider("-")

    exec_results = state.get("execution_results") or {}
    if exec_results:
        print(f"\n{'Task ID':<12} {'Function':<30} {'Status':<10} {'Duration'}")
        print("-" * 65)
        for task_id, result in exec_results.items():
            fn = result.get("function_name", "?")
            status = result.get("status", "?")
            timing = result.get("timing") or {}
            duration = f"{timing.get('duration_ms', 0)}ms" if isinstance(timing, dict) else "?"
            print(f"{task_id:<12} {fn:<30} {status:<10} {duration}")

    elapsed = state.get("execution_time_ms")
    if elapsed:
        print(f"\nTotal execution time: {elapsed}ms")

    _print_divider()
    print("RESPONSE")
    _print_divider("-")
    print()
    print(state.get("final_response", "(no response generated)"))
    print()
    _print_divider()


def run_query(
    query: str,
    thread_id: str,
    conversation_id: str,
    backtest_mode: bool = False,
    auto_approve: bool = False,
) -> dict:
    """Run a complete query through the semi-auto graph with HITL flow.

    Args:
        query: User natural-language query.
        thread_id: LangGraph MemorySaver key.
        conversation_id: App-level session UUID.
        backtest_mode: If True, bypass market/portfolio guards.
        auto_approve: If True, skip HITL confirmation and auto-approve tasks.

    Returns:
        Final graph state dict.
    """
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    initial = make_initial_state(
        query=query,
        thread_id=thread_id,
        backtest_mode=backtest_mode,
        conversation_id=conversation_id,
    )

    _print_divider()
    print(f"Query:        {query}")
    print(f"Thread ID:    {thread_id}")
    print(f"Conv ID:      {conversation_id}")
    print(f"Backtest:     {backtest_mode}")
    _print_divider()

    # Phase 1: Run through reasoning nodes (interrupts before executor)
    print("\n[Phase 1] Running reasoning agents...")
    start = time.monotonic()
    snapshot = graph.invoke(initial, config=config)
    phase1_ms = int((time.monotonic() - start) * 1000)
    print(f"[OK] Reasoning complete in {phase1_ms}ms")

    # Display task preview
    _print_task_preview(snapshot)

    # If execution already happened (guard short-circuit to synthesizer)
    if snapshot.get("final_response"):
        print("\n[INFO] Guard short-circuited — final response already available")
        _print_final_response(snapshot)
        return snapshot

    # HITL: ask for approval (unless auto-approve)
    if not auto_approve:
        answer = input("\nApprove task execution? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("[CANCELLED] Task execution rejected by user.")
            return snapshot
    else:
        print("[AUTO-APPROVE] Proceeding with task execution...")

    # Phase 2: Resume graph from checkpoint (executor_node onwards)
    print("\n[Phase 2] Executing tasks and synthesizing response...")
    start2 = time.monotonic()
    final_state = graph.invoke(None, config=config)
    phase2_ms = int((time.monotonic() - start2) * 1000)
    print(f"[OK] Execution + synthesis complete in {phase2_ms}ms")

    _print_final_response(final_state)
    return final_state


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Semi-Auto Portfolio Manager — LangGraph Multi-Agent System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--query", "-q", required=True, help="User query string")
    parser.add_argument("--thread-id", default=None, help="Conversation thread UUID (auto-generated if omitted)")
    parser.add_argument("--conversation-id", default=None, help="Session UUID (auto-generated if omitted)")
    parser.add_argument("--backtest-mode", action="store_true", default=False, help="Bypass market/portfolio guards")
    parser.add_argument("--auto-approve", action="store_true", default=False, help="Skip HITL confirmation")

    args = parser.parse_args()

    thread_id = args.thread_id or str(uuid.uuid4())
    conversation_id = args.conversation_id or str(uuid.uuid4())

    run_query(
        query=args.query,
        thread_id=thread_id,
        conversation_id=conversation_id,
        backtest_mode=args.backtest_mode,
        auto_approve=args.auto_approve,
    )


if __name__ == "__main__":
    main()
