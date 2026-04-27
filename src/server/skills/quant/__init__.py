"""Quant skills package — re-exports all strategy and indicator classes.

Individual modules (one class per file):
    momentum_skill.py          — MomentumSkill (MACD + RSI)
    volatility_skill.py        — VolatilitySkill (Bollinger Bands)
    volume_skill.py            — VolumeSkill (OBV + volume flow)
    candlestick_skill.py       — CandlestickSkill (pattern detection)
    mean_reversion.py          — MeanReversionSkill (Z-score / MA / BB)
    vwap_reversion.py          — VWAPReversionSkill
    opening_range_breakout.py  — OpeningRangeBreakoutSkill
    rsi_divergence_scalp.py    — RSIDivergenceScalpSkill
    momentum_burst.py          — MomentumBurstSkill
    golden_cross.py            — GoldenCrossSkill
    breakout_52w.py            — Breakout52WeekSkill
    earnings_drift.py          — EarningsDriftSkill

The ``skills.py`` shim also re-exports all of these for backward compat.
"""

# Core indicator classes
from src.server.skills.quant.momentum_skill import (
    MomentumSkill,
    momentum_skill,
    calc_momentum_package,
)
from src.server.skills.quant.volatility_skill import (
    VolatilitySkill,
    volatility_skill,
    calc_volatility_bands,
)
from src.server.skills.quant.volume_skill import (
    VolumeSkill,
    volume_skill,
    calc_volume_flow,
)
from src.server.skills.quant.candlestick_skill import (
    CandlestickSkill,
    candlestick_skill,
    analyze_candle_structure,
)
from src.server.skills.quant.mean_reversion import (
    MeanReversionSkill,
    mean_reversion_skill,
    MeanReversionStrategy,
)

# Day trading strategy classes
from src.server.skills.quant.vwap_reversion import (
    VWAPReversionSkill,
    vwap_reversion_skill,
)
from src.server.skills.quant.opening_range_breakout import (
    OpeningRangeBreakoutSkill,
    opening_range_breakout_skill,
)
from src.server.skills.quant.rsi_divergence_scalp import (
    RSIDivergenceScalpSkill,
    rsi_divergence_scalp_skill,
)
from src.server.skills.quant.momentum_burst import (
    MomentumBurstSkill,
    momentum_burst_skill,
)

# Swing strategy classes
from src.server.skills.quant.golden_cross import (
    GoldenCrossSkill,
    golden_cross_skill,
)
from src.server.skills.quant.breakout_52w import (
    Breakout52WeekSkill,
    breakout_52w_skill,
)
from src.server.skills.quant.earnings_drift import (
    EarningsDriftSkill,
    earnings_drift_skill,
)

# Buy-and-hold strategy
from src.server.skills.quant.buy_and_hold import (
    BuyAndHoldSkill,
    buy_and_hold_skill,
)

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
    "BuyAndHoldSkill",
    # Core singletons
    "momentum_skill",
    "volatility_skill",
    "volume_skill",
    "candlestick_skill",
    "mean_reversion_skill",
    # Strategy singletons
    "vwap_reversion_skill",
    "opening_range_breakout_skill",
    "rsi_divergence_scalp_skill",
    "momentum_burst_skill",
    "golden_cross_skill",
    "breakout_52w_skill",
    "earnings_drift_skill",
    "buy_and_hold_skill",
    # Legacy aliases
    "calc_momentum_package",
    "calc_volatility_bands",
    "calc_volume_flow",
    "analyze_candle_structure",
    "MeanReversionStrategy",
]
