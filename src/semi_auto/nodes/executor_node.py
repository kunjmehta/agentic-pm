"""Executor node for the semi-auto multi-agent system.

Reads all three task queues (portfolio, quant, backtester) from state and
executes the planned functions. Independent tasks run in parallel via
ThreadPoolExecutor; tasks with depends_on or priority=3 run sequentially
after the parallel pass completes.

All results are passed through _to_native() to strip numpy/pandas types
before storing in GraphState (required for LangGraph MemorySaver).

Sets state fields: execution_results, tool_timings.
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

MAX_WORKERS = 4  # Conservative — DuckDB write-lock on Windows

# Task-level metadata keys that must never be passed as function parameters.
# These are top-level planning fields emitted by the LLM agents alongside params.
_METADATA_KEYS = frozenset({
    "task_id", "priority", "depends_on", "workflow_type",
    "note", "metrics_requested", "description", "retry_count",
})


# ── Numpy/pandas type conversion ─────────────────────────────────────────────

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


# ── Task execution ────────────────────────────────────────────────────────────

def _run_task(task: Dict[str, Any], extra_params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a single task by looking up and calling its registered function.

    Args:
        task: Serialized TaskItem dict with function_name, params, task_id.
        extra_params: Additional kwargs injected from dependency results.

    Returns:
        Result dict with status, result, task_id, function_name, timing.
    """
    from src.semi_auto.registry.functions import FUNCTION_REGISTRY

    fn_name = task.get("function_name", "")
    task_id = task.get("task_id", "unknown")

    fn = FUNCTION_REGISTRY.get(fn_name)
    if fn is None:
        logger.warning(f"[executor] function '{fn_name}' not in registry")
        return {
            "task_id": task_id,
            "function_name": fn_name,
            "status": "error",
            "result": None,
            "error": f"Function '{fn_name}' not found in registry",
            "timing": {"tool": fn_name, "duration_ms": 0, "status": "error"},
        }

    # Strip task metadata that the LLM sometimes embeds inside params.
    # These are top-level planning fields and must never reach the function.
    raw_params = task.get("params", {})
    params = {k: v for k, v in raw_params.items() if k not in _METADATA_KEYS}
    params.update(extra_params)
    if len(params) != len(raw_params):
        stripped = set(raw_params) - set(params)
        logger.debug(f"[executor] stripped metadata from {fn_name} params: {stripped}")
    start_time = time.monotonic()

    try:
        logger.info(f"[executor] executing {fn_name} (task={task_id})")
        result = fn(**params)
        duration_ms = int((time.monotonic() - start_time) * 1000)
        native_result = _to_native(result)
        logger.info(f"[executor] {fn_name} completed in {duration_ms}ms")
        return {
            "task_id": task_id,
            "function_name": fn_name,
            "status": "success",
            "result": native_result,
            "error": None,
            "timing": {"tool": fn_name, "duration_ms": duration_ms, "status": "success"},
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.error(f"[executor] {fn_name} failed in {duration_ms}ms: {exc}", exc_info=True)
        return {
            "task_id": task_id,
            "function_name": fn_name,
            "status": "error",
            "result": None,
            "error": str(exc),
            "timing": {"tool": fn_name, "duration_ms": duration_ms, "status": "error"},
        }


def _extract_dep_params(dep_task_id: str, dep_result: Dict[str, Any], fn_name: str) -> Dict[str, Any]:
    """Extract parameters to inject from a dependency's execution result.

    Used specifically for check_portfolio_health which needs portfolio_status
    and positions_data from prior task results.

    Args:
        dep_task_id: The dependency task ID.
        dep_result: The result dict from executing that dependency.
        fn_name: The current function name (to decide injection logic).

    Returns:
        Dict of params to inject into the dependent task.
    """
    if dep_result.get("status") != "success":
        return {}
    result_data = dep_result.get("result") or {}

    # Inject for check_portfolio_health
    if fn_name == "check_portfolio_health":
        fn_dep = dep_result.get("function_name", "")
        if fn_dep == "get_portfolio_status":
            return {"portfolio_status": result_data}
        if fn_dep == "get_positions_summary":
            return {"positions_data": result_data}

    return {}


def executor_node(state: dict) -> dict:
    """Execute all queued tasks from portfolio, quant, and backtester queues.

    Execution strategy:
    - Pass 1 (parallel): Tasks with no depends_on and priority < 3
    - Pass 2 (sequential): Tasks with depends_on set OR priority == 3

    Args:
        state: Current GraphState dict with populated task queues.

    Returns:
        Partial state update with execution_results and tool_timings.
    """
    # Short-circuit: upstream error already set — skip execution
    if state.get("error"):
        logger.warning(f"[executor] skipping — upstream error: {state['error']}")
        return {"execution_results": {}, "tool_timings": []}

    # Collect all queues — normalise quant/bt simple {function_name, params} to full task dicts
    all_tasks: List[Dict[str, Any]] = []

    pm_queue = state.get("portfolio_task_queue") or []
    all_tasks.extend(pm_queue)  # already full TaskItem dicts

    for prefix, queue_key in (("qa", "quant_task_queue"), ("bt", "backtester_task_queue")):
        queue = state.get(queue_key) or []
        for i, call in enumerate(queue):
            # FunctionCall format: {function_name, params} — normalise to task dict
            if "task_id" not in call:
                call = {
                    "task_id": f"{prefix}_{i + 1:03d}",
                    "function_name": call.get("function_name", ""),
                    "params": call.get("params", {}),
                    "priority": 1,
                    "depends_on": [],
                    "retry_count": 0,
                    "description": "",
                }
            all_tasks.append(call)

    if not all_tasks:
        logger.info("[executor] no tasks in any queue — skipping execution")
        return {"execution_results": {}, "tool_timings": []}

    logger.info(f"[executor] processing {len(all_tasks)} total tasks")

    execution_results: Dict[str, Any] = {}
    tool_timings: List[Dict[str, Any]] = []

    # Separate independent (parallel) from dependent/sequential tasks
    independent = [
        t for t in all_tasks
        if not t.get("depends_on") and t.get("priority", 1) < 3
    ]
    sequential = [
        t for t in all_tasks
        if t.get("depends_on") or t.get("priority", 1) >= 3
    ]

    logger.info(f"[executor] parallel={len(independent)} sequential={len(sequential)}")

    # ── Pass 1: Parallel execution ────────────────────────────────────────────
    if independent:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_run_task, t, {}): t for t in independent}
            for future in as_completed(futures):
                result = future.result()
                execution_results[result["task_id"]] = result
                if result.get("timing"):
                    tool_timings.append(result["timing"])

    # ── Pass 2: Sequential execution with dependency injection ─────────────────
    for task in sequential:
        retry_count = task.get("retry_count", 0)
        if retry_count >= 1:
            logger.warning(f"[executor] skipping {task.get('task_id')} — already retried once")
            execution_results[task["task_id"]] = {
                "task_id": task["task_id"],
                "function_name": task.get("function_name"),
                "status": "skipped",
                "error": "Max retries reached",
            }
            continue

        fn_name = task.get("function_name", "")
        injected = {}
        for dep_id in task.get("depends_on", []):
            dep_result = execution_results.get(dep_id, {})
            injected.update(_extract_dep_params(dep_id, dep_result, fn_name))

        result = _run_task(task, injected)
        execution_results[task["task_id"]] = result
        if result.get("timing"):
            tool_timings.append(result["timing"])

        # Single retry on failure
        if result["status"] == "error":
            logger.warning(f"[executor] retrying failed task {task['task_id']}")
            task["retry_count"] = retry_count + 1
            retry_result = _run_task(task, injected)
            execution_results[task["task_id"]] = retry_result
            if retry_result.get("timing"):
                tool_timings.append(retry_result["timing"])

    success_count = sum(1 for r in execution_results.values() if r.get("status") == "success")
    error_count = sum(1 for r in execution_results.values() if r.get("status") == "error")
    logger.info(f"[executor] done: {success_count} success, {error_count} errors")

    return {
        "execution_results": execution_results,
        "tool_timings": tool_timings,
    }


if __name__ == "__main__":
    """Functional test with hardcoded task list (no LLM required)."""
    print("=" * 60)
    print("executor_node Functional Tests")
    print("=" * 60)

    # Test 1: portfolio status tasks (parallel)
    print("\n[1/3] Parallel portfolio tasks")
    test_state = {
        "portfolio_task_queue": [
            {
                "task_id": "pm_001",
                "function_name": "get_portfolio_status",
                "params": {},
                "priority": 1,
                "depends_on": [],
                "retry_count": 0,
                "description": "Fetch portfolio status",
            },
            {
                "task_id": "pm_002",
                "function_name": "get_positions_summary",
                "params": {},
                "priority": 1,
                "depends_on": [],
                "retry_count": 0,
                "description": "Fetch positions",
            },
        ],
        "quant_task_queue": None,
        "backtester_task_queue": None,
    }
    result = executor_node(test_state)
    print(f"[OK] execution_results keys: {list(result['execution_results'].keys())}")
    print(f"[OK] tool_timings count: {len(result['tool_timings'])}")
    assert "pm_001" in result["execution_results"]
    assert "pm_002" in result["execution_results"]

    # Test 2: unknown function (error handling)
    print("\n[2/3] Unknown function error handling")
    error_state = {
        "portfolio_task_queue": [
            {
                "task_id": "pm_err",
                "function_name": "nonexistent_function",
                "params": {},
                "priority": 1,
                "depends_on": [],
                "retry_count": 0,
                "description": "This should fail gracefully",
            }
        ],
        "quant_task_queue": None,
        "backtester_task_queue": None,
    }
    result = executor_node(error_state)
    assert result["execution_results"]["pm_err"]["status"] == "error"
    print(f"[OK] unknown function handled: {result['execution_results']['pm_err']['error']}")

    # Test 3: empty queues
    print("\n[3/3] Empty queues")
    empty_result = executor_node({
        "portfolio_task_queue": None,
        "quant_task_queue": [],
        "backtester_task_queue": None,
    })
    assert empty_result["execution_results"] == {}
    print("[OK] empty queues return empty results")

    print("\n[ALL OK] executor_node tests passed")
