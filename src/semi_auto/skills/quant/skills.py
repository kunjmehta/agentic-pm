"""Quant skill classes for the semi_auto registry.

One class per indicator/strategy, each with two methods:

    analyze_bars(df, ...)       — pure computation on a pre-fetched DataFrame.
                                   Used by the backtesting workflow where bars
                                   are already in memory.

    generate_signals(symbol, ...) — fetches bars from AlpacaDAO then calls
                                   analyze_bars. Used by the signal-generation
                                   workflow that runs on live / recent data.

Core indicator classes (defined here):
    MomentumSkill              — MACD + RSI
    VolatilitySkill            — Bollinger Bands
    VolumeSkill                — OBV + volume flow
    CandlestickSkill           — candlestick pattern detection
    MeanReversionSkill         — Z-score / MA / Bollinger mean-reversion signals

Strategy classes (re-exported from individual modules):
    vwap_reversion             — VWAPReversionSkill
    opening_range_breakout     — OpeningRangeBreakoutSkill
    rsi_divergence_scalp       — RSIDivergenceScalpSkill
    momentum_burst             — MomentumBurstSkill
    golden_cross               — GoldenCrossSkill
    breakout_52w               — Breakout52WeekSkill
    mean_reversion_daily       — MeanReversionDailySkill
    earnings_drift             — EarningsDriftSkill
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.semi_auto.skills.quant._utils import _fetch_bars  # noqa: F401 (shared helper)

logger = get_logger(__name__)


# =============================================================================
# MomentumSkill — MACD + RSI
# =============================================================================

class MomentumSkill:
    """Compute MACD and RSI momentum indicators.

    Workflow A (backtesting): call ``analyze_bars(df)`` with a pre-fetched
    DataFrame.
    Workflow B (signal generation): call ``generate_signals(symbol, ...)``
    which fetches bars automatically.
    """

    def analyze_bars(self, df: pd.DataFrame) -> Dict:
        """Calculate MACD and RSI from a pre-fetched DataFrame.

        Requires at least 26 rows for MACD and 14 rows for RSI.

        Args:
            df: DataFrame with a ``close`` column.

        Returns:
            Dict with keys:
                - macd: {value, signal, histogram} or None
                - rsi: float or None
        """
        if len(df) < 26:
            return {"macd": None, "rsi": None}

        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line

        rsi = None
        if len(df) >= 14:
            delta = df["close"].diff()
            # Wilder's SMMA smoothing via EWM (alpha = 1/14), not simple moving
            # average.  This matches RSI as computed by TradingView / Bloomberg
            # and every major charting platform.
            gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / 14, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / 14, adjust=False).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi_series = 100 - (100 / (1 + rs))
            rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None

        def _f(series):
            v = series.iloc[-1]
            return float(v) if not pd.isna(v) else None

        return {
            "macd": {
                "value": _f(macd_line),
                "signal": _f(signal_line),
                "histogram": _f(histogram),
            },
            "rsi": rsi,
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 90,
    ) -> Dict:
        """Fetch recent bars and compute MACD + RSI signals.

        Args:
            symbol: Stock ticker.
            timeframe: Bar timeframe (AlpacaDAO canonical string).
            lookback_days: Calendar days of history to fetch.

        Returns:
            Same as ``analyze_bars`` or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe, lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df)
        result["symbol"] = symbol
        result["timeframe"] = timeframe
        result["timestamp"] = datetime.now().isoformat()
        return result


# =============================================================================
# VolatilitySkill — Bollinger Bands
# =============================================================================

class VolatilitySkill:
    """Compute Bollinger Band volatility indicators.

    Workflow A (backtesting): ``analyze_bars(df, period, num_std)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(
        self,
        df: pd.DataFrame,
        period: int = 20,
        num_std: float = 2.0,
    ) -> Dict:
        """Calculate Bollinger Bands from a pre-fetched DataFrame.

        Args:
            df: DataFrame with a ``close`` column.
            period: SMA period. Defaults to 20.
            num_std: Number of standard deviations for the bands. Defaults to 2.

        Returns:
            Dict with upper, middle, lower (float or None) and bandwidth (%).
        """
        if len(df) < period:
            return {"upper": None, "middle": None, "lower": None, "bandwidth": None}

        middle = df["close"].rolling(window=period).mean()
        std = df["close"].rolling(window=period).std(ddof=0)
        upper = middle + std * num_std
        lower = middle - std * num_std
        bandwidth = (upper - lower) / middle * 100

        def _f(s):
            v = s.iloc[-1]
            return float(v) if not pd.isna(v) else None

        return {
            "upper": _f(upper),
            "middle": _f(middle),
            "lower": _f(lower),
            "bandwidth": _f(bandwidth),
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 90,
        period: int = 20,
        num_std: float = 2.0,
    ) -> Dict:
        """Fetch recent bars and compute Bollinger Band signals.

        Args:
            symbol: Stock ticker.
            timeframe: Bar timeframe.
            lookback_days: Calendar days of history to fetch.
            period: SMA period passed to ``analyze_bars``.
            num_std: Standard deviation multiplier passed to ``analyze_bars``.

        Returns:
            Same as ``analyze_bars`` or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe, lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, period=period, num_std=num_std)
        result["symbol"] = symbol
        result["timeframe"] = timeframe
        result["timestamp"] = datetime.now().isoformat()
        return result


# =============================================================================
# VolumeSkill — OBV + volume flow
# =============================================================================

class VolumeSkill:
    """Compute On-Balance Volume (OBV) and volume flow indicators.

    Workflow A (backtesting): ``analyze_bars(df)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(self, df: pd.DataFrame) -> Dict:
        """Calculate OBV and volume trends from a pre-fetched DataFrame.

        Args:
            df: DataFrame with ``close`` and ``volume`` columns.

        Returns:
            Dict with obv, volume_trend, avg_volume_10d, current_vs_avg.
        """
        if len(df) < 2:
            return {
                "obv": None,
                "volume_trend": None,
                "avg_volume_10d": None,
                "current_vs_avg": None,
            }

        obv = [0]
        for i in range(1, len(df)):
            if df["close"].iloc[i] > df["close"].iloc[i - 1]:
                obv.append(obv[-1] + df["volume"].iloc[i])
            elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
                obv.append(obv[-1] - df["volume"].iloc[i])
            else:
                obv.append(obv[-1])

        trend = "unknown"
        if len(df) >= 10:
            recent = df["volume"].iloc[-5:].mean()
            previous = df["volume"].iloc[-10:-5].mean()
            trend = "increasing" if recent > previous else "decreasing"

        avg_vol = df["volume"].tail(10).mean() if len(df) >= 10 else None
        current_vs_avg = None
        if avg_vol and avg_vol > 0:
            current_vs_avg = float(round(df["volume"].iloc[-1] / avg_vol, 2))

        return {
            "obv": int(obv[-1]) if obv else None,
            "volume_trend": trend,
            "avg_volume_10d": int(avg_vol) if avg_vol else None,
            "current_vs_avg": current_vs_avg,
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 90,
    ) -> Dict:
        """Fetch recent bars and compute OBV / volume flow signals.

        Args:
            symbol: Stock ticker.
            timeframe: Bar timeframe.
            lookback_days: Calendar days of history to fetch.

        Returns:
            Same as ``analyze_bars`` or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe, lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df)
        result["symbol"] = symbol
        result["timeframe"] = timeframe
        result["timestamp"] = datetime.now().isoformat()
        return result


# =============================================================================
# CandlestickSkill — pattern detection
# =============================================================================

class CandlestickSkill:
    """Detect candlestick patterns in recent price data.

    Detects: bullish/bearish engulfing, doji, hammer, hanging man.

    Workflow A (backtesting): ``analyze_bars(df, lookback)``.
    Workflow B (signal generation): ``generate_signals(symbol, ...)``.
    """

    def analyze_bars(self, df: pd.DataFrame, lookback: int = 5) -> Dict:
        """Detect candlestick patterns in the last *lookback* bars.

        Args:
            df: DataFrame with ``open``, ``high``, ``low``, ``close`` columns.
            lookback: Number of recent candles to analyse.

        Returns:
            Dict with patterns (list), last_candle_type, last_body_pct,
            pattern_count.
        """
        if len(df) < 2:
            return {
                "patterns": [],
                "last_candle_type": None,
                "last_body_pct": None,
                "pattern_count": 0,
            }

        patterns = []
        recent = df.tail(lookback) if len(df) >= lookback else df

        for i in range(1, len(recent)):
            cur = recent.iloc[i]
            prev = recent.iloc[i - 1]
            body = abs(cur["close"] - cur["open"])
            upper_shadow = cur["high"] - max(cur["open"], cur["close"])
            lower_shadow = min(cur["open"], cur["close"]) - cur["low"]
            total_range = cur["high"] - cur["low"]
            if total_range == 0:
                continue
            # Bullish engulfing
            if (
                prev["close"] < prev["open"]
                and cur["close"] > cur["open"]
                and cur["open"] <= prev["close"]
                and cur["close"] >= prev["open"]
            ):
                patterns.append("bullish_engulfing")
            # Bearish engulfing
            if (
                prev["close"] > prev["open"]
                and cur["close"] < cur["open"]
                and cur["open"] >= prev["close"]
                and cur["close"] <= prev["open"]
            ):
                patterns.append("bearish_engulfing")
            # Doji
            if body / total_range < 0.1:
                patterns.append("doji")
            # Hammer / hanging man
            if lower_shadow > 2 * body and upper_shadow < body:
                patterns.append("hammer")
                if i > len(recent) / 2:
                    patterns.append("hanging_man")

        last = recent.iloc[-1]
        last_body = abs(last["close"] - last["open"])
        last_range = last["high"] - last["low"]
        last_type = (
            "bullish"
            if last["close"] > last["open"]
            else "bearish"
            if last["close"] < last["open"]
            else "neutral"
        )
        last_body_pct = (last_body / last_range * 100) if last_range > 0 else 0

        return {
            "patterns": list(set(patterns)),
            "last_candle_type": last_type,
            "last_body_pct": round(float(last_body_pct), 1),
            "pattern_count": len(set(patterns)),
        }

    def generate_signals(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback_days: int = 30,
        lookback: int = 5,
    ) -> Dict:
        """Fetch recent bars and detect candlestick patterns.

        Args:
            symbol: Stock ticker.
            timeframe: Bar timeframe.
            lookback_days: Calendar days of history to fetch.
            lookback: Number of recent candles to pattern-check.

        Returns:
            Same as ``analyze_bars`` or ``{"error": "..."}`` on failure.
        """
        df = _fetch_bars(symbol, timeframe, lookback_days)
        if df is None:
            return {"error": f"No data for {symbol}/{timeframe}"}
        result = self.analyze_bars(df, lookback=lookback)
        result["symbol"] = symbol
        result["timeframe"] = timeframe
        result["timestamp"] = datetime.now().isoformat()
        return result


# =============================================================================
# MeanReversionSkill — Z-score / MA / Bollinger mean-reversion signals
# =============================================================================

class MeanReversionSkill:
    """Mean-reversion strategy analyser combining statistics, MAs, and bands.

    Workflow A (backtesting): ``analyze_bars(df, threshold, ma_period)``
    takes a pre-fetched DataFrame and returns signals without any DAO call.

    Workflow B (signal generation): ``generate_signals(symbol, ...)``
    fetches data from AlpacaDAO and returns the full analysis dict including
    a trade recommendation.
    """

    # ------------------------------------------------------------------
    # Workflow A — pure DataFrame analysis
    # ------------------------------------------------------------------

    def analyze_bars(
        self,
        df: pd.DataFrame,
        threshold: float = 2.0,
        ma_period: int = 20,
        lookback: int = 60,
        sr_lookback: int = 60,
    ) -> Dict:
        """Run mean-reversion analysis on a pre-fetched DataFrame.

        Computes statistics, moving averages, Bollinger Bands,
        support/resistance, and produces a signal + recommendation — all
        without any DAO or network calls.

        Args:
            df: DataFrame with ``open``, ``high``, ``low``, ``close``,
                (optionally ``volume`` and ``vwap``) columns.
            threshold: Z-score entry threshold. Defaults to 2.0.
            ma_period: Moving average period. Defaults to 20.
            lookback: Number of bars to use for statistics. Defaults to 60.
            sr_lookback: Bars to scan for support/resistance pivots. Defaults
                to 60 (1 hour of 1Min data).

        Returns:
            Analysis dict with statistics, moving_averages, signals,
            levels, trade_recommendation.
        """
        if df.empty or len(df) < 2:
            return {"error": "Insufficient data for mean-reversion analysis"}

        current_price = float(df["close"].iloc[-1])
        stats = self._calc_statistics(df, lookback)
        ma = self._calc_moving_averages(df)
        bands = self._calc_bollinger_bands(df, ma_period, lookback)
        levels = self._calc_support_resistance(df, sr_lookback=sr_lookback)
        levels.update({"upper_band": bands.get("upper_band"), "lower_band": bands.get("lower_band")})

        if stats:
            signals = self._generate_signals(current_price, stats, ma, bands, threshold)
            recommendation = self._generate_recommendation(
                current_price, signals, stats, levels, threshold=threshold
            )
        else:
            signals = {
                "current_state": "unknown",
                "z_score_signal": "unknown",
                "ma_cross_signal": "unknown",
                "bollinger_signal": "unknown",
                "overall_signal": "hold",
            }
            recommendation = {
                "action": "hold",
                "confidence": 0.0,
                "reason": "Insufficient data for mean reversion analysis",
                "entry_price": None,
                "stop_loss": None,
                "take_profit": None,
            }

        return {
            "current_price": round(current_price, 2),
            "statistics": stats,
            "moving_averages": ma,
            "signals": signals,
            "levels": levels,
            "trade_recommendation": recommendation,
            "parameters": {"lookback": lookback, "threshold": threshold, "ma_period": ma_period, "sr_lookback": sr_lookback},
        }

    # ------------------------------------------------------------------
    # Workflow B — signal generation (fetches data from DAO)
    # ------------------------------------------------------------------

    def generate_signals(
        self,
        symbol: str,
        lookback: int = 60,
        threshold: float = 2.0,
        ma_period: int = 20,
        timeframe: str = "1Min",
        sr_lookback: int = 60,
    ) -> Dict:
        """Fetch recent bars and run the full mean-reversion analysis.

        Args:
            symbol: Stock ticker.
            lookback: Number of bars for statistics. Defaults to 60.
            threshold: Z-score entry threshold. Defaults to 2.0.
            ma_period: Moving average period. Defaults to 20.
            timeframe: Bar timeframe. Defaults to ``"1Min"``.
            sr_lookback: Bars to scan for support/resistance pivots. Defaults to 60.

        Returns:
            Full analysis dict (same as ``analyze_bars`` plus symbol /
            timestamp) or ``{"error": "..."}`` on failure.
        """
        try:
            from src.common.dao import AlpacaDAO

            dao = AlpacaDAO()
            end = datetime.now()
            start = end - timedelta(days=lookback + 100)
            df = dao.get_bars(symbol=symbol.upper(), start=start, end=end, timeframe=timeframe)
            dao.close()
        except Exception as exc:
            logger.warning(f"[MeanReversionSkill] Bar fetch failed for {symbol}: {exc}")
            return {"error": str(exc)}

        if df is None or df.empty:
            return {"error": f"No data available for {symbol}", "symbol": symbol}

        result = self.analyze_bars(df, threshold=threshold, ma_period=ma_period, lookback=lookback, sr_lookback=sr_lookback)
        result["symbol"] = symbol.upper()
        result["timestamp"] = datetime.now().isoformat()
        return result

    # ------------------------------------------------------------------
    # Internal calculation helpers
    # ------------------------------------------------------------------

    def _calc_statistics(self, df: pd.DataFrame, lookback: int) -> Dict:
        """Compute mean, std_dev, z_score, percentile, optionally vwap.

        Args:
            df: Price DataFrame.
            lookback: Lookback window size.

        Returns:
            Stats dict, or ``{}`` if data is insufficient.
        """
        if df.empty or len(df) < lookback:
            return {}
        prices = df["close"].tail(lookback)
        current = float(prices.iloc[-1])
        mean = float(prices.mean())
        std = float(prices.std(ddof=0))
        z = (current - mean) / std if std > 0 else 0.0
        pct = float((prices <= current).sum() / len(prices) * 100)

        result = {
            "mean": round(mean, 2),
            "std_dev": round(std, 2),
            "z_score": round(z, 2),
            "percentile": round(pct, 1),
        }

        # VWAP (optional — use stored column or compute from volume)
        vwap = None
        if "vwap" in df.columns and not df["vwap"].isna().all():
            recent_vwap = df["vwap"].dropna()
            if not recent_vwap.empty:
                vwap = float(recent_vwap.iloc[-1])
        elif "volume" in df.columns:
            rec = df.tail(lookback)
            if not rec["volume"].isna().all() and rec["volume"].sum() > 0:
                vwap = float((rec["close"] * rec["volume"]).sum() / rec["volume"].sum())

        if vwap is not None:
            result["vwap"] = round(vwap, 2)
        return result

    def _calc_moving_averages(self, df: pd.DataFrame) -> Dict:
        """Calculate SMA-20, SMA-50, and EMA-20.

        Args:
            df: Price DataFrame.

        Returns:
            Dict with sma_20, sma_50, ema_20 (None when insufficient data).
        """
        prices = df["close"]
        return {
            "sma_20": round(float(prices.rolling(20).mean().iloc[-1]), 2) if len(prices) >= 20 else None,
            "sma_50": round(float(prices.rolling(50).mean().iloc[-1]), 2) if len(prices) >= 50 else None,
            "ema_20": round(float(prices.ewm(span=20, adjust=False).mean().iloc[-1]), 2) if len(prices) >= 20 else None,
        }

    def _calc_bollinger_bands(self, df: pd.DataFrame, ma_period: int, lookback: int) -> Dict:
        """Calculate Bollinger Bands (±2σ around SMA).

        Args:
            df: Price DataFrame.
            ma_period: Band SMA period.
            lookback: Lookback window for rolling calculations.

        Returns:
            Dict with upper_band, middle_band, lower_band, or ``{}`` if
            data is insufficient.
        """
        if df.empty or len(df) < ma_period:
            return {}
        prices = df["close"].tail(lookback)
        sma = prices.rolling(ma_period).mean()
        # Population std (ddof=0) matches J. Bollinger's original definition
        std = prices.rolling(ma_period).std(ddof=0)
        return {
            "upper_band": round(float((sma + std * 2).iloc[-1]), 2),
            "middle_band": round(float(sma.iloc[-1]), 2),
            "lower_band": round(float((sma - std * 2).iloc[-1]), 2),
        }

    def _calc_support_resistance(self, df: pd.DataFrame, sr_lookback: int = 60) -> Dict:
        """Calculate recent support and resistance levels.

        Args:
            df: Price DataFrame.
            sr_lookback: Number of bars to scan for high/low pivots. Defaults to
                60, which equals 1 hour of 1Min data — wide enough to produce
                meaningful stop-loss / take-profit prices without being hit by
                normal intraday tick noise (the old default of 20 bars was only
                20 minutes and caused very tight stops).

        Returns:
            Dict with resistance and support, or ``{}`` if insufficient data.
        """
        if df.empty or len(df) < sr_lookback:
            return {}
        rec = df.tail(sr_lookback)
        return {
            "resistance": round(float(rec["high"].max()), 2),
            "support": round(float(rec["low"].min()), 2),
        }

    def _generate_signals(
        self,
        current_price: float,
        stats: Dict,
        ma: Dict,
        bands: Dict,
        threshold: float,
    ) -> Dict:
        """Produce z-score, MA-cross, Bollinger, and overall signals.

        Args:
            current_price: Latest close price.
            stats: Statistics dict from ``_calc_statistics``.
            ma: Moving averages dict from ``_calc_moving_averages``.
            bands: Bollinger bands dict from ``_calc_bollinger_bands``.
            threshold: Z-score threshold for overbought/oversold labels.

        Returns:
            Signals dict with current_state, z_score_signal, ma_cross_signal,
            bollinger_signal, overall_signal.
        """
        z = stats.get("z_score", 0)
        sma_20 = ma.get("sma_20")
        upper = bands.get("upper_band")
        lower = bands.get("lower_band")

        z_sig = "overbought" if z > threshold else "oversold" if z < -threshold else "neutral"
        ma_sig = (
            "bullish" if sma_20 and current_price > sma_20
            else "bearish" if sma_20 and current_price < sma_20
            else "neutral"
        )
        bb_sig = (
            "overbought" if upper and current_price >= upper
            else "oversold" if lower and current_price <= lower
            else "neutral"
        )

        # Combined overall signal
        if z < -2.0 and bb_sig == "oversold":
            overall = "strong_buy"
        elif z > 2.0 and bb_sig == "overbought":
            overall = "strong_sell"
        elif z < -1.5 or (z_sig == "oversold" and ma_sig == "bearish"):
            overall = "buy"
        elif z > 1.5 or (z_sig == "overbought" and ma_sig == "bullish"):
            overall = "sell"
        else:
            overall = "hold"

        state = "overbought" if z > 1.5 else "oversold" if z < -1.5 else "neutral"
        return {
            "current_state": state,
            "z_score_signal": z_sig,
            "ma_cross_signal": ma_sig,
            "bollinger_signal": bb_sig,
            "overall_signal": overall,
        }

    def _generate_recommendation(
        self,
        current_price: float,
        signals: Dict,
        stats: Dict,
        levels: Dict,
        threshold: float = 2.0,
    ) -> Dict:
        """Generate a trade recommendation with entry / stop-loss / take-profit.

        Args:
            current_price: Latest close price.
            signals: Signals dict from ``_generate_signals``.
            stats: Statistics dict (used for z_score, mean, vwap).
            levels: Levels dict (used for support / resistance).
            threshold: Z-score threshold used by the caller. Confidence is
                computed as ``abs(z) / threshold`` so it scales correctly
                relative to the active threshold and never exceeds 1.0 before
                the VWAP bump is applied.

        Returns:
            Dict with action, confidence, reason, entry_price, stop_loss,
            take_profit.
        """
        signal = signals["overall_signal"]
        z = stats.get("z_score", 0)
        vwap = stats.get("vwap")

        confidence = min(abs(z) / threshold, 1.0)
        vwap_note = ""
        if vwap is not None:
            if current_price < vwap:
                vwap_note = (
                    f" Price ${current_price:.2f} is below VWAP ${vwap:.2f}, "
                    "indicating snap-back rally pressure."
                )
                if signal in ("buy", "strong_buy"):
                    confidence = min(confidence + 0.15, 1.0)
            else:
                vwap_note = (
                    f" Price ${current_price:.2f} is above VWAP ${vwap:.2f}, "
                    "resistance to further upside."
                )
                if signal in ("sell", "strong_sell"):
                    confidence = min(confidence + 0.15, 1.0)

        mean = stats.get("mean", current_price)
        support = levels.get("support", current_price * 0.97)
        resistance = levels.get("resistance", current_price * 1.03)

        if signal == "strong_buy":
            return {
                "action": "buy",
                "confidence": round(confidence, 2),
                "reason": f"Strong oversold (Z={z:.2f}). High reversion probability.{vwap_note}",
                "entry_price": round(current_price, 2),
                "stop_loss": round(support, 2),
                "take_profit": round(mean, 2),
            }
        if signal == "buy":
            return {
                "action": "buy",
                "confidence": round(confidence, 2),
                "reason": f"Oversold (Z={z:.2f}). Price below mean.{vwap_note}",
                "entry_price": round(current_price, 2),
                "stop_loss": round(support, 2),
                "take_profit": round(mean, 2),
            }
        if signal == "strong_sell":
            return {
                "action": "sell",
                "confidence": round(confidence, 2),
                "reason": f"Strong overbought (Z={z:.2f}). High reversion probability.{vwap_note}",
                "entry_price": round(current_price, 2),
                "stop_loss": round(resistance, 2),
                "take_profit": round(mean, 2),
            }
        if signal == "sell":
            return {
                "action": "sell",
                "confidence": round(confidence, 2),
                "reason": f"Overbought (Z={z:.2f}). Price above mean.{vwap_note}",
                "entry_price": round(current_price, 2),
                "stop_loss": round(resistance, 2),
                "take_profit": round(mean, 2),
            }
        # hold
        vwap_info = f" VWAP: ${vwap:.2f}." if vwap else ""
        return {
            "action": "hold",
            "confidence": round(confidence, 2),
            "reason": f"Price within normal range (Z={z:.2f}). No extreme deviation.{vwap_info}",
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
        }


# =============================================================================
# Module-level singleton instances (core indicators)
# =============================================================================

momentum_skill = MomentumSkill()
volatility_skill = VolatilitySkill()

# =============================================================================
# Re-export strategy skill classes from sub-modules
# (keeps all imports from src.semi_auto.skills.quant.skills working)
# =============================================================================

from src.semi_auto.skills.quant.vwap_reversion import (  # noqa: E402
    VWAPReversionSkill,
    vwap_reversion_skill,
    make_vwap_reversion_signals,
)
from src.semi_auto.skills.quant.opening_range_breakout import (  # noqa: E402
    OpeningRangeBreakoutSkill,
    opening_range_breakout_skill,
    make_opening_range_breakout_signals,
)
from src.semi_auto.skills.quant.rsi_divergence_scalp import (  # noqa: E402
    RSIDivergenceScalpSkill,
    rsi_divergence_scalp_skill,
    make_rsi_divergence_signals,
)
from src.semi_auto.skills.quant.momentum_burst import (  # noqa: E402
    MomentumBurstSkill,
    momentum_burst_skill,
    make_momentum_burst_signals,
)
from src.semi_auto.skills.quant.golden_cross import (  # noqa: E402
    GoldenCrossSkill,
    golden_cross_skill,
    make_golden_cross_signals,
)
from src.semi_auto.skills.quant.breakout_52w import (  # noqa: E402
    Breakout52WeekSkill,
    breakout_52w_skill,
    make_breakout_52w_signals,
)
from src.semi_auto.skills.quant.mean_reversion_daily import (  # noqa: E402
    MeanReversionDailySkill,
    mean_reversion_daily_skill,
    make_mean_reversion_daily_signals,
)
from src.semi_auto.skills.quant.earnings_drift import (  # noqa: E402
    EarningsDriftSkill,
    earnings_drift_skill,
    make_earnings_drift_signals,
)


volume_skill = VolumeSkill()
candlestick_skill = CandlestickSkill()
mean_reversion_skill = MeanReversionSkill()

# ---------------------------------------------------------------------------
# Legacy function aliases — keep the registry's existing import names working
# ---------------------------------------------------------------------------

def calc_momentum_package(df: pd.DataFrame) -> Dict:
    """Legacy alias: delegate to MomentumSkill.analyze_bars."""
    return momentum_skill.analyze_bars(df)


def calc_volatility_bands(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> Dict:
    """Legacy alias: delegate to VolatilitySkill.analyze_bars."""
    return volatility_skill.analyze_bars(df, period=period, num_std=num_std)


def calc_volume_flow(df: pd.DataFrame) -> Dict:
    """Legacy alias: delegate to VolumeSkill.analyze_bars."""
    return volume_skill.analyze_bars(df)


def analyze_candle_structure(df: pd.DataFrame, lookback: int = 5) -> Dict:
    """Legacy alias: delegate to CandlestickSkill.analyze_bars."""
    return candlestick_skill.analyze_bars(df, lookback=lookback)


# MeanReversionStrategy kept as a class alias for backward-compat with registry
MeanReversionStrategy = MeanReversionSkill

__all__ = [
    # Core indicator classes
    "MomentumSkill",
    "VolatilitySkill",
    "VolumeSkill",
    "CandlestickSkill",
    "MeanReversionSkill",
    # Day trading strategy classes
    "VWAPReversionSkill",
    "OpeningRangeBreakoutSkill",
    "RSIDivergenceScalpSkill",
    "MomentumBurstSkill",
    # Swing strategy classes
    "GoldenCrossSkill",
    "Breakout52WeekSkill",
    "MeanReversionDailySkill",
    "EarningsDriftSkill",
    # Core singletons
    "momentum_skill",
    "volatility_skill",
    "volume_skill",
    "candlestick_skill",
    "mean_reversion_skill",
    # New strategy singletons
    "vwap_reversion_skill",
    "opening_range_breakout_skill",
    "rsi_divergence_scalp_skill",
    "momentum_burst_skill",
    "golden_cross_skill",
    "breakout_52w_skill",
    "mean_reversion_daily_skill",
    "earnings_drift_skill",
    # Signal factory functions (backtester compatible)
    "make_vwap_reversion_signals",
    "make_opening_range_breakout_signals",
    "make_rsi_divergence_signals",
    "make_momentum_burst_signals",
    "make_golden_cross_signals",
    "make_breakout_52w_signals",
    "make_mean_reversion_daily_signals",
    "make_earnings_drift_signals",
    # Legacy function aliases
    "calc_momentum_package",
    "calc_volatility_bands",
    "calc_volume_flow",
    "analyze_candle_structure",
    "MeanReversionStrategy",
]
