"""ETL pipeline for pre-computing technical indicators and strategy signals.

This module orchestrates the computation of technical indicators and strategy
signals for all watchlist symbols across multiple timeframes. Pre-computed
results are stored in the database for fast retrieval by the quant agent.

All formulas are sourced from the quant skill singletons in
``src.server.skills.quant``, ensuring consistency with the function registry
and backtester (which also use those same singletons).
"""

import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd

from src.common.dao import AlpacaDAO
from src.common.utils import config, get_logger
from src.server.skills.quant import (
    momentum_skill,
    volatility_skill,
    volume_skill,
    candlestick_skill,
    mean_reversion_skill,
    vwap_reversion_skill,
    opening_range_breakout_skill,
    rsi_divergence_scalp_skill,
    momentum_burst_skill,
    golden_cross_skill,
    breakout_52w_skill,
    earnings_drift_skill,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Strategy routing — which strategies run on which timeframes.
# Singletons are used (not per-call instantiation) because:
#   - All skills are stateless DataFrame transformers with no mutable state.
#   - The expanding window loop calls each skill N times per symbol; re-using
#     shared instances avoids N × 12 unnecessary allocations.
#   - Matches the pattern already used in _fn_quant.py (function registry).
# ---------------------------------------------------------------------------

_INTRADAY_STRATEGIES: Dict[str, object] = {
    "vwap_reversion":         vwap_reversion_skill,
    "opening_range_breakout": opening_range_breakout_skill,
    "rsi_divergence_scalp":   rsi_divergence_scalp_skill,
    "momentum_burst":         momentum_burst_skill,
}

_DAILY_STRATEGIES: Dict[str, object] = {
    "golden_cross":   golden_cross_skill,
    "breakout_52w":   breakout_52w_skill,
    "earnings_drift": earnings_drift_skill,
}


def _strategies_for_timeframe(timeframe: str) -> Dict[str, object]:
    """Return the strategy map applicable to the given timeframe.

    Args:
        timeframe: Bar timeframe string (e.g. '1Min', '1Hour', '1Day').

    Returns:
        Dict mapping strategy name → skill singleton.
    """
    if timeframe in ("1Min", "1Hour"):
        return _INTRADAY_STRATEGIES
    if timeframe == "1Day":
        return _DAILY_STRATEGIES
    return {}


class IndicatorsETL:
    """ETL pipeline for computing and storing technical indicators and strategy signals.

    This pipeline:
    1. Fetches market bars from the database
    2. Calculates all technical indicators via quant skill singletons
    3. Flattens indicator results into rows (one per timestamp)
    4. Saves indicator rows to ``computed_indicators`` table
    5. Runs applicable strategy skills per timeframe
    6. Saves strategy signal rows to ``precomputed_strategy_signals`` table

    Can be run on-demand or scheduled (hourly) for all watchlist symbols.
    """

    def __init__(
        self,
        timeframes: Optional[List[str]] = None,
        lookback_days: int = 60,
    ):
        """Initialize ETL pipeline.

        Args:
            timeframes: List of timeframes to process. Defaults to config value
                or ``["1Min", "1Hour", "1Day"]``.
            lookback_days: Days of historical data to process. Defaults to 60.
        """
        self.timeframes = timeframes or config.get(
            "etl.timeframes",
            default=["1Min", "1Hour", "1Day"],
        )
        self.lookback_days = lookback_days
        self.dao = AlpacaDAO()

        logger.info(
            f"IndicatorsETL initialized: timeframes={self.timeframes}, "
            f"lookback_days={lookback_days}"
        )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def run_for_symbol(
        self,
        symbol: str,
        force_recalculate: bool = False,
    ) -> dict:
        """Run ETL for a single symbol across all configured timeframes.

        Args:
            symbol: Stock ticker symbol.
            force_recalculate: Reserved for future incremental logic; currently
                all data is (re)computed from the lookback window.

        Returns:
            Dict with per-timeframe row counts and any errors.
        """
        logger.info(f"Starting ETL for {symbol}")

        results: dict = {
            "symbol": symbol,
            "timeframes": {},
            "total_rows": 0,
            "errors": [],
        }

        for timeframe in self.timeframes:
            try:
                rows = self._process_timeframe(symbol, timeframe, force_recalculate)
                results["timeframes"][timeframe] = rows
                results["total_rows"] += rows
                logger.info(f"  {timeframe}: {rows} rows computed")
            except Exception as e:
                error_msg = f"Failed to process {timeframe}: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
                results["timeframes"][timeframe] = 0

        logger.info(
            f"Completed ETL for {symbol}: {results['total_rows']} total rows, "
            f"{len(results['errors'])} errors"
        )
        return results

    def run_for_watchlist(self) -> dict:
        """Run ETL for all symbols in the watchlist.

        Returns:
            Dict with per-symbol results and overall stats.
        """
        watchlist = self.dao.get_watchlist()
        if not watchlist:
            logger.warning("Watchlist is empty, nothing to process")
            return {"symbols": {}, "total_rows": 0, "errors": []}

        logger.info(f"Running ETL for {len(watchlist)} watchlist symbols")

        results: dict = {"symbols": {}, "total_rows": 0, "total_errors": 0}

        for symbol in watchlist:
            try:
                sym_result = self.run_for_symbol(symbol)
                results["symbols"][symbol] = sym_result
                results["total_rows"] += sym_result["total_rows"]
                results["total_errors"] += len(sym_result["errors"])
            except Exception as e:
                error_msg = f"Failed to process {symbol}: {e}"
                logger.error(error_msg)
                results["symbols"][symbol] = {
                    "symbol": symbol,
                    "timeframes": {},
                    "total_rows": 0,
                    "errors": [error_msg],
                }
                results["total_errors"] += 1

        logger.info(
            f"ETL complete: {results['total_rows']} total rows, "
            f"{results['total_errors']} errors across {len(watchlist)} symbols"
        )
        return results

    def close(self) -> None:
        """Close the database connection."""
        if self.dao:
            self.dao.close()

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _process_timeframe(
        self,
        symbol: str,
        timeframe: str,
        force_recalculate: bool,  # noqa: ARG002 — reserved
    ) -> int:
        """Process a single symbol-timeframe combination.

        Args:
            symbol: Stock ticker.
            timeframe: Timeframe string ('1Min', '1Hour', '1Day').
            force_recalculate: Reserved; currently unused.

        Returns:
            Total number of indicator + strategy signal rows written.
        """
        end = datetime.now()
        start = end - timedelta(days=self.lookback_days)

        df = self.dao.get_bars(symbol, start, end, timeframe)
        if df.empty:
            logger.warning(f"No bars data for {symbol} {timeframe}")
            return 0

        logger.debug(f"Processing {len(df)} bars for {symbol} {timeframe}")

        # --- Indicator rows ---------------------------------------------------
        indicator_rows = self._calculate_indicators_rolling(df, symbol, timeframe)
        rows_saved = 0
        if indicator_rows:
            indicators_df = pd.DataFrame(indicator_rows)
            rows_saved += self.dao.save_computed_indicators(indicators_df)

        # --- Strategy signal rows --------------------------------------------
        strategy_rows = self._calculate_strategy_signals_rolling(df, symbol, timeframe)
        if strategy_rows:
            signals_df = pd.DataFrame(strategy_rows)
            rows_saved += self.dao.save_strategy_signals(signals_df)

        return rows_saved

    def _calculate_indicators_rolling(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> List[dict]:
        """Calculate basic technical indicators for each timestamp (expanding window).

        Each iteration uses all bars up to index ``i``, matching what any
        skill would compute if run live at that timestamp.

        Args:
            df: Full OHLCV DataFrame for the symbol-timeframe.
            symbol: Stock ticker.
            timeframe: Timeframe string.

        Returns:
            List of flat indicator dicts (one per timestamp from bar 60 onward).
        """
        indicator_rows: List[dict] = []
        min_required = 60  # MeanReversionSkill needs at least 60 bars

        for i in range(min_required, len(df) + 1):
            window_df = df.iloc[:i].copy()
            try:
                indicators = {
                    "momentum":       momentum_skill.analyze_bars(window_df),
                    "volatility":     volatility_skill.analyze_bars(window_df),
                    "volume":         volume_skill.analyze_bars(window_df),
                    "candlestick":    candlestick_skill.analyze_bars(window_df),
                    "mean_reversion": mean_reversion_skill.analyze_bars(window_df),
                }
                timestamp = window_df["timestamp"].iloc[-1]
                row = self._flatten_indicators(symbol, timestamp, timeframe, indicators)
                indicator_rows.append(row)
            except Exception as e:
                logger.debug(f"Error calculating indicators at index {i}: {e}")

        return indicator_rows

    def _flatten_indicators(
        self,
        symbol: str,
        timestamp: pd.Timestamp,
        timeframe: str,
        indicators: dict,
    ) -> dict:
        """Flatten nested skill output dicts into a single ``computed_indicators`` row.

        Args:
            symbol: Stock ticker.
            timestamp: Bar timestamp.
            timeframe: Timeframe string.
            indicators: Dict keyed by skill category, each value the skill's output dict.

        Returns:
            Flat dict matching the ``computed_indicators`` table schema.
        """
        momentum = indicators.get("momentum", {})
        macd = momentum.get("macd") or {}
        volatility = indicators.get("volatility", {})
        volume = indicators.get("volume", {})
        candle = indicators.get("candlestick", {})

        # MeanReversionSkill.analyze_bars() returns a nested structure:
        # z_score / percentile / vwap live under result["statistics"], not top-level.
        mean_rev = indicators.get("mean_reversion", {})
        stats = mean_rev.get("statistics") or {}

        return {
            "symbol":    symbol,
            "timestamp": timestamp,
            "timeframe": timeframe,
            # Momentum
            "macd_value":      macd.get("value"),
            "macd_signal":     macd.get("signal"),
            "macd_histogram":  macd.get("histogram"),
            "rsi":             momentum.get("rsi"),
            # Volatility
            "bb_upper":     volatility.get("upper"),
            "bb_middle":    volatility.get("middle"),
            "bb_lower":     volatility.get("lower"),
            "bb_bandwidth": volatility.get("bandwidth"),
            # Volume
            "obv":             volume.get("obv"),
            "volume_trend":    volume.get("volume_trend"),
            "avg_volume_10d":  volume.get("avg_volume_10d"),
            "current_vs_avg":  volume.get("current_vs_avg"),
            # Mean reversion — nested under "statistics"
            "z_score":    stats.get("z_score"),
            "percentile": stats.get("percentile"),
            "vwap":       stats.get("vwap"),
            # Candlestick — new columns
            "candle_patterns":  json.dumps(candle.get("patterns", [])),
            "last_candle_type": candle.get("last_candle_type"),
            "last_body_pct":    candle.get("last_body_pct"),
            "pattern_count":    candle.get("pattern_count"),
        }

    def _calculate_strategy_signals_rolling(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> List[dict]:
        """Calculate strategy signals for each timestamp (expanding window).

        Only runs strategies applicable to the given timeframe (see
        ``_strategies_for_timeframe``). If a strategy returns an error
        (e.g. insufficient bars), action="hold" / confidence=0 is stored.

        Args:
            df: Full OHLCV DataFrame.
            symbol: Stock ticker.
            timeframe: Timeframe string.

        Returns:
            List of strategy signal dicts for ``precomputed_strategy_signals``.
        """
        strategies = _strategies_for_timeframe(timeframe)
        if not strategies:
            return []

        signal_rows: List[dict] = []
        min_required = 60  # consistent with indicator min

        for i in range(min_required, len(df) + 1):
            window_df = df.iloc[:i].copy()
            timestamp = window_df["timestamp"].iloc[-1]

            for name, skill in strategies.items():
                try:
                    result = skill.analyze_bars(window_df)
                except Exception as e:
                    logger.debug(f"Strategy {name} error at index {i}: {e}")
                    result = {}

                # Strategy skills return action/confidence at top level;
                # MeanReversionSkill nests them under trade_recommendation.
                rec = result.get("trade_recommendation", {})
                signal_rows.append({
                    "symbol":       symbol,
                    "timestamp":    timestamp,
                    "timeframe":    timeframe,
                    "strategy_name": name,
                    "action":       result.get("action") or rec.get("action", "hold"),
                    "confidence":   result.get("confidence") if result.get("confidence") is not None
                                    else rec.get("confidence", 0.0),
                    "reason":       result.get("reason") or rec.get("reason"),
                    "entry_price":  result.get("entry_price") or rec.get("entry_price"),
                    "stop_loss":    result.get("stop_loss") or rec.get("stop_loss"),
                    "take_profit":  result.get("take_profit") or rec.get("take_profit"),
                })

        return signal_rows


if __name__ == "__main__":
    """Run ETL pipeline for testing."""
    import argparse

    parser = argparse.ArgumentParser(description="Run technical indicators ETL pipeline")
    parser.add_argument("--symbol", type=str, help="Single symbol to process (default: all watchlist)")
    parser.add_argument(
        "--timeframes", nargs="+", default=["1Min", "1Hour", "1Day"],
        help="Timeframes to process (default: 1Min 1Hour 1Day)",
    )
    parser.add_argument("--lookback-days", type=int, default=60, help="Days of historical data (default: 60)")
    parser.add_argument("--force", action="store_true", help="Force recalculation of all data")
    args = parser.parse_args()

    print("=" * 60)
    print("Technical Indicators ETL Pipeline")
    print("=" * 60)

    etl = IndicatorsETL(timeframes=args.timeframes, lookback_days=args.lookback_days)

    try:
        if args.symbol:
            print(f"\nProcessing {args.symbol}...")
            results = etl.run_for_symbol(args.symbol, force_recalculate=args.force)
            print(f"\nCompleted: {results['total_rows']} indicator rows computed")
            if results["errors"]:
                print(f"\nErrors: {len(results['errors'])}")
                for error in results["errors"]:
                    print(f"  - {error}")
        else:
            print("\nProcessing watchlist...")
            results = etl.run_for_watchlist()
            print(f"\nCompleted: {results['total_rows']} total indicator rows")
            print(f"  Symbols processed: {len(results['symbols'])}")
            if results["total_errors"] > 0:
                print(f"\nTotal errors: {results['total_errors']}")
    except Exception as e:
        print(f"\nETL failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        etl.close()

    print("\n" + "=" * 60)
