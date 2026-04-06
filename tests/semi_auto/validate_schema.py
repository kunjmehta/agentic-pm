"""Schema validation for strategy outputs."""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.semi_auto.skills.quant.mean_reversion import mean_reversion_skill
from src.semi_auto.skills.quant.golden_cross import golden_cross_skill
from src.semi_auto.skills.quant.vwap_reversion import vwap_reversion_skill
from src.semi_auto.skills.quant.rsi_divergence_scalp import rsi_divergence_scalp_skill
from src.semi_auto.skills.quant.earnings_drift import earnings_drift_skill
from src.semi_auto.skills.quant.opening_range_breakout import opening_range_breakout_skill
from src.semi_auto.skills.quant.momentum_burst import momentum_burst_skill
from src.semi_auto.skills.quant.breakout_52w import breakout_52w_skill

def create_test_df(bars=100):
    """Create test data with sufficient bars."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=bars, freq='1min')
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(bars) * 0.5)
    return pd.DataFrame({
        'open': close + np.random.randn(bars) * 0.1,
        'high': close + abs(np.random.randn(bars) * 0.3),
        'low': close - abs(np.random.randn(bars) * 0.3),
        'close': close,
        'volume': np.random.randint(10000, 100000, bars),
    }, index=dates)

def validate_strategy_output(name, result):
    """Validate strategy output has required top-level keys."""
    required_keys = ['action', 'confidence']
    optional_keys = ['indicators', 'statistics', 'parameters']

    missing = [k for k in required_keys if k not in result]
    if missing:
        print(f"FAIL {name}: Missing required keys: {missing}")
        return False

    # Check for structured blocks (good practice but not required)
    has_blocks = all(k in result for k in optional_keys)
    if not has_blocks:
        missing_blocks = [k for k in optional_keys if k not in result]
        print(f"WARN {name}: Missing optional blocks: {missing_blocks}")

    print(f"PASS {name}: Has required keys (action={result['action']}, confidence={result['confidence']})")
    return True

def main():
    """Test all strategies for schema consistency."""
    df = create_test_df(300)  # Enough for daily strategies

    strategies = [
        ("mean_reversion", lambda: mean_reversion_skill.analyze_bars(df, lookback=60)),
        ("golden_cross", lambda: golden_cross_skill.analyze_bars(df, fast=50, slow=200)),
        ("vwap_reversion", lambda: vwap_reversion_skill.analyze_bars(df)),
        ("rsi_divergence", lambda: rsi_divergence_scalp_skill.analyze_bars(df)),
        ("earnings_drift", lambda: earnings_drift_skill.analyze_bars(df)),
        ("opening_range", lambda: opening_range_breakout_skill.analyze_bars(df)),
        ("momentum_burst", lambda: momentum_burst_skill.analyze_bars(df)),
        ("breakout_52w", lambda: breakout_52w_skill.analyze_bars(df)),
    ]

    print("=== Schema Validation ===\n")
    passed = 0
    for name, fn in strategies:
        try:
            result = fn()
            if validate_strategy_output(name, result):
                passed += 1
        except Exception as e:
            print(f"FAIL {name}: Exception - {e}")

    print(f"\n{passed}/{len(strategies)} strategies passed schema validation")
    return passed == len(strategies)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
