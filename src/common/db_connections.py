"""Process-level DuckDB connection manager.

Owns exactly **one** read-write WAL-enabled :class:`duckdb.DuckDBPyConnection`
per database file for the lifetime of the process.  All DAOs call
:func:`get_connection` instead of opening their own connections, so there is
no file-lock contention between DAO instances within the same process.

Each of the three processes (API, ETL, Agent) imports this module and receives
its own connection objects — there is no cross-process Python-object sharing.
DuckDB WAL ensures that committed writes are visible to any other connection
(within the process or via a ``READ_ONLY`` connection from another process)
without blocking.

Usage::

    from src.common.db_connections import get_connection

    conn = get_connection("market")   # market_data.duckdb
    conn = get_connection("portfolio")
    conn = get_connection("analysis")
    conn = get_connection("backtest")

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


# ── Public API ────────────────────────────────────────────────────────────────


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
    """Open and configure a new R/W WAL connection for *db_key*.

    WAL (Write-Ahead Log) is DuckDB's default durability mechanism.  Explicit
    ``wal_autocheckpoint`` keeps the WAL file from growing unbounded between
    checkpoints.

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

    try:
        # WAL is DuckDB's default durability mechanism — no extra PRAGMA needed.
        conn = duckdb.connect(str(abs_path))
        logger.info(
            f"[db_connections] opened {db_key} ({rel_path}) — R/W WAL"
        )
        return conn
    except duckdb.IOException as exc:
        raise RuntimeError(
            f"[db_connections] cannot open {db_key} ({abs_path}): {exc}\n"
            "Hint: another process may hold an exclusive write lock on this file. "
            "Ensure only one writer process is active per database file."
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


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("src/common/db_connections.py smoke test")
    print("=" * 60)

    # Use temp in-memory connections for the test (avoid touching live DBs)
    import tempfile, os

    tmp_files: dict[str, str] = {}
    orig_db_files = dict(_DB_FILES)

    try:
        for key in list(_DB_FILES.keys()):
            tmp = tempfile.mktemp(suffix=f"_{key}.duckdb")
            _DB_FILES[key] = tmp          # redirect to temp file
            tmp_files[key] = tmp

        # Test 1: get_connection returns same object on repeated calls
        c1 = get_connection("market")
        c2 = get_connection("market")
        assert c1 is c2, "Same object expected on second call"
        print("  [OK] get_connection returns singleton")

        # Test 2: write + read through shared connection
        c1.execute("CREATE TABLE test_t (x INT)")
        c1.execute("INSERT INTO test_t VALUES (42)")
        rows = c1.execute("SELECT x FROM test_t").fetchall()
        assert rows == [(42,)], f"Unexpected rows: {rows}"
        print("  [OK] write + read on shared connection")

        # Test 3: convenience aliases return same object
        assert get_market_conn() is c1
        print("  [OK] get_market_conn() alias works")

        # Test 4: different db_key → different connection
        cp = get_connection("portfolio")
        assert cp is not c1, "Different keys must give different connections"
        print("  [OK] different db_key → different connection")

        # Test 5: unknown key raises ValueError
        try:
            get_connection("nonexistent")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        print("  [OK] unknown db_key raises ValueError")

        # Test 6: close_all resets connections
        close_all()
        assert len(_connections) == 0, "Connections should be empty after close_all"
        print("  [OK] close_all() clears all connections")

        print("\n[ALL OK] db_connections.py smoke test passed")

    finally:
        _DB_FILES.update(orig_db_files)
        close_all()
        for tmp in tmp_files.values():
            for suffix in ("", ".wal"):
                p = tmp + suffix if not tmp.endswith(suffix) else tmp
                try:
                    os.unlink(p)
                except FileNotFoundError:
                    pass

    print("=" * 60)
