"""Feedback handler node — process user feedback on proposed plans.

When is_feedback=True, this node prepares state for PM review by:
1. Loading the last proposed plan from conversation history (task queues)
2. Setting pm_review_approved=False to trigger revision flow
3. Preserving context (prior_turns, conversation_id, backtest_mode)

This allows the PM to revise the plan based on user feedback without re-running
the entire analysis pipeline (classifier, data availability, etc.).
"""

import sys
from pathlib import Path
from typing import Any, Dict

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.server.state import GraphState
from src.common.utils import get_logger

logger = get_logger(__name__)


def feedback_handler_node(state: GraphState) -> Dict[str, Any]:
    """Process user feedback and prepare state for PM review.

    When user provides feedback on a proposed plan (is_feedback=True), this node:
    - Marks the plan as rejected (pm_review_approved=False)
    - Preserves the original task queues from the last turn
    - Adds the feedback query to the conversation context
    - Routes to pm_review_node for plan revision

    The PM review node will see the feedback query and can revise the plan accordingly.

    Args:
        state: Current GraphState with is_feedback=True.

    Returns:
        Partial state update dict with:
        - pm_review_approved: False (triggers revision flow)
        - review_iteration: Incremented or initialized to 0
        - Any other state needed for PM review
    """
    logger.info("[feedback_handler] Processing user feedback")

    # Extract prior turns to understand the context
    prior_turns = state.get("prior_turns") or []
    thread_id = state.get("thread_id", "")
    feedback_query = state.get("query", "")

    _queue_keys = ("portfolio_task_queue", "quant_task_queue", "backtester_task_queue", "order_task_queue")

    # Seed from current state; override from last pending-approval turn if found.
    last_tasks = {k: state.get(k) or [] for k in _queue_keys}

    for turn in reversed(prior_turns):
        if turn.get("status") == "pending_approval":
            for key in _queue_keys:
                if key in turn:
                    last_tasks[key] = turn.get(key) or []
            logger.info(f"[feedback_handler] Loaded task queues from turn {turn.get('turn_number')}")
            break

    review_iteration = (state.get("review_iteration") or 0) + 1

    logger.info(
        f"[feedback_handler] Feedback received: \"{feedback_query[:80]}...\" "
        f"(iteration={review_iteration})"
    )

    return {
        "pm_review_approved": False,  # Trigger revision flow
        "review_iteration": review_iteration,
        "portfolio_task_queue": last_tasks["portfolio_task_queue"],
        "quant_task_queue": last_tasks["quant_task_queue"],
        "backtester_task_queue": last_tasks["backtester_task_queue"],
        "order_task_queue": last_tasks["order_task_queue"],
        # Add a note that this is feedback-driven revision
        "pm_review_notes": f"User provided feedback: {feedback_query}",
    }


if __name__ == "__main__":
    """Smoke test: verify feedback handler processes state correctly."""
    print("=" * 60)
    print("feedback_handler_node.py Smoke Test")
    print("=" * 60)

    # Mock state with feedback
    test_state: GraphState = {
        "query": "Please add error handling for API failures",
        "thread_id": "test-thread-001",
        "backtest_mode": True,
        "is_feedback": True,
        "conversation_id": "conv-001",
        "turn_number": 2,
        "prior_turns": [
            {
                "turn_number": 1,
                "status": "pending_approval",
                "portfolio_task_queue": [
                    {"task_id": "pm_001", "function_name": "get_portfolio_status"}
                ],
                "quant_task_queue": [],
                "backtester_task_queue": [
                    {"task_id": "bt_001", "function_name": "run_backtest"}
                ],
            }
        ],
        "portfolio_task_queue": None,
        "quant_task_queue": None,
        "backtester_task_queue": None,
        "order_task_queue": None,
        "intent": None,
        "symbol": None,
        "bt_workflow": None,
        "routing_error": None,
        "_query_intent": None,
        "_delegate_quant": None,
        "_delegate_backtester": None,
        "_quant_query": None,
        "_backtester_query": None,
        "_order_query": None,
        "portfolio_reasoning": None,
        "quant_reasoning": None,
        "backtester_reasoning": None,
        "order_reasoning": None,
        "pm_review_approved": None,
        "pm_review_notes": None,
        "pm_review_edits": None,
        "review_iteration": 0,
        "pm_decision_reasoning": None,
        "_execute_orders": None,
        "execution_results": None,
        "final_response": None,
        "error": None,
        "execution_time_ms": None,
        "timestamp": "2025-01-01T00:00:00Z",
        "tool_timings": None,
        "data_availability": None,
        "signal_batch": None,
        "autonomous_mode": False,
    }

    # Run feedback handler
    result = feedback_handler_node(test_state)

    # Verify output
    assert result["pm_review_approved"] is False
    assert "User provided feedback:" in result["pm_review_notes"]
    assert result["review_iteration"] == 1  # starts at 0, incremented to 1
    assert len(result["portfolio_task_queue"]) == 1
    assert len(result["backtester_task_queue"]) == 1
    assert result["backtester_task_queue"][0]["task_id"] == "bt_001"

    print("[OK] Feedback handler processed state correctly")
    print(f"     pm_review_approved: {result['pm_review_approved']}")
    print(f"     review_iteration: {result['review_iteration']}")
    print(f"     pm_review_notes: {result['pm_review_notes'][:60]}...")
    print(f"     portfolio_tasks: {len(result['portfolio_task_queue'])} tasks")
    print(f"     backtester_tasks: {len(result['backtester_task_queue'])} tasks")

    print("\n[ALL OK] feedback_handler_node.py smoke test passed")
