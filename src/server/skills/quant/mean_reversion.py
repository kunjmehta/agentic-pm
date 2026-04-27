"""MeanReversionSkill — Z-score / MA / Bollinger mean-reversion signals."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)


class MeanReversionSkill:
    """Mean-reversion strategy analyser combining statistics, MAs, and bands.

    Supports both intraday and daily timeframes.

    Workflow A (backtesting): ``analyze_bars(df, threshold, ma_period)``
    takes a pre-fetched DataFrame and returns signals without any DAO call.

    Workflow B (signal generation): ``generate_signals(symbol, ...)``
    fetches data from AlpacaDAO and returns the full analysis dict including
    a trade recommendation.

    For daily timeframes, pass ``timeframe="1Day"`` to ``generate_signals``.
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
            sr_lookback: Bars to scan for support/resistance pivots. Defaults to 60.

        Returns:
            Analysis dict with statistics, moving_averages, signals,
            levels, trade_recommendation.
        """
        min_bars = max(lookback, sr_lookback, 50)
        if df.empty or len(df) < min_bars:
            return {
                "error": f"Insufficient data for mean-reversion analysis (need {min_bars} bars, got {len(df)})",
                "action": "hold",
                "confidence": 0.0,
            }

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
            "parameters": {
                "lookback": lookback,
                "threshold": threshold,
                "ma_period": ma_period,
                "sr_lookback": sr_lookback,
            },
            # Add top-level keys for uniform access
            "action": recommendation.get("action", "hold"),
            "confidence": recommendation.get("confidence", 0.0),
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

        result = self.analyze_bars(
            df, threshold=threshold, ma_period=ma_period,
            lookback=lookback, sr_lookback=sr_lookback,
        )
        result["symbol"] = symbol.upper()
        result["timestamp"] = datetime.now().isoformat()
        # Add top-level keys for uniform access
        result["action"] = result.get("trade_recommendation", {}).get("action", "hold")
        result["confidence"] = result.get("trade_recommendation", {}).get("confidence", 0.0)
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
            Dict with upper_band, middle_band, lower_band, or ``{}`` if insufficient.
        """
        if df.empty or len(df) < ma_period:
            return {}
        if lookback < ma_period:
            lookback = ma_period
        prices = df["close"].tail(lookback)
        sma = prices.rolling(ma_period).mean()
        std = prices.rolling(ma_period).std(ddof=1)  # Sample std (industry standard)
        return {
            "upper_band": round(float((sma + std * 2).iloc[-1]), 2),
            "middle_band": round(float(sma.iloc[-1]), 2),
            "lower_band": round(float((sma - std * 2).iloc[-1]), 2),
        }

    def _calc_support_resistance(self, df: pd.DataFrame, sr_lookback: int = 60) -> Dict:
        """Calculate recent support and resistance levels.

        Args:
            df: Price DataFrame.
            sr_lookback: Number of bars to scan for high/low pivots.

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
            threshold: Z-score threshold used by the caller.

        Returns:
            Dict with action, confidence, reason, entry_price, stop_loss, take_profit.
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
        vwap_info = f" VWAP: ${vwap:.2f}." if vwap else ""
        # Invert confidence for hold: close to mean = high confidence hold
        hold_confidence = 1.0 - min(abs(z) / threshold, 0.9)  # z=0 → 1.0, z=threshold → 0.1
        return {
            "action": "hold",
            "confidence": round(max(hold_confidence, 0.1), 2),
            "reason": f"Price within normal range (Z={z:.2f}). No extreme deviation.{vwap_info}",
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
        }


# Singleton
mean_reversion_skill = MeanReversionSkill()

# Backward-compat alias used by registry
MeanReversionStrategy = MeanReversionSkill

__all__ = ["MeanReversionSkill", "mean_reversion_skill", "MeanReversionStrategy"]


if __name__ == "__main__":
    import numpy as np

    rng = np.random.default_rng(4)
    n = 80
    prices = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.002,
        "low": prices * 0.998,
        "close": prices,
        "volume": rng.integers(1000, 5000, n).astype(float),
    })
    result = MeanReversionSkill().analyze_bars(df)
    rec = result["trade_recommendation"]
    print(f"Action: {rec['action']}, confidence: {rec['confidence']}")
    print("MeanReversionSkill smoke test passed.")
