"""DAO for strategy optimization sessions and results.

Extends BacktestDAO to persist agentic optimizer runs in the same
backtest.duckdb database.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime
from typing import Dict, List, Optional

from src.common.dao.backtest_dao import BacktestDAO
from src.common.utils import get_logger

logger = get_logger(__name__)


class OptimizerDAO(BacktestDAO):
    """Data access layer for strategy optimization sessions.

    Inherits connection/transaction/schema utilities from BacktestDAO and
    writes to the same data/backtest.duckdb file.
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize OptimizerDAO and ensure optimizer schema exists.

        Args:
            db_path: Optional explicit path to DuckDB file. Defaults to
                backtest.duckdb via BacktestDAO.
        """
        super().__init__(db_path=db_path)
        self._initialize_optimizer_schema()

    def _initialize_optimizer_schema(self) -> None:
        """Execute optimizer_schema.sql if optimization_sessions table is absent."""
        schema_path = Path("config/schema/optimizer_schema.sql")
        if schema_path.exists():
            self.execute_schema_file(
                str(schema_path),
                check_table="optimization_sessions"
            )
            logger.debug("Optimizer schema check completed")
        else:
            logger.warning(f"Optimizer schema file not found: {schema_path}")

    # =========================================================================
    # Session Management
    # =========================================================================

    def create_session(
        self,
        session_id: str,
        ticker: str,
        start_date: str,
        end_date: str,
        goal: str,
        max_iterations: int,
    ) -> str:
        """Insert a new optimization session row.

        Args:
            session_id: UUID string for this session.
            ticker: Stock ticker symbol.
            start_date: Backtest start date (YYYY-MM-DD).
            end_date: Backtest end date (YYYY-MM-DD).
            goal: Optimization goal ("sharpe" | "total_return" | "profit_factor").
            max_iterations: Hard iteration cap.

        Returns:
            session_id: The same session_id that was passed in.
        """
        query = """
            INSERT INTO optimization_sessions (
                session_id, ticker, start_date, end_date, goal,
                max_iterations, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'running', ?)
        """
        self.execute(query, (
            session_id, ticker, start_date, end_date, goal,
            max_iterations, datetime.now()
        ))
        logger.info(f"[OptimizerDAO] Created session {session_id}: {ticker} goal={goal}")
        return session_id

    def save_result(
        self,
        session_id: str,
        candidate: Dict,
        iteration_num: int,
        metrics: Dict,
        status: str = "completed",
        llm_evaluation: Optional[str] = None,
    ) -> int:
        """Insert one backtest run result into optimization_results.

        Args:
            session_id: Parent session identifier.
            candidate: Candidate dict with strategy, z_score_entry, etc.
            iteration_num: 1-based iteration number within the session.
            metrics: Metrics dict from backtest result.
            status: "completed" or "failed".
            llm_evaluation: Optional quant_evaluator analysis text.

        Returns:
            result_id: Auto-generated row ID.
        """
        query = """
            INSERT INTO optimization_results (
                session_id, candidate_id, strategy,
                z_score_entry, z_score_exit, lookback, source,
                iteration_num,
                sharpe_ratio, total_return_pct, max_drawdown_pct,
                win_rate, profit_factor, total_trades,
                status, llm_evaluation, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.execute(query, (
            session_id,
            candidate.get("candidate_id", "unknown"),
            candidate.get("strategy", "unknown"),
            candidate.get("z_score_entry"),
            candidate.get("z_score_exit"),
            candidate.get("lookback"),
            candidate.get("source", "grid"),
            iteration_num,
            metrics.get("sharpe_ratio"),
            metrics.get("total_return_pct"),
            metrics.get("max_drawdown_pct"),
            metrics.get("win_rate"),
            metrics.get("profit_factor"),
            metrics.get("total_trades"),
            status,
            llm_evaluation,
            datetime.now()
        ))

        # Retrieve the generated result_id
        row = self.fetch_one(
            """
            SELECT result_id FROM optimization_results
            WHERE session_id = ? AND iteration_num = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (session_id, iteration_num)
        )
        result_id = row["result_id"] if row else -1
        logger.info(
            f"[OptimizerDAO] Saved result {result_id}: "
            f"session={session_id} iter={iteration_num} candidate={candidate.get('candidate_id')}"
        )
        return result_id

    def complete_session(
        self,
        session_id: str,
        iterations_run: int,
        early_stopped: bool,
        early_stop_reason: Optional[str],
        best_candidate_id: Optional[str],
        best_sharpe: Optional[float],
        best_return_pct: Optional[float],
        final_recommendation: Optional[str],
    ) -> None:
        """Mark an optimization session as completed with final metrics.

        Args:
            session_id: Session identifier.
            iterations_run: Number of backtest iterations executed.
            early_stopped: Whether the optimizer stopped before max_iterations.
            early_stop_reason: Reason for early stop (if any).
            best_candidate_id: Candidate ID of the winning run.
            best_sharpe: Sharpe ratio of the best run.
            best_return_pct: Total return % of the best run.
            final_recommendation: Full LLM recommendation text.
        """
        query = """
            UPDATE optimization_sessions
            SET
                status = 'completed',
                iterations_run = ?,
                early_stopped = ?,
                early_stop_reason = ?,
                best_candidate_id = ?,
                best_sharpe = ?,
                best_return_pct = ?,
                final_recommendation = ?,
                completed_at = ?
            WHERE session_id = ?
        """
        self.execute(query, (
            iterations_run, early_stopped, early_stop_reason,
            best_candidate_id, best_sharpe, best_return_pct,
            final_recommendation, datetime.now(), session_id
        ))
        logger.info(f"[OptimizerDAO] Completed session {session_id}: best={best_candidate_id}")

    def fail_session(self, session_id: str, error_msg: str) -> None:
        """Mark an optimization session as failed.

        Args:
            session_id: Session identifier.
            error_msg: Error message describing the failure.
        """
        query = """
            UPDATE optimization_sessions
            SET status = 'failed', early_stop_reason = ?, completed_at = ?
            WHERE session_id = ?
        """
        self.execute(query, (error_msg, datetime.now(), session_id))
        logger.error(f"[OptimizerDAO] Failed session {session_id}: {error_msg}")

    # =========================================================================
    # Queries
    # =========================================================================

    def get_session(self, session_id: str) -> Optional[Dict]:
        """Retrieve a full optimization session row.

        Args:
            session_id: Session identifier.

        Returns:
            Dict with session fields, or None if not found.
        """
        return self.fetch_one(
            "SELECT * FROM optimization_sessions WHERE session_id = ?",
            (session_id,)
        )

    def get_session_results(self, session_id: str) -> List[Dict]:
        """Retrieve all optimization result rows for a session in iteration order.

        Args:
            session_id: Session identifier.

        Returns:
            List of dicts ordered by iteration_num.
        """
        return self.fetch_all(
            """
            SELECT * FROM optimization_results
            WHERE session_id = ?
            ORDER BY iteration_num
            """,
            (session_id,)
        )

    def get_best_params(
        self,
        ticker: str,
        strategy: str = "mean-reversion",
        goal: str = "sharpe",
        limit: int = 5,
    ) -> List[Dict]:
        """Query best parameter sets for a ticker/strategy ordered by goal metric.

        Useful for seeding future optimizer runs with already-proven parameters.

        Args:
            ticker: Stock ticker symbol.
            strategy: Strategy name filter.
            goal: Metric to rank by ("sharpe" | "total_return" | "profit_factor").
            limit: Maximum rows to return.

        Returns:
            List of dicts with candidate params and metrics, best first.
        """
        goal_col_map = {
            "sharpe": "sharpe_ratio",
            "total_return": "total_return_pct",
            "profit_factor": "profit_factor",
        }
        order_col = goal_col_map.get(goal, "sharpe_ratio")

        return self.fetch_all(
            f"""
            SELECT
                r.candidate_id, r.strategy,
                r.z_score_entry, r.z_score_exit, r.lookback, r.source,
                r.sharpe_ratio, r.total_return_pct, r.max_drawdown_pct,
                r.win_rate, r.profit_factor, r.total_trades,
                s.ticker, s.goal
            FROM optimization_results r
            JOIN optimization_sessions s ON r.session_id = s.session_id
            WHERE s.ticker = ?
              AND r.strategy = ?
              AND r.status = 'completed'
              AND r.{order_col} IS NOT NULL
            ORDER BY r.{order_col} DESC
            LIMIT ?
            """,
            (ticker, strategy, limit)
        )


# =============================================================================
# Functional Testing
# =============================================================================

if __name__ == "__main__":
    import uuid as _uuid

    print("=" * 60)
    print("OptimizerDAO Functional Test")
    print("=" * 60)

    dao = OptimizerDAO()
    print("\n[OK] DAO initialized, optimizer schema loaded")

    # 1. Create session
    session_id = str(_uuid.uuid4())
    print(f"\n1. Creating session {session_id[:8]}...")
    dao.create_session(
        session_id=session_id,
        ticker="AAPL",
        start_date="2025-01-01",
        end_date="2025-03-01",
        goal="sharpe",
        max_iterations=6,
    )
    print("   [OK] Session created")

    # 2. Save result
    print("\n2. Saving optimization result...")
    result_id = dao.save_result(
        session_id=session_id,
        candidate={
            "candidate_id": "mr_2.0_0.5_20",
            "strategy": "mean-reversion",
            "z_score_entry": 2.0,
            "z_score_exit": 0.5,
            "lookback": 20,
            "source": "grid",
        },
        iteration_num=1,
        metrics={
            "sharpe_ratio": 1.42,
            "total_return_pct": 3.5,
            "max_drawdown_pct": -4.2,
            "win_rate": 0.62,
            "profit_factor": 1.9,
            "total_trades": 12,
        },
        llm_evaluation="Good Sharpe; acceptable drawdown; solid win rate.",
    )
    print(f"   [OK] Result saved: result_id={result_id}")

    # 3. Complete session
    print("\n3. Completing session...")
    dao.complete_session(
        session_id=session_id,
        iterations_run=1,
        early_stopped=False,
        early_stop_reason=None,
        best_candidate_id="mr_2.0_0.5_20",
        best_sharpe=1.42,
        best_return_pct=3.5,
        final_recommendation="STRONG CANDIDATE — deploy with 2% risk per trade.",
    )
    print("   [OK] Session completed")

    # 4. Retrieve session
    print("\n4. Retrieving session...")
    session = dao.get_session(session_id)
    print(f"   ticker={session['ticker']}  status={session['status']}  best={session['best_candidate_id']}")

    # 5. Retrieve results
    print("\n5. Retrieving session results...")
    results = dao.get_session_results(session_id)
    print(f"   Found {len(results)} result(s)")

    # 6. Get best params
    print("\n6. Getting best params for AAPL mean-reversion (sharpe)...")
    best = dao.get_best_params("AAPL", strategy="mean-reversion", goal="sharpe")
    print(f"   Found {len(best)} historical best run(s)")

    dao.close()
    print("\n" + "=" * 60)
    print("All OptimizerDAO tests passed! [SUCCESS]")
    print("=" * 60)
