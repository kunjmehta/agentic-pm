"""Momentum indicator calculations (MACD and RSI)."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import numpy as np
import argparse
import json
from datetime import datetime, timedelta

from src.common.dao import AlpacaDAO


def calc_momentum_package(df: pd.DataFrame) -> dict:
    """Calculate MACD and RSI momentum indicators.

    Args:
        df: DataFrame with 'close' column

    Returns:
        Dict with MACD (value, signal, histogram) and RSI
    """
    if len(df) < 26:
        return {'macd': None, 'rsi': None}

    # MACD: EMA(12) - EMA(26), Signal: EMA(9) of MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    # RSI: Relative Strength Index (14 periods)
    rsi = None
    if len(df) >= 14:
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()

        # Avoid division by zero
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

    return {
        'macd': {
            'value': float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else None,
            'signal': float(signal_line.iloc[-1]) if not pd.isna(signal_line.iloc[-1]) else None,
            'histogram': float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else None
        },
        'rsi': float(rsi.iloc[-1]) if rsi is not None and not pd.isna(rsi.iloc[-1]) else None
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Calculate momentum indicators (MACD, RSI)')
    parser.add_argument('--symbol', type=str, required=True, help='Stock ticker symbol')
    parser.add_argument('--lookback', type=int, default=60, help='Minutes of data to analyze')
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
        result = calc_momentum_package(bars)

        # Output JSON
        print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)
