"""Candlestick pattern detection."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import argparse
import json
from datetime import datetime, timedelta

from src.common.dao import AlpacaDAO


def analyze_candle_structure(df: pd.DataFrame, lookback: int = 5) -> dict:
    """Analyze candlestick patterns.

    Detects:
    - Bullish/Bearish Engulfing
    - Doji (indecision)
    - Hammer/Hanging Man
    - Body/shadow spreads

    Args:
        df: DataFrame with OHLC data
        lookback: Number of recent candles to analyze

    Returns:
        Dict with detected patterns and analysis
    """
    if len(df) < 2:
        return {
            'patterns': [],
            'last_candle_type': None,
            'last_body_pct': None,
            'pattern_count': 0
        }

    patterns = []
    recent = df.tail(lookback) if len(df) >= lookback else df

    # Analyze patterns in recent candles
    for i in range(1, len(recent)):
        current = recent.iloc[i]
        previous = recent.iloc[i-1]

        # Calculate body and shadows
        body = abs(current['close'] - current['open'])
        upper_shadow = current['high'] - max(current['open'], current['close'])
        lower_shadow = min(current['open'], current['close']) - current['low']
        total_range = current['high'] - current['low']

        # Skip if no range
        if total_range == 0:
            continue

        # Bullish Engulfing
        if (previous['close'] < previous['open'] and  # Previous bearish
            current['close'] > current['open'] and    # Current bullish
            current['open'] <= previous['close'] and
            current['close'] >= previous['open']):
            patterns.append('bullish_engulfing')

        # Bearish Engulfing
        if (previous['close'] > previous['open'] and  # Previous bullish
            current['close'] < current['open'] and    # Current bearish
            current['open'] >= previous['close'] and
            current['close'] <= previous['open']):
            patterns.append('bearish_engulfing')

        # Doji (small body, indecision)
        if body / total_range < 0.1:
            patterns.append('doji')

        # Hammer (long lower shadow, small body at top)
        if (lower_shadow > 2 * body and
            upper_shadow < body):
            patterns.append('hammer')

        # Hanging Man (same as hammer but context matters)
        # We'll detect the shape, context interpretation is for the analyst
        if (lower_shadow > 2 * body and
            upper_shadow < body and
            i > len(recent) / 2):  # In second half = potentially hanging man
            patterns.append('hanging_man')

    # Analyze last candle
    last = recent.iloc[-1]
    last_body = abs(last['close'] - last['open'])
    last_range = last['high'] - last['low']

    # Determine candle type
    if last['close'] > last['open']:
        last_type = 'bullish'
    elif last['close'] < last['open']:
        last_type = 'bearish'
    else:
        last_type = 'neutral'

    # Body percentage of total range
    last_body_pct = (last_body / last_range * 100) if last_range > 0 else 0

    return {
        'patterns': list(set(patterns)),  # Remove duplicates
        'last_candle_type': last_type,
        'last_body_pct': round(float(last_body_pct), 1),
        'pattern_count': len(set(patterns))
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Detect candlestick patterns')
    parser.add_argument('--symbol', type=str, required=True, help='Stock ticker symbol')
    parser.add_argument('--lookback', type=int, default=10, help='Number of candles to analyze')
    args = parser.parse_args()

    try:
        # Fetch data from database
        # Use more data than lookback to have context
        dao = AlpacaDAO()
        end = datetime.now()
        start = end - timedelta(minutes=args.lookback * 2)
        bars = dao.get_bars(args.symbol, start, end, timeframe='1Min')
        dao.close()

        if bars.empty:
            print(json.dumps({'error': f'No data available for {args.symbol}'}))
            sys.exit(1)

        # Analyze patterns
        result = analyze_candle_structure(bars, lookback=args.lookback)

        # Output JSON
        print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)
