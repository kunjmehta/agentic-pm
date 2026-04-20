"""Centralized strategy registration module.

This module imports all strategy classes and registers them with metadata.
Import this module AFTER all strategy classes have been defined to avoid
circular dependencies.

Usage:
    from src.server.registry.register_strategies import ensure_strategies_registered
    ensure_strategies_registered()  # Call once at startup
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.registry import strategy_registry as _registry
from src.common.registry.strategy_registry import get_registry  # backward-compat shim kept for callers
from src.common.registry.strategy_metadata import StrategyMetadata
from src.common.utils import get_logger

logger = get_logger(__name__)

_strategies_registered = False


def register_all_strategies():
    """Register all strategy classes with their metadata.

    This function should be called once at application startup, after all
    strategy modules have been imported.
    """
    global _strategies_registered
    if _strategies_registered:
        logger.debug("Strategies already registered, skipping")
        return

    # Import all strategy classes (lazy import to avoid circular dependencies)
    from src.server.skills.quant.mean_reversion import MeanReversionSkill
    from src.server.skills.quant.vwap_reversion import VWAPReversionSkill
    from src.server.skills.quant.opening_range_breakout import OpeningRangeBreakoutSkill
    from src.server.skills.quant.rsi_divergence_scalp import RSIDivergenceScalpSkill
    from src.server.skills.quant.momentum_burst import MomentumBurstSkill
    from src.server.skills.quant.golden_cross import GoldenCrossSkill
    from src.server.skills.quant.breakout_52w import Breakout52WeekSkill
    from src.server.skills.quant.earnings_drift import EarningsDriftSkill

    # Register mean-reversion (intraday)
    _registry.register(
        StrategyMetadata(
            name="mean-reversion",
            display_name="Mean Reversion (Intraday)",
            description="Z-score / MA / Bollinger Band mean reversion for intraday trading",
            category="intraday",
            timeframes=["1Min", "5Min", "15Min", "1Hour"],
            min_bars=120,
            parameters={
                "threshold": {
                    "type": "float",
                    "default": 2.5,
                    "min": 1.0,
                    "max": 4.0,
                    "description": "Z-score threshold for entry signal",
                },
                "ma_period": {
                    "type": "int",
                    "default": 20,
                    "min": 10,
                    "max": 50,
                    "description": "Moving average period",
                },
                "lookback": {
                    "type": "int",
                    "default": 120,
                    "min": 60,
                    "max": 300,
                    "description": "Number of bars for statistical analysis",
                },
                "sr_lookback": {
                    "type": "int",
                    "default": 60,
                    "min": 20,
                    "max": 200,
                    "description": "Bars for support/resistance calculation",
                },
            },
            tags=["mean-reversion", "statistical", "bollinger-bands", "z-score"],
            config_prefix="strategy.mean_reversion",
        ),
        MeanReversionSkill,
    )

    # Register VWAP reversion
    _registry.register(
        StrategyMetadata(
            name="vwap-reversion",
            display_name="VWAP Reversion",
            description="Intraday mean reversion to VWAP with volume confirmation",
            category="intraday",
            timeframes=["1Min", "5Min", "15Min"],
            min_bars=26,
            parameters={
                "dev_pct": {
                    "type": "float",
                    "default": 0.005,
                    "min": 0.001,
                    "max": 0.05,
                    "description": "Minimum deviation from VWAP (0.5%)",
                },
                "vol_mult": {
                    "type": "float",
                    "default": 2.0,
                    "min": 1.0,
                    "max": 5.0,
                    "description": "Volume multiplier vs 20-bar average",
                },
                "stop_pct": {
                    "type": "float",
                    "default": 0.003,
                    "min": 0.001,
                    "max": 0.02,
                    "description": "Stop-loss distance (0.3%)",
                },
            },
            tags=["mean-reversion", "vwap", "volume", "intraday"],
            config_prefix="strategy.vwap_reversion",
        ),
        VWAPReversionSkill,
    )

    # Register opening range breakout
    _registry.register(
        StrategyMetadata(
            name="opening-range-breakout",
            display_name="Opening Range Breakout",
            description="First N-minute range breakout with volume confirmation",
            category="intraday",
            timeframes=["1Min", "5Min"],
            min_bars=20,
            parameters={
                "range_bars": {
                    "type": "int",
                    "default": 15,
                    "min": 5,
                    "max": 60,
                    "description": "Number of bars for opening range (15 = 15min on 1Min)",
                },
            },
            tags=["breakout", "opening-range", "volume", "day-trading"],
            config_prefix="strategy.opening_range_breakout",
        ),
        OpeningRangeBreakoutSkill,
    )

    # Register RSI divergence scalp
    _registry.register(
        StrategyMetadata(
            name="rsi-divergence",
            display_name="RSI Divergence Scalp",
            description="Bullish/bearish divergence between price and RSI",
            category="intraday",
            timeframes=["1Min", "5Min", "15Min"],
            min_bars=20,
            parameters={
                "lookback": {
                    "type": "int",
                    "default": 20,
                    "min": 10,
                    "max": 50,
                    "description": "Bars to scan for divergence",
                },
                "oversold": {
                    "type": "float",
                    "default": 35.0,
                    "min": 20.0,
                    "max": 40.0,
                    "description": "RSI oversold threshold",
                },
            },
            tags=["rsi", "divergence", "scalping", "momentum"],
            config_prefix="strategy.rsi_divergence",
        ),
        RSIDivergenceScalpSkill,
    )

    # Register momentum burst
    _registry.register(
        StrategyMetadata(
            name="momentum-burst",
            display_name="Momentum Burst",
            description="Sudden price move with volume spike",
            category="intraday",
            timeframes=["1Min", "5Min", "15Min"],
            min_bars=10,
            parameters={
                "vol_mult": {
                    "type": "float",
                    "default": 3.0,
                    "min": 2.0,
                    "max": 5.0,
                    "description": "Volume spike multiplier",
                },
                "min_move": {
                    "type": "float",
                    "default": 0.005,
                    "min": 0.002,
                    "max": 0.02,
                    "description": "Minimum price move threshold (0.5%)",
                },
                "trail_pct": {
                    "type": "float",
                    "default": 0.002,
                    "min": 0.001,
                    "max": 0.01,
                    "description": "Trailing stop percentage (0.2%)",
                },
            },
            tags=["momentum", "volume", "breakout", "scalping"],
            config_prefix="strategy.momentum_burst",
        ),
        MomentumBurstSkill,
    )

    # Register golden cross (swing/position)
    _registry.register(
        StrategyMetadata(
            name="golden-cross",
            display_name="Golden Cross",
            description="50/200 moving average crossover for position trading",
            category="daily",
            timeframes=["1Day"],
            min_bars=200,
            parameters={
                "fast": {
                    "type": "int",
                    "default": 50,
                    "min": 20,
                    "max": 100,
                    "description": "Fast MA period",
                },
                "slow": {
                    "type": "int",
                    "default": 200,
                    "min": 100,
                    "max": 300,
                    "description": "Slow MA period",
                },
            },
            tags=["moving-average", "crossover", "swing", "position"],
            config_prefix="strategy.golden_cross",
        ),
        GoldenCrossSkill,
    )

    # Register 52-week breakout
    _registry.register(
        StrategyMetadata(
            name="breakout-52w",
            display_name="52-Week Breakout",
            description="Breakout above 52-week high with volume confirmation",
            category="daily",
            timeframes=["1Day"],
            min_bars=252,
            parameters={
                "lookback": {
                    "type": "int",
                    "default": 252,
                    "min": 200,
                    "max": 300,
                    "description": "Lookback period (252 = ~1 year)",
                },
                "vol_mult": {
                    "type": "float",
                    "default": 1.5,
                    "min": 1.0,
                    "max": 3.0,
                    "description": "Volume multiplier",
                },
                "trail_pct": {
                    "type": "float",
                    "default": 0.10,
                    "min": 0.05,
                    "max": 0.20,
                    "description": "Trailing stop percentage (10%)",
                },
            },
            tags=["breakout", "52-week", "volume", "swing"],
            config_prefix="strategy.breakout_52w",
        ),
        Breakout52WeekSkill,
    )

    # Register earnings drift
    _registry.register(
        StrategyMetadata(
            name="earnings-drift",
            display_name="Earnings Drift",
            description="Post-earnings announcement drift strategy",
            category="daily",
            timeframes=["1Day"],
            min_bars=10,
            parameters={
                "lookback": {
                    "type": "int",
                    "default": 10,
                    "min": 5,
                    "max": 20,
                    "description": "Days to check for earnings move",
                },
                "min_move": {
                    "type": "float",
                    "default": 0.04,
                    "min": 0.02,
                    "max": 0.10,
                    "description": "Minimum post-earnings move (4%)",
                },
                "vol_mult": {
                    "type": "float",
                    "default": 2.0,
                    "min": 1.0,
                    "max": 5.0,
                    "description": "Volume multiplier",
                },
                "hold_days": {
                    "type": "int",
                    "default": 5,
                    "min": 3,
                    "max": 10,
                    "description": "Days to hold position",
                },
            },
            tags=["earnings", "event-driven", "drift", "swing"],
            config_prefix="strategy.earnings_drift",
        ),
        EarningsDriftSkill,
    )

    _strategies_registered = True
    logger.info(f"Registered {_registry.count()} strategies: {', '.join(_registry.get_all_names())}")


def ensure_strategies_registered():
    """Ensure strategies are registered (idempotent).

    Call this at application startup or before using the registry.
    """
    register_all_strategies()


def reset_registration_flag():
    """Reset the registration flag (for testing only).

    This allows tests to call register_all_strategies() again after
    clearing the registry.
    """
    global _strategies_registered
    _strategies_registered = False
