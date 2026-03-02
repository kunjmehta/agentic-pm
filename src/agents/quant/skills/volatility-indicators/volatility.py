"""Volatility indicator calculations (Bollinger Bands)."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import argparse
import json
from datetime import datetime, timedelta

from src.dao import AlpacaDAO


def calc_volatility_bands(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> dict:
    """Calculate Bollinger Bands.

    Args:
        df: DataFrame with 'close' column
        period: SMA period (default 20)
        num_std: Number of standard deviations (default 2)

    Returns:
        Dict with upper, middle, lower bands and bandwidth percentage
    """
    if len(df) < period:
        return {'upper': None, 'middle': None, 'lower': None, 'bandwidth': None}

    # Calculate SMA and standard deviation
    middle_band = df['close'].rolling(window=period).mean()
    std = df['close'].rolling(window=period).std()

    # Upper and lower bands
    upper_band = middle_band + (std * num_std)
    lower_band = middle_band - (std * num_std)

    # Bandwidth as percentage of middle band
    bandwidth = ((upper_band - lower_band) / middle_band * 100)

    return {
        'upper': float(upper_band.iloc[-1]) if not pd.isna(upper_band.iloc[-1]) else None,
        'middle': float(middle_band.iloc[-1]) if not pd.isna(middle_band.iloc[-1]) else None,
        'lower': float(lower_band.iloc[-1]) if not pd.isna(lower_band.iloc[-1]) else None,
        'bandwidth': float(bandwidth.iloc[-1]) if not pd.isna(bandwidth.iloc[-1]) else None
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Calculate Bollinger Bands')
    parser.add_argument('--symbol', type=str, required=True, help='Stock ticker symbol')
    parser.add_argument('--lookback', type=int, default=60, help='Minutes of data to analyze')
    parser.add_argument('--period', type=int, default=20, help='SMA period (default 20)')
    parser.add_argument('--std', type=float, default=2.0, help='Standard deviations (default 2.0)')
    args = parser.parse_args()

    try:
        # Fetch data from database
        dao = AlpacaDAO()
        end = datetime.now()
        start = end - timedelta(minutes=args.lookback)
        bars = dao.get_bars(args.symbol, start, end, timeframe='1Min')
        dao.close()

        if bars.empty:
            print(json.dumps({'error': f'No data available for {args.symbol}'}))
            sys.exit(1)

        # Calculate indicators
        result = calc_volatility_bands(bars, period=args.period, num_std=args.std)

        # Output JSON
        print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)
