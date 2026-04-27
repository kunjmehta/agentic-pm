"""Process-level DuckDB connection manager.

Owns exactly **one** connection per database file for the lifetime of the
process.  All DAOs call :func:`get_connection` instead of opening their own
connections, so there is no file-lock contention between DAO instances within
the same process.

DuckDB enforces a single read-write lock per file across OS processes.
To avoid that conflict each process must declare which databases it only reads
by calling :func:`configure_read_only` **before** the first :func:`get_connection`
call for those keys.  Read-only connections may be opened by any number of
processes simultaneously, even while another process holds the write lock.

Write ownership (single source of truth):
- ``market``    → ETL process
- ``analysis``  → API process (schema init at startup; agent writes signals via API)
- ``portfolio`` → API process
- ``backtest``  → API process
- ETL opens market read-write; all others read-only (ETL does not use analysis).
- Agent process opens all databases read-only; persists data via API HTTP calls.

Usage::

    # At process startup, before any DAO is created:
    from src.common.db_connections import configure_read_only, get_connection

    configure_read_only(["market", "analysis"])   # in API process
    conn = get_connection("market")               # opens read-only

Shutdown::

    from src.common.db_connections import close_all
    close_all()   # call once at process exit / lifespan teardown
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

import duckdb

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

# ── DB file map (relative to project root) ────────────────────────────────────

_DB_FILES: dict[str, str] = {
    "market":    "data/market_data.duckdb",
    "portfolio": "data/portfolio.duckdb",
    "analysis":  "data/analysis.duckdb",
    "backtest":  "data/backtest.duckdb",
}

# ── Internal state ────────────────────────────────────────────────────────────

_lock = threading.Lock()
_connections: dict[str, duckdb.DuckDBPyConnection] = {}
# Keys whose connections must be opened read-only in this process.
_read_only_keys: set[str] = set()


# ── Public API ────────────────────────────────────────────────────────────────


def configure_read_only(keys: list[str]) -> None:
    """Declare which databases this process should open read-only.

    Must be called **before** the first :func:`get_connection` for each key.
    Calling after a connection is already open has no effect on that connection.

    Args:
        keys: Database keys (e.g. ``["market", "analysis"]``) to open RO.

    Raises:
        ValueError: If any key is not a recognised database.
    """
    unknown = set(keys) - set(_DB_FILES)
    if unknown:
        raise ValueError(
            f"Unknown db_key(s): {sorted(unknown)}. Valid keys: {sorted(_DB_FILES)}"
        )
    with _lock:
        _read_only_keys.update(keys)
    logger.info(f"[db_connections] read-only keys configured: {sorted(_read_only_keys)}")


def get_connection(db_key: str) -> duckdb.DuckDBPyConnection:
    """Return the shared R/W WAL connection for *db_key*.

    Opens the connection on first call (lazy init).  Subsequent calls return
    the cached object — no new ``duckdb.connect()`` calls are made.

    Args:
        db_key: One of ``"market"``, ``"portfolio"``, ``"analysis"``,
            ``"backtest"``.

    Returns:
        Open :class:`duckdb.DuckDBPyConnection` in read-write WAL mode.

    Raises:
        ValueError: If *db_key* is not a recognised database.
        RuntimeError: If the underlying DuckDB file cannot be opened.
    """
    if db_key not in _DB_FILES:
        raise ValueError(
            f"Unknown db_key={db_key!r}. "
            f"Valid keys: {sorted(_DB_FILES)}"
        )

    if db_key not in _connections:
        with _lock:
            # Double-checked locking — another thread may have created it.
            if db_key not in _connections:
                _connections[db_key] = _open(db_key)

    return _connections[db_key]


def close_all() -> None:
    """Close all open connections.

    Call once during process shutdown (FastAPI lifespan teardown, ETL main
    exit, etc.) to flush WAL and release file handles.
    """
    with _lock:
        for key in list(_connections.keys()):
            conn = _connections.pop(key)
            try:
                conn.close()
                logger.debug(f"[db_connections] closed {key} connection")
            except Exception as exc:
                logger.warning(f"[db_connections] error closing {key}: {exc}")


# ── Internal helpers ──────────────────────────────────────────────────────────


def _open(db_key: str) -> duckdb.DuckDBPyConnection:
    """Open a connection for *db_key*, honouring the process-level read-only config.

    Args:
        db_key: Registered database identifier.

    Returns:
        Configured :class:`duckdb.DuckDBPyConnection`.

    Raises:
        RuntimeError: If the connection cannot be established.
    """
    rel_path = _DB_FILES[db_key]
    abs_path = _project_root / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    read_only = db_key in _read_only_keys
    mode_label = "R/O" if read_only else "R/W WAL"

    try:
        conn = duckdb.connect(str(abs_path), read_only=read_only)
        logger.info(f"[db_connections] opened {db_key} ({rel_path}) — {mode_label}")
        return conn
    except duckdb.IOException as exc:
        hint = (
            "Another process holds an exclusive write lock. "
            "Call configure_read_only(['" + db_key + "']) before get_connection() "
            "if this process only reads from this database."
        )
        raise RuntimeError(
            f"[db_connections] cannot open {db_key} ({abs_path}): {exc}\n{hint}"
        ) from exc


# ── Convenience aliases ───────────────────────────────────────────────────────


def get_market_conn() -> duckdb.DuckDBPyConnection:
    """Shared connection to ``market_data.duckdb``."""
    return get_connection("market")


def get_portfolio_conn() -> duckdb.DuckDBPyConnection:
    """Shared connection to ``portfolio.duckdb``."""
    return get_connection("portfolio")


def get_analysis_conn() -> duckdb.DuckDBPyConnection:
    """Shared connection to ``analysis.duckdb``."""
    return get_connection("analysis")


def get_backtest_conn() -> duckdb.DuckDBPyConnection:
    """Shared connection to ``backtest.duckdb``."""
    return get_connection("backtest")
