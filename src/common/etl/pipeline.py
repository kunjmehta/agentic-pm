"""ETL pipeline for pre-computing technical indicators.

This module orchestrates the computation of technical indicators for all watchlist
symbols across multiple timeframes. Pre-computed indicators are stored in the
database for fast retrieval by the quant agent.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime, timedelta
from typing import List, Optional
import pandas as pd

from src.common.dao import AlpacaDAO
from src.common.etl.indicators_engine import IndicatorsEngine
from src.common.utils import config, get_logger


# Initialize logger
logger = get_logger(__name__)


class IndicatorsETL:
    """ETL pipeline for computing and storing technical indicators.

    This pipeline:
    1. Fetches market bars from database
    2. Calculates all technical indicators using IndicatorsEngine
    3. Flattens results into rows (one per timestamp)
    4. Saves to computed_indicators table

    Can be run on-demand or scheduled (hourly) for all watchlist symbols.
    """

    def __init__(
        self,
        timeframes: Optional[List[str]] = None,
        lookback_days: int = 60
    ):
        """Initialize ETL pipeline.

        Args:
            timeframes: List of timeframes to process (default from config)
            lookback_days: Days of historical data to process (default: 60)
        """
        self.timeframes = timeframes or config.get(
            "etl.timeframes",
            default=["1Min", "1Hour", "1Day"]
        )
        self.lookback_days = lookback_days
        self.dao = AlpacaDAO()
        self.engine = IndicatorsEngine()

        logger.info(
            f"IndicatorsETL initialized: timeframes={self.timeframes}, "
            f"lookback_days={lookback_days}"
        )

    def run_for_symbol(
        self,
        symbol: str,
        force_recalculate: bool = False
    ) -> dict:
        """Run ETL for a single symbol across all timeframes.

        Args:
            symbol: Stock ticker symbol
            force_recalculate: If True, recalculates all data; if False, only calculates new data

        Returns:
            Dict with results per timeframe (rows_computed, errors)
        """
        logger.info(f"Starting ETL for {symbol}")

        results = {
            'symbol': symbol,
            'timeframes': {},
            'total_rows': 0,
            'errors': []
        }

        for timeframe in self.timeframes:
            try:
                rows = self._process_timeframe(symbol, timeframe, force_recalculate)
                results['timeframes'][timeframe] = rows
                results['total_rows'] += rows
                logger.info(f"  {timeframe}: {rows} rows computed")

            except Exception as e:
                error_msg = f"Failed to process {timeframe}: {str(e)}"
                logger.error(error_msg)
                results['errors'].append(error_msg)
                results['timeframes'][timeframe] = 0

        logger.info(
            f"Completed ETL for {symbol}: {results['total_rows']} total rows, "
            f"{len(results['errors'])} errors"
        )

        return results

    def _process_timeframe(
        self,
        symbol: str,
        timeframe: str,
        force_recalculate: bool
    ) -> int:
        """Process a single symbol-timeframe combination.

        Args:
            symbol: Stock ticker
            timeframe: Timeframe string ('1Min', '1Hour', '1Day')
            force_recalculate: Whether to recalculate all data

        Returns:
            Number of indicator rows computed
        """
        # Determine date range
        end = datetime.now()
        start = end - timedelta(days=self.lookback_days)

        # Fetch bars
        df = self.dao.get_bars(symbol, start, end, timeframe)

        if df.empty:
            logger.warning(f"No bars data for {symbol} {timeframe}")
            return 0

        logger.debug(f"Processing {len(df)} bars for {symbol} {timeframe}")

        # Calculate indicators for each bar (rolling window)
        indicator_rows = self._calculate_indicators_rolling(df, symbol, timeframe)

        if not indicator_rows:
            logger.warning(f"No indicators computed for {symbol} {timeframe}")
            return 0

        # Convert to DataFrame and save
        indicators_df = pd.DataFrame(indicator_rows)
        rows_saved = self.dao.save_computed_indicators(indicators_df)

        return rows_saved

    def _calculate_indicators_rolling(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str
    ) -> List[dict]:
        """Calculate indicators for each timestamp using rolling windows.

        This calculates indicators at each timestamp using all prior data,
        not just the last value.

        Args:
            df: DataFrame with OHLCV data
            symbol: Stock ticker
            timeframe: Timeframe string

        Returns:
            List of indicator dictionaries (one per timestamp)
        """
        indicator_rows = []

        # Minimum data required for calculations
        min_required = 60  # Need at least 60 bars for mean reversion

        # Process each timestamp (using expanding window)
        for i in range(min_required, len(df) + 1):
            # Get data up to this point
            window_df = df.iloc[:i].copy()

            # Calculate all indicators
            try:
                indicators = self.engine.calc_all(window_df)

                # Extract last timestamp
                timestamp = window_df['timestamp'].iloc[-1]

                # Flatten indicators into a single row
                row = self._flatten_indicators(
                    symbol,
                    timestamp,
                    timeframe,
                    indicators
                )

                indicator_rows.append(row)

            except Exception as e:
                logger.debug(f"Error calculating indicators at index {i}: {e}")
                continue

        return indicator_rows

    def _flatten_indicators(
        self,
        symbol: str,
        timestamp: pd.Timestamp,
        timeframe: str,
        indicators: dict
    ) -> dict:
        """Flatten nested indicators dict into a single row for database.

        Args:
            symbol: Stock ticker
            timestamp: Bar timestamp
            timeframe: Timeframe string
            indicators: Nested dict from IndicatorsEngine.calc_all()

        Returns:
            Flat dict matching computed_indicators table schema
        """
        # Extract momentum
        momentum = indicators.get('momentum', {})
        macd = momentum.get('macd', {})

        # Extract volatility
        volatility = indicators.get('volatility', {})

        # Extract volume
        volume = indicators.get('volume', {})

        # Extract mean reversion
        mean_rev = indicators.get('mean_reversion', {})

        # Build flat row
        row = {
            'symbol': symbol,
            'timestamp': timestamp,
            'timeframe': timeframe,

            # Momentum indicators
            'macd_value': macd.get('value') if macd else None,
            'macd_signal': macd.get('signal') if macd else None,
            'macd_histogram': macd.get('histogram') if macd else None,
            'rsi': momentum.get('rsi'),

            # Volatility indicators
            'bb_upper': volatility.get('upper'),
            'bb_middle': volatility.get('middle'),
            'bb_lower': volatility.get('lower'),
            'bb_bandwidth': volatility.get('bandwidth'),

            # Volume indicators
            'obv': volume.get('obv'),
            'volume_trend': volume.get('volume_trend'),
            'avg_volume_10d': volume.get('avg_volume_10d'),
            'current_vs_avg': volume.get('current_vs_avg'),

            # Mean reversion indicators
            'z_score': mean_rev.get('z_score'),
            'percentile': mean_rev.get('percentile'),
            'vwap': mean_rev.get('vwap')
        }

        return row

    def run_for_watchlist(self) -> dict:
        """Run ETL for all symbols in the watchlist.

        Returns:
            Dict with results per symbol and overall stats
        """
        # Get watchlist
        watchlist = self.dao.get_watchlist()

        if not watchlist:
            logger.warning("Watchlist is empty, nothing to process")
            return {'symbols': {}, 'total_rows': 0, 'errors': []}

        logger.info(f"Running ETL for {len(watchlist)} watchlist symbols")

        results = {
            'symbols': {},
            'total_rows': 0,
            'total_errors': 0
        }

        for symbol in watchlist:
            try:
                symbol_result = self.run_for_symbol(symbol)
                results['symbols'][symbol] = symbol_result
                results['total_rows'] += symbol_result['total_rows']
                results['total_errors'] += len(symbol_result['errors'])

            except Exception as e:
                error_msg = f"Failed to process {symbol}: {str(e)}"
                logger.error(error_msg)
                results['symbols'][symbol] = {
                    'symbol': symbol,
                    'timeframes': {},
                    'total_rows': 0,
                    'errors': [error_msg]
                }
                results['total_errors'] += 1

        logger.info(
            f"ETL complete: {results['total_rows']} total rows, "
            f"{results['total_errors']} errors across {len(watchlist)} symbols"
        )

        return results

    def close(self):
        """Close database connection."""
        if self.dao:
            self.dao.close()


if __name__ == "__main__":
    """Run ETL pipeline for testing."""
    import argparse

    parser = argparse.ArgumentParser(description='Run technical indicators ETL pipeline')
    parser.add_argument(
        '--symbol',
        type=str,
        help='Single symbol to process (default: all watchlist)'
    )
    parser.add_argument(
        '--timeframes',
        nargs='+',
        default=['1Min', '1Hour', '1Day'],
        help='Timeframes to process (default: 1Min 1Hour 1Day)'
    )
    parser.add_argument(
        '--lookback-days',
        type=int,
        default=60,
        help='Days of historical data to process (default: 60)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force recalculation of all data'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Technical Indicators ETL Pipeline")
    print("=" * 60)

    # Initialize pipeline
    etl = IndicatorsETL(
        timeframes=args.timeframes,
        lookback_days=args.lookback_days
    )

    try:
        if args.symbol:
            # Process single symbol
            print(f"\nProcessing {args.symbol}...")
            results = etl.run_for_symbol(args.symbol, force_recalculate=args.force)

            print(f"\n✓ Completed: {results['total_rows']} indicator rows computed")

            if results['errors']:
                print(f"\n⚠ Errors: {len(results['errors'])}")
                for error in results['errors']:
                    print(f"  - {error}")

        else:
            # Process entire watchlist
            print("\nProcessing watchlist...")
            results = etl.run_for_watchlist()

            print(f"\n✓ Completed: {results['total_rows']} total indicator rows")
            print(f"  Symbols processed: {len(results['symbols'])}")

            if results['total_errors'] > 0:
                print(f"\n⚠ Total errors: {results['total_errors']}")

    except Exception as e:
        print(f"\n✗ ETL failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        etl.close()

    print("\n" + "=" * 60)
