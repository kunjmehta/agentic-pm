"""API process entry point.

Wraps the FastAPI application with the cleaned-up API-only lifespan.
This process serves all HTTP routes and WebSocket connections; it does NOT
manage ETL streaming or autonomous signal processing.

Usage:
    uvicorn src.processes.api_process:app --host 0.0.0.0 --port 8000
    # or with hot-reload:
    uvicorn src.processes.api_process:app --reload --port 8000
    # or directly:
    python src/processes/api_process.py
"""

import sys
import uvicorn
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

# API owns writes to portfolio, backtest, and analysis (schema init + signal persistence).
# ETL owns market writes. Open market read-only to avoid DuckDB's single-writer lock.
from src.common.db_connections import configure_read_only
configure_read_only(["market"])

# Import the application from the main server module.
# The lifespan registered there handles API-only concerns.
from src.server.api import app  # noqa: E402 — path setup must precede this


if __name__ == "__main__":
    uvicorn.run(
        "src.processes.api_process:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
