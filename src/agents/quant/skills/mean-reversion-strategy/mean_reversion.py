"""Mean Reversion Strategy Implementation.

Calculates statistical measures and generates trading signals based on
mean reversion principles. Identifies overbought/oversold conditions
using Z-scores, moving averages, and Bollinger Bands.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from src.dao import AlpacaDAO
from src.utils import get_logger

logger = get_logger(__name__)


class MeanReversionStrategy:
    """Mean reversion strategy calculator.

    Identifies trading opportunities based on statistical deviation
    from historical mean prices.
    """

    def __init__(
        self,
        symbol: str,
        lookback: int = 60,
        threshold: float = 2.0,
        ma_period: int = 20,
        timeframe: str = "1Day"
    ):
        """Initialize mean reversion strategy.

        Args:
            symbol: Stock ticker symbol
            lookback: Number of bars for calculation
            threshold: Z-score threshold for signals (default 2.0)
            ma_period: Moving average period (default 20)
            timeframe: Timeframe for bars (default: 1Day)
        """
        self.symbol = symbol.upper()
        self.lookback = lookback
        self.threshold = threshold
        self.ma_period = ma_period
        self.timeframe = timeframe
        self.dao = AlpacaDAO()

    def fetch_data(self) -> pd.DataFrame:
        """Fetch historical price data.

        Returns:
            DataFrame with OHLCV data
        """
        logger.info(f"Fetching {self.lookback} bars for {self.symbol}")

        # Calculate time range
        end = datetime.now()
        # Get extra days to ensure we have enough data
        days_needed = self.lookback + 100  # Extra buffer for MA calculations
        start = end - timedelta(days=days_needed)

        # Fetch data from database
        df = self.dao.get_bars(
            symbol=self.symbol,
            start=start,
            end=end,
            timeframe=self.timeframe
        )

        if df.empty:
            logger.warning(f"No data found for {self.symbol}")
            return pd.DataFrame()

        # Ensure we have enough data
        if len(df) < self.lookback:
            logger.warning(
                f"Insufficient data: {len(df)} bars, need {self.lookback}"
            )

        return df

    def calculate_statistics(self, df: pd.DataFrame) -> Dict:
        """Calculate statistical measures including VWAP.

        Args:
            df: DataFrame with price data

        Returns:
            Dict with mean, std_dev, z_score, percentile, vwap
        """
        if df.empty or len(df) < self.lookback:
            return {}

        # Use closing prices for calculations
        prices = df['close'].tail(self.lookback)
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
            recent_data = df.tail(self.lookback)
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

    def calculate_moving_averages(self, df: pd.DataFrame) -> Dict:
        """Calculate moving averages.

        Args:
            df: DataFrame with price data

        Returns:
            Dict with SMA and EMA values
        """
        if df.empty:
            return {}

        prices = df['close']

        # Simple Moving Averages
        sma_20 = float(prices.rolling(window=20).mean().iloc[-1]) if len(prices) >= 20 else None
        sma_50 = float(prices.rolling(window=50).mean().iloc[-1]) if len(prices) >= 50 else None

        # Exponential Moving Average
        ema_20 = float(prices.ewm(span=20, adjust=False).mean().iloc[-1]) if len(prices) >= 20 else None

        return {
            "sma_20": round(sma_20, 2) if sma_20 else None,
            "sma_50": round(sma_50, 2) if sma_50 else None,
            "ema_20": round(ema_20, 2) if ema_20 else None
        }

    def calculate_bollinger_bands(self, df: pd.DataFrame) -> Dict:
        """Calculate Bollinger Bands.

        Args:
            df: DataFrame with price data

        Returns:
            Dict with upper, middle, lower bands
        """
        if df.empty or len(df) < self.ma_period:
            return {}

        prices = df['close'].tail(self.lookback)

        # Middle band (SMA)
        sma = prices.rolling(window=self.ma_period).mean()

        # Standard deviation
        std = prices.rolling(window=self.ma_period).std()

        # Bands
        upper_band = float((sma + (std * 2)).iloc[-1])
        middle_band = float(sma.iloc[-1])
        lower_band = float((sma - (std * 2)).iloc[-1])

        return {
            "upper_band": round(upper_band, 2),
            "middle_band": round(middle_band, 2),
            "lower_band": round(lower_band, 2)
        }

    def calculate_support_resistance(self, df: pd.DataFrame) -> Dict:
        """Calculate support and resistance levels.

        Uses recent highs/lows to identify key price levels.

        Args:
            df: DataFrame with price data

        Returns:
            Dict with support and resistance levels
        """
        if df.empty or len(df) < 20:
            return {}

        recent = df.tail(20)

        # Resistance: recent high
        resistance = float(recent['high'].max())

        # Support: recent low
        support = float(recent['low'].min())

        return {
            "resistance": round(resistance, 2),
            "support": round(support, 2)
        }

    def generate_signals(
        self,
        current_price: float,
        stats: Dict,
        ma: Dict,
        bands: Dict
    ) -> Dict:
        """Generate trading signals.

        Args:
            current_price: Current stock price
            stats: Statistical measures
            ma: Moving average values
            bands: Bollinger Band values

        Returns:
            Dict with signals and recommendations
        """
        z_score = stats.get("z_score", 0)
        sma_20 = ma.get("sma_20")
        upper_band = bands.get("upper_band")
        lower_band = bands.get("lower_band")

        # Z-score signal
        if z_score > self.threshold:
            z_signal = "overbought"
        elif z_score < -self.threshold:
            z_signal = "oversold"
        else:
            z_signal = "neutral"

        # Moving average cross signal
        ma_signal = "neutral"
        if sma_20:
            if current_price > sma_20:
                ma_signal = "bullish"
            elif current_price < sma_20:
                ma_signal = "bearish"

        # Bollinger Band signal
        bb_signal = "neutral"
        if upper_band and lower_band:
            if current_price >= upper_band:
                bb_signal = "overbought"
            elif current_price <= lower_band:
                bb_signal = "oversold"

        # Overall signal (combined logic)
        overall_signal = self._determine_overall_signal(
            z_score, z_signal, ma_signal, bb_signal
        )

        # Current state
        if z_score > 1.5:
            state = "overbought"
        elif z_score < -1.5:
            state = "oversold"
        else:
            state = "neutral"

        return {
            "current_state": state,
            "z_score_signal": z_signal,
            "ma_cross_signal": ma_signal,
            "bollinger_signal": bb_signal,
            "overall_signal": overall_signal
        }

    def _determine_overall_signal(
        self,
        z_score: float,
        z_signal: str,
        ma_signal: str,
        bb_signal: str
    ) -> str:
        """Determine overall trading signal.

        Args:
            z_score: Z-score value
            z_signal: Z-score signal
            ma_signal: Moving average signal
            bb_signal: Bollinger Band signal

        Returns:
            Overall signal: strong_buy, buy, hold, sell, strong_sell
        """
        # Strong signals (multiple confirmations)
        if z_score < -2.0 and bb_signal == "oversold":
            return "strong_buy"
        if z_score > 2.0 and bb_signal == "overbought":
            return "strong_sell"

        # Moderate signals
        if z_score < -1.5 or (z_signal == "oversold" and ma_signal == "bearish"):
            return "buy"
        if z_score > 1.5 or (z_signal == "overbought" and ma_signal == "bullish"):
            return "sell"

        # Default
        return "hold"

    def generate_trade_recommendation(
        self,
        current_price: float,
        signals: Dict,
        stats: Dict,
        levels: Dict
    ) -> Dict:
        """Generate detailed trade recommendation with VWAP confirmation.

        Args:
            current_price: Current stock price
            signals: Trading signals
            stats: Statistical measures
            levels: Support/resistance levels

        Returns:
            Dict with action, confidence, reason, entry, stop_loss, take_profit
        """
        signal = signals["overall_signal"]
        z_score = stats.get("z_score", 0)
        vwap = stats.get("vwap")

        # Confidence based on signal strength
        confidence = min(abs(z_score) / self.threshold, 1.0)

        # VWAP confirmation logic
        vwap_confirmation = ""
        if vwap is not None:
            if current_price < vwap:
                vwap_confirmation = f" Price ${current_price:.2f} is below VWAP ${vwap:.2f}, indicating average buyers are underwater - increased snap-back rally pressure."
                # Boost confidence for buy signals when price < VWAP
                if signal in ["buy", "strong_buy"]:
                    confidence = min(confidence + 0.15, 1.0)
            elif current_price > vwap:
                vwap_confirmation = f" Price ${current_price:.2f} is above VWAP ${vwap:.2f}, indicating average buyers are profitable - resistance to further upside."
                # Boost confidence for sell signals when price > VWAP
                if signal in ["sell", "strong_sell"]:
                    confidence = min(confidence + 0.15, 1.0)

        # Generate recommendation
        if signal == "strong_buy":
            action = "buy"
            reason = f"Strong oversold condition detected (Z-score: {z_score:.2f}). Price significantly below mean, high probability of reversion.{vwap_confirmation}"
            entry = current_price
            stop_loss = levels.get("support", current_price * 0.97)
            take_profit = stats.get("mean", current_price * 1.03)

        elif signal == "buy":
            action = "buy"
            reason = f"Oversold condition detected (Z-score: {z_score:.2f}). Price below mean with potential for upward reversion.{vwap_confirmation}"
            entry = current_price
            stop_loss = levels.get("support", current_price * 0.98)
            take_profit = stats.get("mean", current_price * 1.02)

        elif signal == "strong_sell":
            action = "sell"
            reason = f"Strong overbought condition detected (Z-score: {z_score:.2f}). Price significantly above mean, high probability of reversion.{vwap_confirmation}"
            entry = current_price
            stop_loss = levels.get("resistance", current_price * 1.03)
            take_profit = stats.get("mean", current_price * 0.97)

        elif signal == "sell":
            action = "sell"
            reason = f"Overbought condition detected (Z-score: {z_score:.2f}). Price above mean with potential for downward reversion.{vwap_confirmation}"
            entry = current_price
            stop_loss = levels.get("resistance", current_price * 1.02)
            take_profit = stats.get("mean", current_price * 0.98)

        else:  # hold
            action = "hold"
            vwap_info = f" VWAP: ${vwap:.2f}." if vwap else ""
            reason = f"Price within normal range (Z-score: {z_score:.2f}). No extreme deviation detected, waiting for clearer signal.{vwap_info}"
            entry = None
            stop_loss = None
            take_profit = None

        return {
            "action": action,
            "confidence": round(confidence, 2),
            "reason": reason,
            "entry_price": round(entry, 2) if entry else None,
            "stop_loss": round(stop_loss, 2) if stop_loss else None,
            "take_profit": round(take_profit, 2) if take_profit else None
        }

    def analyze(self) -> Dict:
        """Run complete mean reversion analysis.

        Returns:
            Dict with all analysis results
        """
        logger.info(f"Running mean reversion analysis for {self.symbol}")

        # Fetch data
        df = self.fetch_data()
        if df.empty:
            return {
                "error": f"No data available for {self.symbol}",
                "symbol": self.symbol,
                "timestamp": datetime.now().isoformat()
            }

        current_price = float(df['close'].iloc[-1])

        # Calculate metrics (these may return empty dicts if insufficient data)
        stats = self.calculate_statistics(df)
        ma = self.calculate_moving_averages(df)
        bands = self.calculate_bollinger_bands(df)
        levels = self.calculate_support_resistance(df)

        # Merge bands into levels
        levels.update({
            "upper_band": bands.get("upper_band"),
            "lower_band": bands.get("lower_band")
        })

        # Generate signals only if we have statistics
        if stats:
            signals = self.generate_signals(current_price, stats, ma, bands)
            recommendation = self.generate_trade_recommendation(
                current_price, signals, stats, levels
            )
            overall_signal = signals['overall_signal']
        else:
            # Insufficient data for analysis
            signals = {
                "current_state": "unknown",
                "z_score_signal": "unknown",
                "ma_cross_signal": "unknown",
                "bollinger_signal": "unknown",
                "overall_signal": "hold"
            }
            recommendation = {
                "action": "hold",
                "confidence": 0.0,
                "reason": "Insufficient data for mean reversion analysis",
                "entry_price": None,
                "stop_loss": None,
                "take_profit": None
            }
            overall_signal = "hold"

        # Build result
        result = {
            "symbol": self.symbol,
            "timestamp": datetime.now().isoformat(),
            "current_price": round(current_price, 2),
            "statistics": stats,
            "moving_averages": ma,
            "signals": signals,
            "levels": levels,
            "trade_recommendation": recommendation,
            "parameters": {
                "lookback": self.lookback,
                "threshold": self.threshold,
                "ma_period": self.ma_period
            }
        }

        logger.info(f"Analysis complete: {overall_signal}")
        return result


def main():
    """Command-line interface for mean reversion strategy."""
    parser = argparse.ArgumentParser(
        description='Mean Reversion Strategy Analysis'
    )
    parser.add_argument(
        '--symbol',
        type=str,
        required=True,
        help='Stock ticker symbol (e.g., AAPL)'
    )
    parser.add_argument(
        '--lookback',
        type=int,
        default=60,
        help='Number of bars for calculation (default: 60)'
    )
    parser.add_argument(
        '--threshold',
        type=float,
        default=2.0,
        help='Z-score threshold for signals (default: 2.0)'
    )
    parser.add_argument(
        '--ma-period',
        type=int,
        default=20,
        help='Moving average period (default: 20)'
    )
    parser.add_argument(
        '--timeframe',
        type=str,
        default='1Day',
        help='Timeframe for bars (default: 1Day)'
    )
    parser.add_argument(
        '--format',
        type=str,
        choices=['json', 'text'],
        default='json',
        help='Output format (default: json)'
    )

    args = parser.parse_args()

    # Run analysis
    try:
        strategy = MeanReversionStrategy(
            symbol=args.symbol,
            lookback=args.lookback,
            threshold=args.threshold,
            ma_period=args.ma_period,
            timeframe=args.timeframe
        )

        result = strategy.analyze()

        # Close DAO connection
        strategy.dao.close()

        # Output
        if args.format == 'json':
            print(json.dumps(result, indent=2))
        else:
            # Text format
            if "error" in result:
                print(f"Error: {result['error']}")
            else:
                print(f"\n{'='*60}")
                print(f"Mean Reversion Analysis: {result['symbol']}")
                print(f"{'='*60}")
                print(f"\nCurrent Price: ${result['current_price']}")

                # Statistics (handle empty dict)
                if result.get('statistics'):
                    print(f"\nStatistics:")
                    print(f"  Mean: ${result['statistics'].get('mean', 'N/A')}")
                    print(f"  Std Dev: ${result['statistics'].get('std_dev', 'N/A')}")
                    print(f"  Z-Score: {result['statistics'].get('z_score', 'N/A')}")
                    print(f"  Percentile: {result['statistics'].get('percentile', 'N/A')}%")
                else:
                    print(f"\nStatistics: Insufficient data")

                # Signals (handle empty dict)
                if result.get('signals'):
                    print(f"\nSignals:")
                    print(f"  State: {result['signals'].get('current_state', 'unknown')}")
                    print(f"  Overall Signal: {result['signals'].get('overall_signal', 'unknown')}")
                else:
                    print(f"\nSignals: Insufficient data")

                # Recommendation
                if result.get('trade_recommendation'):
                    print(f"\nRecommendation:")
                    rec = result['trade_recommendation']
                    print(f"  Action: {rec.get('action', 'unknown').upper()}")
                    print(f"  Confidence: {rec.get('confidence', 0)*100:.0f}%")
                    print(f"  Reason: {rec.get('reason', 'No reason available')}")
                    if rec.get('entry_price'):
                        print(f"  Entry: ${rec['entry_price']}")
                        print(f"  Stop Loss: ${rec['stop_loss']}")
                        print(f"  Take Profit: ${rec['take_profit']}")
                else:
                    print(f"\nRecommendation: Insufficient data")

                print(f"\n{'='*60}\n")

    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
