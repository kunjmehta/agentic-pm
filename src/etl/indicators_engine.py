"""Pure technical indicators calculation engine for ETL pipeline.

This module provides standalone calculation functions extracted from the quant agent
skills. All functions are pure (no database dependencies) and operate on pandas
DataFrames with OHLCV data.

These formulas are exact copies of the quant agent implementations, ensuring
consistency between pre-computed indicators and on-demand agent calculations.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class IndicatorsEngine:
    """Pure calculation engine for technical indicators.

    All methods are static and require no initialization. Input is always a
    pandas DataFrame with OHLCV columns, output is always a dictionary.
    """

    @staticmethod
    def calc_momentum(df: pd.DataFrame) -> Dict:
        """Calculate MACD and RSI momentum indicators.

        Extracted from: src/agents/quant/skills/momentum-indicators/momentum.py

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

    @staticmethod
    def calc_volatility(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> Dict:
        """Calculate Bollinger Bands.

        Extracted from: src/agents/quant/skills/volatility-indicators/volatility.py

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

    @staticmethod
    def calc_volume(df: pd.DataFrame) -> Dict:
        """Calculate On-Balance Volume (OBV) and volume trends.

        Extracted from: src/agents/quant/skills/volume-indicators/volume.py

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

    @staticmethod
    def calc_candlestick(df: pd.DataFrame, lookback: int = 5) -> Dict:
        """Analyze candlestick patterns.

        Extracted from: src/agents/quant/skills/candlestick-patterns/candles.py

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

    @staticmethod
    def calc_mean_reversion(
        df: pd.DataFrame,
        lookback: int = 60,
        threshold: float = 2.0
    ) -> Dict:
        """Calculate mean reversion metrics.

        Extracted from: src/agents/quant/skills/mean-reversion-strategy/mean_reversion.py

        Args:
            df: DataFrame with price and volume data
            lookback: Number of bars for calculation
            threshold: Z-score threshold for signals (default 2.0)

        Returns:
            Dict with statistical measures (mean, std_dev, z_score, percentile, vwap)
        """
        if df.empty or len(df) < lookback:
            return {}

        # Use closing prices for calculations
        prices = df['close'].tail(lookback)
        current_price = float(prices.iloc[-1])

        # Calculate statistics
        mean = float(prices.mean())
        std_dev = float(prices.std())

        # Z-score: (current - mean) / std_dev
        z_score = (current_price - mean) / std_dev if std_dev > 0 else 0.0

        # Percentile rank
        percentile = float((prices <= current_price).sum() / len(prices) * 100)

        # VWAP (Volume-Weighted Average Price) - use today's data or recent period
        vwap = None
        if 'vwap' in df.columns and not df['vwap'].isna().all():
            # Use the most recent VWAP from the data
            recent_vwap = df['vwap'].dropna()
            if not recent_vwap.empty:
                vwap = float(recent_vwap.iloc[-1])
        elif 'volume' in df.columns:
            # Calculate VWAP if not in data
            recent_data = df.tail(lookback)
            if not recent_data['volume'].isna().all() and recent_data['volume'].sum() > 0:
                vwap = float(
                    (recent_data['close'] * recent_data['volume']).sum() /
                    recent_data['volume'].sum()
                )

        result = {
            "mean": round(mean, 2),
            "std_dev": round(std_dev, 2),
            "z_score": round(z_score, 2),
            "percentile": round(percentile, 1)
        }

        if vwap is not None:
            result["vwap"] = round(vwap, 2)

        return result

    @staticmethod
    def calc_all(df: pd.DataFrame) -> Dict:
        """Calculate all indicators in one pass.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dict with all indicator categories (momentum, volatility, volume, candlestick, mean_reversion)
        """
        return {
            'momentum': IndicatorsEngine.calc_momentum(df),
            'volatility': IndicatorsEngine.calc_volatility(df),
            'volume': IndicatorsEngine.calc_volume(df),
            'candlestick': IndicatorsEngine.calc_candlestick(df),
            'mean_reversion': IndicatorsEngine.calc_mean_reversion(df)
        }


if __name__ == "__main__":
    """Test IndicatorsEngine with sample data."""
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    from src.dao import AlpacaDAO
    from datetime import datetime, timedelta

    print("=" * 60)
    print("Testing IndicatorsEngine")
    print("=" * 60)

    # Fetch sample data
    symbol = "AAPL"
    dao = AlpacaDAO()
    end = datetime.now()
    start = end - timedelta(days=30)

    print(f"\n1. Fetching data for {symbol}...")
    df = dao.get_bars(symbol, start, end, timeframe='1Day')
    dao.close()

    if df.empty:
        print(f"   [FAIL] No data available for {symbol}")
        sys.exit(1)

    print(f"   [OK] Fetched {len(df)} bars")

    # Test individual indicators
    print("\n2. Testing momentum indicators...")
    momentum = IndicatorsEngine.calc_momentum(df)
    print(f"   MACD: {momentum['macd']}")
    print(f"   RSI: {momentum['rsi']}")

    print("\n3. Testing volatility indicators...")
    volatility = IndicatorsEngine.calc_volatility(df)
    print(f"   BB Upper: {volatility['upper']}")
    print(f"   BB Middle: {volatility['middle']}")
    print(f"   BB Lower: {volatility['lower']}")
    print(f"   Bandwidth: {volatility['bandwidth']}")

    print("\n4. Testing volume indicators...")
    volume = IndicatorsEngine.calc_volume(df)
    print(f"   OBV: {volume['obv']}")
    print(f"   Volume Trend: {volume['volume_trend']}")

    print("\n5. Testing candlestick patterns...")
    candles = IndicatorsEngine.calc_candlestick(df)
    print(f"   Patterns: {candles['patterns']}")
    print(f"   Last Candle: {candles['last_candle_type']}")

    print("\n6. Testing mean reversion...")
    mean_rev = IndicatorsEngine.calc_mean_reversion(df)
    print(f"   Z-Score: {mean_rev.get('z_score')}")
    print(f"   Percentile: {mean_rev.get('percentile')}")

    print("\n7. Testing calc_all()...")
    all_indicators = IndicatorsEngine.calc_all(df)
    print(f"   [OK] Calculated all indicators")
    print(f"   Categories: {list(all_indicators.keys())}")

    print("\n" + "=" * 60)
    print("IndicatorsEngine Tests Complete")
    print("=" * 60)
