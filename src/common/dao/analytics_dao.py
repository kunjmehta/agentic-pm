"""Analytics DAO for audit trails and compliance logging.

Provides persistence for LLM reasoning traces, performance metrics, and
audit logs. In production, this would write to a dedicated analytics database
(e.g., separate DuckDB file or TimescaleDB for time-series data).

For now, implements logging-based audit trail with optional JSON file persistence.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

# Analytics data directory
ANALYTICS_DIR = Path.home() / ".agentic-trader" / "analytics"
REASONING_TRACES_DIR = ANALYTICS_DIR / "reasoning_traces"


class AnalyticsDAO:
    """Data Access Object for analytics and audit logging.

    Provides methods for persisting:
    - LLM reasoning traces (for compliance/debugging)
    - Performance metrics
    - Audit logs

    Current implementation uses JSON file storage. In production, migrate to:
    - Dedicated analytics.duckdb database
    - TimescaleDB for time-series queries
    - Elasticsearch for full-text search
    """

    def __init__(self):
        """Initialize AnalyticsDAO and ensure directories exist."""
        REASONING_TRACES_DIR.mkdir(parents=True, exist_ok=True)

    def save_reasoning_trace(self, reasoning_data: Dict[str, Any]) -> None:
        """Persist LLM reasoning trace for audit/compliance.

        Saves to both:
        1. Structured JSON file (queryable)
        2. Application log (for monitoring)

        Args:
            reasoning_data: Dict containing:
                - thread_id: Conversation identifier
                - turn_number: Sequential turn
                - timestamp: ISO timestamp
                - query: User query
                - intent: Classified intent
                - portfolio_reasoning: PM reasoning trace
                - quant_reasoning: Quant analyst trace
                - backtester_reasoning: Backtest trace
                - order_reasoning: Order planning trace
                - pm_review_notes: PM review notes
                - pm_decision_reasoning: Post-execution decision
                - (additional metadata fields)

        Note:
            Errors are caught and logged but don't raise exceptions to avoid
            blocking the main workflow.
        """
        try:
            thread_id = reasoning_data.get("thread_id", "unknown")
            turn_number = reasoning_data.get("turn_number", 0)
            timestamp = reasoning_data.get("timestamp", datetime.utcnow().isoformat())

            # Create filename with thread_id and timestamp
            safe_timestamp = timestamp.replace(":", "-").replace(".", "-")
            filename = f"{thread_id}_{turn_number}_{safe_timestamp}.json"
            file_path = REASONING_TRACES_DIR / filename

            # Write JSON file
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(reasoning_data, f, indent=2, default=str)

            # Log summary (for monitoring/alerting)
            logger.info(
                f"[analytics] Reasoning trace saved: "
                f"thread={thread_id} turn={turn_number} "
                f"intent={reasoning_data.get('intent')} "
                f"symbol={reasoning_data.get('symbol')} "
                f"file={file_path.name}"
            )

            # Log detailed trace (for audit/compliance)
            logger.debug(
                f"[analytics] Reasoning details: "
                f"portfolio={bool(reasoning_data.get('portfolio_reasoning'))} "
                f"quant={bool(reasoning_data.get('quant_reasoning'))} "
                f"backtester={bool(reasoning_data.get('backtester_reasoning'))} "
                f"order={bool(reasoning_data.get('order_reasoning'))} "
                f"approved={reasoning_data.get('pm_review_approved')}"
            )

        except Exception as exc:
            logger.error(
                f"[analytics] Failed to save reasoning trace: {exc}",
                exc_info=True
            )

    def close(self) -> None:
        """Close DAO resources (no-op for file-based storage)."""
        pass


if __name__ == "__main__":
    """Smoke test for AnalyticsDAO."""
    print("=" * 60)
    print("AnalyticsDAO Smoke Test")
    print("=" * 60)

    dao = AnalyticsDAO()

    # Test: save reasoning trace
    print("\n[1/1] Testing save_reasoning_trace...")
    test_data = {
        "thread_id": "test-thread-001",
        "turn_number": 1,
        "timestamp": datetime.utcnow().isoformat(),
        "query": "What is my portfolio status?",
        "intent": "portfolio",
        "symbol": None,
        "portfolio_reasoning": "PM will fetch portfolio status and positions summary.",
        "quant_reasoning": None,
        "backtester_reasoning": None,
        "order_reasoning": None,
        "pm_review_notes": "Plan approved. No sub-agents needed.",
        "pm_review_approved": True,
        "execute_orders": False,
    }

    dao.save_reasoning_trace(test_data)
    dao.close()

    # Verify file was created
    traces = list(REASONING_TRACES_DIR.glob("test-thread-001_*.json"))
    if traces:
        print(f"[OK] Reasoning trace saved: {traces[0].name}")
        # Read and verify
        with open(traces[0]) as f:
            data = json.load(f)
            assert data["thread_id"] == "test-thread-001"
            assert data["intent"] == "portfolio"
            print("[OK] Trace data verified")
    else:
        print("[ERROR] Trace file not found")

    print("\n" + "=" * 60)
    print("AnalyticsDAO tests complete")
    print(f"Traces saved to: {REASONING_TRACES_DIR}")
    print("=" * 60)
