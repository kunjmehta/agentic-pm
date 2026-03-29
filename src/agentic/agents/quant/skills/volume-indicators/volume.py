"""Volume indicator calculations (OBV and volume flow)."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import argparse
import json
from datetime import datetime, timedelta

from src.common.dao import AlpacaDAO


def calc_volume_flow(df: pd.DataFrame) -> dict:
    """Calculate On-Balance Volume (OBV) and volume trends.

    Args:
        df: DataFrame with 'close' and 'volume' columns

    Returns:
        Dict with OBV, volume trend, and average volume metrics
    """
    if len(df) < 2:
        return {
            'obv': None,
            'volume_trend': None,
            'avg_volume_10d': None,
            'current_vs_avg': None
        }

    # OBV calculation
    obv = [0]
    for i in range(1, len(df)):
        if df['close'].iloc[i] > df['close'].iloc[i-1]:
            obv.append(obv[-1] + df['volume'].iloc[i])
        elif df['close'].iloc[i] < df['close'].iloc[i-1]:
            obv.append(obv[-1] - df['volume'].iloc[i])
        else:
            obv.append(obv[-1])

    # Volume trend (last 5 vs previous 5)
    trend = 'unknown'
    if len(df) >= 10:
        recent_vol = df['volume'].iloc[-5:].mean()
        previous_vol = df['volume'].iloc[-10:-5].mean()
        trend = 'increasing' if recent_vol > previous_vol else 'decreasing'

    # Average volume (10-day)
    avg_volume_10d = df['volume'].tail(10).mean() if len(df) >= 10 else None

    # Current volume vs average
    current_vs_avg = None
    if avg_volume_10d and avg_volume_10d > 0:
        current_vol = df['volume'].iloc[-1]
        current_vs_avg = current_vol / avg_volume_10d

    return {
        'obv': int(obv[-1]) if obv else None,
        'volume_trend': trend,
        'avg_volume_10d': int(avg_volume_10d) if avg_volume_10d else None,
        'current_vs_avg': float(round(current_vs_avg, 2)) if current_vs_avg else None
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Calculate volume indicators (OBV, volume flow)')
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
        result = calc_volume_flow(bars)

        # Output JSON
        print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)
