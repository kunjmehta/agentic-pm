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


# ── Live telemetry ────────────────────────────────────────────────────────────

def _push_event(thread_id: Optional[str], event: dict) -> None:
    """Thread-safe push to the execution event queue for a thread.

    Called from within ThreadPoolExecutor workers to stream per-task
    progress events to the SSE ``/approve/stream/{thread_id}`` endpoint.

    Args:
        thread_id: Conversation thread ID; no-op if None or no queue registered.
        event: SSE event payload dict to push.
    """
    if not thread_id:
        return
    try:
        import src.semi_auto.app_state as _state
        q = _state._execution_queues.get(thread_id)
        loop = _state._event_loop
        if q is not None and loop is not None and loop.is_running():
            loop.call_soon_threadsafe(q.put_nowait, event)
    except Exception:
        pass  # telemetry failures must never break execution

MAX_READ_WORKERS = 12  # Read-heavy tasks (fetch, analyze, compute)
MAX_WRITE_WORKERS = 4  # Write tasks (orders, DB writes) — conservative for DuckDB

# Read-only functions that can run with higher parallelism
READ_ONLY_FUNCTIONS = frozenset({
    "get_portfolio_status",
    "get_positions_summary",
    "check_portfolio_health",
    "check_data_availability",
    "calc_momentum",
    "calc_volatility",
    "calc_volume",
    "analyze_candles",
    "calc_mean_reversion",
    "backtest_strategy",
    "snapshot_worth",
    # Strategy signal functions
    "vwap_reversion_signal",
    "opening_range_breakout_signal",
    "rsi_divergence_scalp_signal",
    "momentum_burst_signal",
    "golden_cross_signal",
    "breakout_52w_signal",
    "mean_reversion_daily_signal",
    "earnings_drift_signal",
})

# Write functions that require conservative parallelism
WRITE_FUNCTIONS = frozenset({
    "execute_order",
    "close_position",
    "scale_position",
    "execute_strategy_signal",
    "save_eod_snapshot",
    "swap_positions",
})

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

        # Detect skill-level failures returned as dicts instead of exceptions.
        # Functions like backtest_strategy_core return {"status": "failed", "error": "..."}.
        # The executor must surface these as task errors so the synthesizer can
        # distinguish them from genuine successes.
        result_failed = (
            isinstance(native_result, dict)
            and (
                native_result.get("status") in ("failed", "error")
                or ("error" in native_result and native_result.get("status") not in ("completed", "success", None))
            )
        )
        if result_failed:
            err_msg = native_result.get("error") or native_result.get("message") or "skill returned failure status"
            logger.warning(f"[executor] {fn_name} returned failure result: {err_msg}")
            return {
                "task_id": task_id,
                "function_name": fn_name,
                "status": "error",
                "result": native_result,
                "error": err_msg,
                "timing": {"tool": fn_name, "duration_ms": duration_ms, "status": "error"},
            }

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


def _run_queue(
    state: dict,
    queue_specs: List[tuple],
    label: str,
) -> dict:
    """Shared execution logic for analysis and order executor nodes.

    Args:
        state: Current GraphState dict.
        queue_specs: List of (prefix, queue_key) tuples to process.
        label: Log label for this executor pass ("analysis" or "order").

    Returns:
        Partial state update with execution_results and tool_timings.
    """
    if state.get("error"):
        logger.warning(f"[executor/{label}] skipping — upstream error: {state['error']}")
        return {"execution_results": state.get("execution_results") or {}, "tool_timings": state.get("tool_timings") or []}

    all_tasks: List[Dict[str, Any]] = []

    pm_queue = state.get("portfolio_task_queue") or []
    if label == "analysis":
        all_tasks.extend(pm_queue)  # portfolio tasks run in analysis pass

    for prefix, queue_key in queue_specs:
        queue = state.get(queue_key) or []
        for i, call in enumerate(queue):
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
        logger.info(f"[executor/{label}] no tasks — skipping")
        prior = state.get("execution_results") or {}
        return {"execution_results": prior, "tool_timings": state.get("tool_timings") or []}

    logger.info(f"[executor/{label}] processing {len(all_tasks)} tasks")

    # Merge with prior execution_results (from analysis pass, for order pass)
    execution_results: Dict[str, Any] = dict(state.get("execution_results") or {})
    tool_timings: List[Dict[str, Any]] = list(state.get("tool_timings") or [])

    independent = [t for t in all_tasks if not t.get("depends_on") and t.get("priority", 1) < 3]
    sequential = [t for t in all_tasks if t.get("depends_on") or t.get("priority", 1) >= 3]

    # Categorize independent tasks as read vs write for optimal parallelism
    read_tasks = [t for t in independent if t.get("function_name") in READ_ONLY_FUNCTIONS]
    write_tasks = [t for t in independent if t.get("function_name") in WRITE_FUNCTIONS]
    # Unknown functions default to write (conservative)
    unknown_tasks = [t for t in independent if t.get("function_name") not in READ_ONLY_FUNCTIONS and t.get("function_name") not in WRITE_FUNCTIONS]
    write_tasks.extend(unknown_tasks)

    thread_id: Optional[str] = state.get("thread_id")
    logger.info(
        f"[executor/{label}] parallel={len(independent)} (read={len(read_tasks)}, write={len(write_tasks)}) "
        f"sequential={len(sequential)}"
    )

    # Execute read tasks with high parallelism
    if read_tasks:
        with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as pool:
            futures = {}
            for t in read_tasks:
                _push_event(thread_id, {
                    "type": "tool_call",
                    "data": {
                        "task_id": t.get("task_id"),
                        "function_name": t.get("function_name"),
                        "status": "started",
                    },
                })
                futures[pool.submit(_run_task, t, {})] = t
            for future in as_completed(futures):
                result = future.result()
                execution_results[result["task_id"]] = result
                if result.get("timing"):
                    tool_timings.append(result["timing"])
                _push_event(thread_id, {
                    "type": "tool_call",
                    "data": {
                        "task_id": result["task_id"],
                        "function_name": result["function_name"],
                        "status": result["status"],
                        "duration_ms": result.get("timing", {}).get("duration_ms"),
                    },
                })

    # Execute write tasks with conservative parallelism
    if write_tasks:
        with ThreadPoolExecutor(max_workers=MAX_WRITE_WORKERS) as pool:
            futures = {}
            for t in write_tasks:
                _push_event(thread_id, {
                    "type": "tool_call",
                    "data": {
                        "task_id": t.get("task_id"),
                        "function_name": t.get("function_name"),
                        "status": "started",
                    },
                })
                futures[pool.submit(_run_task, t, {})] = t
            for future in as_completed(futures):
                result = future.result()
                execution_results[result["task_id"]] = result
                if result.get("timing"):
                    tool_timings.append(result["timing"])
                _push_event(thread_id, {
                    "type": "tool_call",
                    "data": {
                        "task_id": result["task_id"],
                        "function_name": result["function_name"],
                        "status": result["status"],
                        "duration_ms": result.get("timing", {}).get("duration_ms"),
                    },
                })

    for task in sequential:
        retry_count = task.get("retry_count", 0)
        if retry_count >= 1:
            logger.warning(f"[executor/{label}] skipping {task.get('task_id')} — already retried once")
            execution_results[task["task_id"]] = {
                "task_id": task["task_id"], "function_name": task.get("function_name"),
                "status": "skipped", "error": "Max retries reached",
            }
            continue

        fn_name = task.get("function_name", "")
        injected = {}
        for dep_id in task.get("depends_on", []):
            dep_result = execution_results.get(dep_id, {})
            injected.update(_extract_dep_params(dep_id, dep_result, fn_name))

        _push_event(thread_id, {
            "type": "tool_call",
            "data": {
                "task_id": task.get("task_id"),
                "function_name": fn_name,
                "status": "started",
            },
        })
        result = _run_task(task, injected)
        execution_results[task["task_id"]] = result
        if result.get("timing"):
            tool_timings.append(result["timing"])
        _push_event(thread_id, {
            "type": "tool_call",
            "data": {
                "task_id": result["task_id"],
                "function_name": result["function_name"],
                "status": result["status"],
                "duration_ms": result.get("timing", {}).get("duration_ms"),
            },
        })

        if result["status"] == "error":
            logger.warning(f"[executor/{label}] retrying failed task {task['task_id']}")
            task["retry_count"] = retry_count + 1
            _push_event(thread_id, {
                "type": "tool_call",
                "data": {
                    "task_id": task["task_id"],
                    "function_name": fn_name,
                    "status": "started",
                },
            })
            retry_result = _run_task(task, injected)
            execution_results[task["task_id"]] = retry_result
            if retry_result.get("timing"):
                tool_timings.append(retry_result["timing"])
            _push_event(thread_id, {
                "type": "tool_call",
                "data": {
                    "task_id": retry_result["task_id"],
                    "function_name": retry_result["function_name"],
                    "status": retry_result["status"],
                    "duration_ms": retry_result.get("timing", {}).get("duration_ms"),
                },
            })

    success_count = sum(1 for r in execution_results.values() if r.get("status") == "success")
    error_count = sum(1 for r in execution_results.values() if r.get("status") == "error")
    logger.info(f"[executor/{label}] done: {success_count} success, {error_count} errors")
    return {"execution_results": execution_results, "tool_timings": tool_timings}


def executor_node(state: dict) -> dict:
    """Execute analysis tasks from portfolio, quant, and backtester queues.

    Order queue is NOT processed here — it runs in order_executor_node after
    pm_decision_node decides whether orders are needed.

    Execution strategy:
    - Pass 1 (parallel): Tasks with no depends_on and priority < 3
    - Pass 2 (sequential): Tasks with depends_on set OR priority == 3

    Args:
        state: Current GraphState dict with populated task queues.

    Returns:
        Partial state update with execution_results and tool_timings.
    """
    return _run_queue(
        state,
        queue_specs=[("qa", "quant_task_queue"), ("bt", "backtester_task_queue")],
        label="analysis",
    )


def order_executor_node(state: dict) -> dict:
    """Execute order tasks from order_task_queue (second pass, after pm_decision).

    Merges results with execution_results from the analysis pass so that
    synthesizer_node sees both analysis and order outcomes in a single dict.

    Args:
        state: Current GraphState dict with order_task_queue populated by order_reasoning_node.

    Returns:
        Partial state update with merged execution_results and tool_timings.
    """
    return _run_queue(
        state,
        queue_specs=[("ord", "order_task_queue")],
        label="order",
    )


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
        "order_task_queue": None,
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
        "order_task_queue": None,
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
        "order_task_queue": None,
    })
    assert empty_result["execution_results"] == {}
    print("[OK] empty queues return empty results")

    print("\n[ALL OK] executor_node tests passed")
