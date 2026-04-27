"""Shared server-level constants used across nodes, services, and the executor.

Centralising these prevents the same magic numbers from being re-declared in
every node file and ensures a single source of truth for tuning parameters.
"""

# ── LLM retry budget ──────────────────────────────────────────────────────────

# Maximum attempts when the LLM returns a ValidationError or transient failure.
# Applied uniformly across all reasoning nodes (portfolio, quant, backtester,
# order, pm_review, pm_decision, synthesizer, classifier).
MAX_RETRIES: int = 3

# ── Executor thread-pool sizing ───────────────────────────────────────────────

# Parallel read workers — used for independent fetch/analyse/compute tasks.
# Sized for I/O-bound work (DB reads, indicator calculations).
MAX_READ_WORKERS: int = 12

# Sequential write workers — used for order placement and DuckDB writes.
# Kept conservative to avoid DuckDB write-lock contention.
MAX_WRITE_WORKERS: int = 4

# ── Executor metadata filtering ───────────────────────────────────────────────

# Top-level task planning fields emitted by the LLM alongside the function
# params dict.  These must be stripped before passing kwargs to the registered
# callable so functions never receive unexpected keyword arguments.
METADATA_KEYS: frozenset = frozenset({
    "task_id", "priority", "depends_on", "workflow_type",
    "note", "metrics_requested", "description", "retry_count",
})
