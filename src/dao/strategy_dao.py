"""Strategy DAO for storing trading strategy results.

Handles persistence of strategy execution results including:
- Signals and recommendations
- Statistical measures and indicators
- Agent reasoning and thought traces
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import json
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

from src.dao.base_dao import BaseDAO
from src.utils import get_logger

logger = get_logger(__name__)


class StrategyDAO(BaseDAO):
    """DAO for trading strategy results."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize StrategyDAO and create schema.
        
        Args:
            db_path: Optional path to DuckDB database file. If None, uses default from config.
        """
        super().__init__(db_path=db_path)
        self._initialize_schema()
        logger.info("Strategy schema initialized")

    def _initialize_schema(self):
        """Create strategy_results table if it doesn't exist."""
        schema_file = Path(__file__).parent.parent.parent / "config" / "schema" / "strategy_schema.sql"
        # Only execute if strategy_results table doesn't exist
        self.execute_schema_file(str(schema_file), check_table="strategy_results")

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
        timeframe: str = "1Day"
    ) -> bool:
        """Save strategy execution result.

        Args:
            symbol: Stock ticker symbol
            strategy_name: Name of strategy (e.g., 'mean-reversion')
            current_price: Current stock price
            statistics: Statistical measures dict
            indicators: Technical indicators dict
            signals: Trading signals dict
            action: Trading action ('buy', 'sell', 'hold')
            confidence: Confidence level (0.0 to 1.0)
            reason: Human-readable explanation
            entry_price: Recommended entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            support_level: Support level
            resistance_level: Resistance level
            current_state: Current market state
            thought_trace: Agent reasoning process
            model_used: LLM model identifier
            parameters: Strategy parameters used
            timeframe: Timeframe for analysis

        Returns:
            True if successful, False otherwise
        """
        try:
            query = """
                INSERT INTO strategy_results (
                    symbol, strategy_name, timestamp, current_price, timeframe,
                    statistics, indicators, current_state, signals,
                    action, confidence, reason,
                    entry_price, stop_loss, take_profit,
                    support_level, resistance_level,
                    thought_trace, model_used, parameters
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            params = (
                symbol,
                strategy_name,
                datetime.now(),
                current_price,
                timeframe,
                json.dumps(statistics),
                json.dumps(indicators),
                current_state,
                json.dumps(signals),
                action,
                confidence,
                reason,
                entry_price,
                stop_loss,
                take_profit,
                support_level,
                resistance_level,
                thought_trace,
                model_used,
                json.dumps(parameters) if parameters else None
            )

            self.execute(query, params)
            logger.info(
                f"Saved {strategy_name} result for {symbol}: {action} "
                f"(confidence: {confidence:.2f})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to save strategy result: {e}", exc_info=True)
            return False

    def get_latest_signal(
        self,
        symbol: str,
        strategy_name: str
    ) -> Optional[Dict]:
        """Get most recent signal for a symbol and strategy.

        Args:
            symbol: Stock ticker symbol
            strategy_name: Strategy name

        Returns:
            Dict with latest signal data or None
        """
        query = """
            SELECT * FROM strategy_results
            WHERE symbol = ? AND strategy_name = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """

        result = self.fetch_one(query, (symbol, strategy_name))

        if result:
            # Parse JSON fields, guarding against NULL/None values  
            result['statistics'] = json.loads(result.get('statistics') or '{}')  
            result['indicators'] = json.loads(result.get('indicators') or '{}')  
            result['signals'] = json.loads(result.get('signals') or '{}')  
            raw_parameters = result.get('parameters')  
            result['parameters'] = json.loads(raw_parameters) if raw_parameters else None 

        return result

    def get_recent_signals(
        self,
        symbol: str,
        strategy_name: str,
        limit: int = 10
    ) -> pd.DataFrame:
        """Get recent signals for a symbol and strategy.

        Args:
            symbol: Stock ticker symbol
            strategy_name: Strategy name
            limit: Number of recent signals to retrieve

        Returns:
            DataFrame with recent signals
        """
        query = """
            SELECT * FROM strategy_results
            WHERE symbol = ? AND strategy_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """

        return self.fetch_df(query, (symbol, strategy_name, limit))

    def get_actionable_signals(
        self,
        min_confidence: float = 0.7,
        action_filter: Optional[str] = None
    ) -> pd.DataFrame:
        """Get high-confidence actionable signals.

        Args:
            min_confidence: Minimum confidence threshold (default 0.7)
            action_filter: Filter by action ('buy' or 'sell'), None for both

        Returns:
            DataFrame with actionable signals
        """
        if action_filter:
            query = """
                SELECT * FROM strategy_results
                WHERE action = ? AND confidence >= ?
                ORDER BY timestamp DESC, confidence DESC
                LIMIT 50
            """
            params = (action_filter, min_confidence)
        else:
            query = """
                SELECT * FROM strategy_results
                WHERE action IN ('buy', 'sell') AND confidence >= ?
                ORDER BY timestamp DESC, confidence DESC
                LIMIT 50
            """
            params = (min_confidence,)

        return self.fetch_df(query, params)

    def get_strategy_performance(
        self,
        strategy_name: str,
        days: int = 30
    ) -> Dict:
        """Get strategy performance statistics.

        Args:
            strategy_name: Strategy name
            days: Number of days to analyze

        Returns:
            Dict with performance metrics
        """
        # Calculate cutoff date
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)

        query = """
            SELECT
                COUNT(*) as total_signals,
                SUM(CASE WHEN action = 'buy' THEN 1 ELSE 0 END) as buy_signals,
                SUM(CASE WHEN action = 'sell' THEN 1 ELSE 0 END) as sell_signals,
                SUM(CASE WHEN action = 'hold' THEN 1 ELSE 0 END) as hold_signals,
                AVG(confidence) as avg_confidence,
                MAX(confidence) as max_confidence,
                MIN(confidence) as min_confidence
            FROM strategy_results
            WHERE strategy_name = ?
              AND timestamp >= ?
        """

        result = self.fetch_one(query, (strategy_name, cutoff))
        return result if result else {}


if __name__ == "__main__":
    """Test StrategyDAO."""
    print("="*60)
    print("Testing StrategyDAO")
    print("="*60)

    dao = StrategyDAO()

    # Test 1: Save strategy result
    print("\n[1/4] Testing save_strategy_result...")
    success = dao.save_strategy_result(
        symbol="AAPL",
        strategy_name="mean-reversion",
        current_price=150.25,
        statistics={"mean": 148.50, "std_dev": 2.35, "z_score": 0.74},
        indicators={"sma_20": 148.75, "sma_50": 147.80},
        signals={"overall_signal": "hold", "z_score_signal": "neutral"},
        action="hold",
        confidence=0.65,
        reason="Price within normal range",
        current_state="neutral",
        parameters={"lookback": 60, "threshold": 2.0}
    )
    print(f"OK: Strategy result saved: {success}")

    # Test 2: Get latest signal
    print("\n[2/4] Testing get_latest_signal...")
    latest = dao.get_latest_signal("AAPL", "mean-reversion")
    if latest:
        print(f"OK: Latest signal - Action: {latest['action']}, Confidence: {latest['confidence']}")
    else:
        print("OK: No signals found")

    # Test 3: Get recent signals
    print("\n[3/4] Testing get_recent_signals...")
    recent = dao.get_recent_signals("AAPL", "mean-reversion", limit=5)
    print(f"OK: Retrieved {len(recent)} recent signals")

    # Test 4: Get strategy performance
    print("\n[4/4] Testing get_strategy_performance...")
    perf = dao.get_strategy_performance("mean-reversion", days=30)
    if perf:
        print(f"OK: Performance - Total signals: {perf.get('total_signals', 0)}")
    else:
        print("OK: No performance data yet")

    dao.close()

    print("\n" + "="*60)
    print("StrategyDAO tests complete!")
    print("="*60)
