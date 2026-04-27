"""DAO for analysis.duckdb — analyst EOD summaries and strategy signal results."""

import json
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
from src.common.dao.base_dao import BaseDAO
from src.common.utils import get_logger

logger = get_logger(__name__)


class AnalysisDAO(BaseDAO):
    """Data access layer for analysis.duckdb.

    Covers two concerns that share the same database and writer process (ETL):

    - **Analyst summaries**: LLM-generated EOD narratives per symbol
      (``analyst_summaries`` table).
    - **Strategy results**: per-strategy signal rows with indicators, confidence,
      and agent reasoning (``strategy_results`` table).
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialise AnalysisDAO.

        Args:
            db_path: Override database path. If None uses analysis.duckdb.
        """
        super().__init__(db_path=db_path, db_type="analysis")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables from the canonical schema file if they do not exist."""
        schema_file = project_root / "config" / "schema" / "analysis_schema.sql"
        self.execute_schema_file(str(schema_file), check_table="analyst_summaries")
        logger.debug("Analysis schema check completed")

    # -------------------------------------------------------------------------
    # Analyst summaries
    # -------------------------------------------------------------------------

    def save_eod_summary(
        self,
        symbol: str,
        timestamp: datetime,
        indicators: Dict,
        summary_text: str,
        signals: Dict,
        thought_trace: Optional[str] = None,
        model_used: Optional[str] = None,
        token_count: Optional[int] = None,
    ) -> int:
        """Upsert an end-of-day analyst summary for a symbol.

        Args:
            symbol: Stock ticker (e.g. ``"AAPL"``).
            timestamp: EOD timestamp (typically 4:01 PM ET).
            indicators: Final indicator values for the day.
            summary_text: LLM-generated comprehensive daily analysis.
            signals: Structured signals dict (momentum, volatility, volume_trend).
            thought_trace: Agent reasoning and decision process.
            model_used: LLM model identifier.
            token_count: Tokens consumed.

        Returns:
            Number of rows inserted/updated.
        """
        data = pd.DataFrame([{
            "symbol": symbol,
            "timestamp": timestamp,
            "date_only": timestamp.date(),
            "indicators": json.dumps(indicators),
            "summary_text": summary_text,
            "signals": json.dumps(signals),
            "thought_trace": thought_trace,
            "model_used": model_used,
            "token_count": token_count,
        }])
        rows = self.upsert_df(table="analyst_summaries", df=data, key_columns=["symbol", "date_only"])
        logger.info(f"[AnalysisDAO] saved EOD summary for {symbol} at {timestamp}")
        return rows

    def get_eod_summaries(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        """Fetch EOD summaries for a symbol within a date range.

        Args:
            symbol: Stock ticker.
            start_date: Inclusive start date.
            end_date: Inclusive end date.

        Returns:
            DataFrame sorted by timestamp descending, JSON columns parsed.
        """
        df = self.fetch_df(
            """
            SELECT * FROM analyst_summaries
            WHERE symbol = ?
              AND DATE(timestamp) >= ?
              AND DATE(timestamp) <= ?
            ORDER BY timestamp DESC
            """,
            [symbol, start_date, end_date],
        )
        if not df.empty:
            df["indicators"] = df["indicators"].apply(json.loads)
            df["signals"] = df["signals"].apply(json.loads)
        return df

    def get_latest_eod(self, symbol: str) -> Optional[Dict]:
        """Fetch the most recent EOD summary for a symbol.

        Args:
            symbol: Stock ticker.

        Returns:
            Row dict with parsed JSON fields, or None if no summary exists.
        """
        df = self.fetch_df(
            "SELECT * FROM analyst_summaries WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            [symbol],
        )
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        row["indicators"] = json.loads(row["indicators"])
        row["signals"] = json.loads(row["signals"])
        return row

    def get_recent_eods(self, symbol: str, count: int = 5) -> List[Dict]:
        """Fetch the N most recent EOD summaries for a symbol.

        Args:
            symbol: Stock ticker.
            count: Maximum rows to return.

        Returns:
            List of row dicts with parsed JSON fields.
        """
        df = self.fetch_df(
            "SELECT * FROM analyst_summaries WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
            [symbol, count],
        )
        if df.empty:
            return []
        df["indicators"] = df["indicators"].apply(json.loads)
        df["signals"] = df["signals"].apply(json.loads)
        return df.to_dict("records")

    def get_all_symbols(self) -> List[str]:
        """Return all symbols that have at least one EOD summary.

        Returns:
            Sorted list of ticker symbols.
        """
        df = self.fetch_df("SELECT DISTINCT symbol FROM analyst_summaries ORDER BY symbol")
        return df["symbol"].tolist() if not df.empty else []

    # -------------------------------------------------------------------------
    # Strategy results
    # -------------------------------------------------------------------------

    def save_strategy_result(
        self,
        symbol: str,
        strategy_name: str,
        current_price: float,
        statistics: Dict,
        indicators: Dict,
        signals: Dict,
        action: str,
        confidence: float,
        reason: str,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        support_level: Optional[float] = None,
        resistance_level: Optional[float] = None,
        current_state: Optional[str] = None,
        thought_trace: Optional[str] = None,
        model_used: str = "gpt-4",
        parameters: Optional[Dict] = None,
        timeframe: str = "1Day",
    ) -> bool:
        """Insert a strategy signal result row.

        Args:
            symbol: Stock ticker.
            strategy_name: Strategy identifier (e.g. ``"mean-reversion"``).
            current_price: Price at analysis time.
            statistics: Statistical measures dict.
            indicators: Technical indicators dict.
            signals: Trading signals dict.
            action: ``"buy"``, ``"sell"``, or ``"hold"``.
            confidence: 0.0–1.0 confidence score.
            reason: Human-readable explanation.
            entry_price: Recommended entry price.
            stop_loss: Stop-loss price.
            take_profit: Take-profit price.
            support_level: Support level.
            resistance_level: Resistance level.
            current_state: Market state label.
            thought_trace: Agent reasoning text.
            model_used: LLM model identifier.
            parameters: Strategy parameters used.
            timeframe: Analysis timeframe.

        Returns:
            True on success, False on error.
        """
        try:
            self.execute(
                """
                INSERT INTO strategy_results (
                    symbol, strategy_name, timestamp, current_price, timeframe,
                    statistics, indicators, current_state, signals,
                    action, confidence, reason,
                    entry_price, stop_loss, take_profit,
                    support_level, resistance_level,
                    thought_trace, model_used, parameters
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol, strategy_name, datetime.now(), current_price, timeframe,
                    json.dumps(statistics), json.dumps(indicators), current_state, json.dumps(signals),
                    action, confidence, reason,
                    entry_price, stop_loss, take_profit,
                    support_level, resistance_level,
                    thought_trace, model_used,
                    json.dumps(parameters) if parameters else None,
                ),
            )
            logger.info(f"[AnalysisDAO] {strategy_name} {symbol}: {action} ({confidence:.2f})")
            return True
        except Exception as exc:
            logger.error(f"[AnalysisDAO] save_strategy_result failed: {exc}", exc_info=True)
            return False

    def get_latest_signal(self, symbol: str, strategy_name: str) -> Optional[Dict]:
        """Fetch the most recent signal for a symbol+strategy pair.

        Args:
            symbol: Stock ticker.
            strategy_name: Strategy name.

        Returns:
            Row dict with parsed JSON fields, or None.
        """
        result = self.fetch_one(
            "SELECT * FROM strategy_results WHERE symbol = ? AND strategy_name = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (symbol, strategy_name),
        )
        if result:
            result["statistics"] = json.loads(result.get("statistics") or "{}")
            result["indicators"] = json.loads(result.get("indicators") or "{}")
            result["signals"] = json.loads(result.get("signals") or "{}")
            raw = result.get("parameters")
            result["parameters"] = json.loads(raw) if raw else None
        return result

    def get_recent_signals(self, symbol: str, strategy_name: str, limit: int = 10) -> pd.DataFrame:
        """Fetch recent signals for a symbol+strategy pair.

        Args:
            symbol: Stock ticker.
            strategy_name: Strategy name.
            limit: Maximum rows.

        Returns:
            DataFrame sorted by timestamp descending.
        """
        return self.fetch_df(
            "SELECT * FROM strategy_results WHERE symbol = ? AND strategy_name = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (symbol, strategy_name, limit),
        )

    def get_actionable_signals(
        self,
        min_confidence: float = 0.7,
        action_filter: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch high-confidence buy/sell signals.

        Args:
            min_confidence: Minimum confidence threshold.
            action_filter: Restrict to ``"buy"`` or ``"sell"``; None returns both.

        Returns:
            DataFrame sorted by timestamp and confidence descending.
        """
        if action_filter:
            return self.fetch_df(
                "SELECT * FROM strategy_results WHERE action = ? AND confidence >= ? "
                "ORDER BY timestamp DESC, confidence DESC LIMIT 50",
                (action_filter, min_confidence),
            )
        return self.fetch_df(
            "SELECT * FROM strategy_results WHERE action IN ('buy', 'sell') AND confidence >= ? "
            "ORDER BY timestamp DESC, confidence DESC LIMIT 50",
            (min_confidence,),
        )

    def get_actionable_signals_by_time(
        self,
        min_confidence: float = 0.65,
        lookback_minutes: int = 30,
        action_filter: Optional[str] = None,
    ) -> List[Dict]:
        """Fetch actionable signals generated within a lookback window.

        Args:
            min_confidence: Minimum confidence threshold.
            lookback_minutes: Time window to look back.
            action_filter: Restrict to ``"buy"`` or ``"sell"``; None returns both.

        Returns:
            List of row dicts with parsed JSON fields.
        """
        cutoff = datetime.now() - timedelta(minutes=lookback_minutes)
        if action_filter:
            df = self.fetch_df(
                "SELECT * FROM strategy_results WHERE action = ? AND confidence >= ? "
                "AND timestamp >= ? ORDER BY timestamp DESC, confidence DESC",
                (action_filter, min_confidence, cutoff),
            )
        else:
            df = self.fetch_df(
                "SELECT * FROM strategy_results WHERE action IN ('buy', 'sell') "
                "AND confidence >= ? AND timestamp >= ? "
                "ORDER BY timestamp DESC, confidence DESC",
                (min_confidence, cutoff),
            )
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            r = row.to_dict()
            r["statistics"] = json.loads(r.get("statistics") or "{}")
            r["indicators"] = json.loads(r.get("indicators") or "{}")
            r["signals"] = json.loads(r.get("signals") or "{}")
            raw = r.get("parameters")
            r["parameters"] = json.loads(raw) if raw else None
            results.append(r)
        return results

    def get_strategy_performance(self, strategy_name: str, days: int = 30) -> Dict:
        """Aggregate performance statistics for a strategy over N days.

        Args:
            strategy_name: Strategy name.
            days: Lookback window in days.

        Returns:
            Dict with total_signals, buy/sell/hold counts, confidence stats.
        """
        cutoff = datetime.now() - timedelta(days=days)
        result = self.fetch_one(
            """
            SELECT
                COUNT(*) as total_signals,
                SUM(CASE WHEN action = 'buy'  THEN 1 ELSE 0 END) as buy_signals,
                SUM(CASE WHEN action = 'sell' THEN 1 ELSE 0 END) as sell_signals,
                SUM(CASE WHEN action = 'hold' THEN 1 ELSE 0 END) as hold_signals,
                AVG(confidence) as avg_confidence,
                MAX(confidence) as max_confidence,
                MIN(confidence) as min_confidence
            FROM strategy_results
            WHERE strategy_name = ? AND timestamp >= ?
            """,
            (strategy_name, cutoff),
        )
        return result if result else {}


if __name__ == "__main__":
    dao = AnalysisDAO(db_path=":memory:")
    print("AnalysisDAO smoke test — in-memory DB")
    ok = dao.save_strategy_result(
        symbol="AAPL", strategy_name="test", current_price=150.0,
        statistics={}, indicators={}, signals={},
        action="buy", confidence=0.8, reason="test",
    )
    assert ok, "save_strategy_result failed"
    sig = dao.get_latest_signal("AAPL", "test")
    assert sig and sig["action"] == "buy"
    print("[OK] strategy result round-trip")
    dao.close()
    print("[ALL OK]")
