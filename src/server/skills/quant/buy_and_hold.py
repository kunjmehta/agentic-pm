"""Buy-and-hold strategy migrated from backtester/core/strategies.py."""

from typing import Union
import pandas as pd
from src.server.skills.quant.base_strategy import QuantStrategy
from src.server.skills.backtester.core.bt_types import StrategySignal, StrategyError


class BuyAndHoldSkill(QuantStrategy):
    """Simple buy-and-hold strategy with Pydantic validation.

    This strategy buys on the first signal and holds indefinitely.
    """

    def __init__(self):
        """Initialize buy-and-hold strategy."""
        self._bought = False

    def analyze_bars(self, df: pd.DataFrame, **params) -> Union[StrategySignal, StrategyError]:
        """Buy once on first call, hold thereafter.

        Args:
            df: OHLCV DataFrame with price data
            **params: Unused (buy-and-hold has no parameters)

        Returns:
            StrategySignal: Buy signal on first call, hold signal thereafter
            StrategyError: If no data provided
        """
        if df.empty:
            return StrategyError(error="No data provided")

        close = float(df.iloc[-1]["close"])

        if not self._bought:
            self._bought = True
            return StrategySignal(
                action="buy",
                confidence=1.0,
                current_price=close,
                reason="Initial buy (buy-and-hold strategy)",
                entry_price=close,
                parameters={"strategy": "buy-and-hold"}
            )

        return StrategySignal(
            action="hold",
            confidence=1.0,
            current_price=close,
            reason="Holding (buy-and-hold strategy)",
            parameters={"strategy": "buy-and-hold"}
        )


# Module-level singleton
buy_and_hold_skill = BuyAndHoldSkill()


__all__ = [
    "BuyAndHoldSkill",
    "buy_and_hold_skill",
]


if __name__ == "__main__":
    """Test buy-and-hold strategy."""
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("Buy-and-Hold Strategy Tests")
    print("=" * 60)

    # Create test data
    test_df = pd.DataFrame({
        "open": [100, 101, 102, 103, 104],
        "high": [101, 102, 103, 104, 105],
        "low": [99, 100, 101, 102, 103],
        "close": [100.5, 101.5, 102.5, 103.5, 104.5],
        "volume": [1000, 1100, 1200, 1300, 1400]
    })

    print("\n[TEST 1] Instantiate strategy")
    strategy = BuyAndHoldSkill()
    print("  ✓ Strategy instantiated")

    print("\n[TEST 2] First signal should be 'buy'")
    signal1 = strategy.analyze_bars(test_df)
    assert signal1.action == "buy", f"Expected 'buy', got '{signal1.action}'"
    print(f"  Action: {signal1.action}")
    print(f"  Confidence: {signal1.confidence}")
    print(f"  Price: {signal1.current_price}")
    print(f"  Reason: {signal1.reason}")
    print("  ✓ First signal is 'buy'")

    print("\n[TEST 3] Subsequent signals should be 'hold'")
    signal2 = strategy.analyze_bars(test_df)
    assert signal2.action == "hold", f"Expected 'hold', got '{signal2.action}'"
    print(f"  Action: {signal2.action}")
    print(f"  Reason: {signal2.reason}")
    print("  ✓ Second signal is 'hold'")

    print("\n[TEST 4] Multiple holds remain consistent")
    for i in range(3):
        signal = strategy.analyze_bars(test_df)
        assert signal.action == "hold", f"Call {i+3}: Expected 'hold', got '{signal.action}'"
    print("  ✓ All subsequent signals are 'hold'")

    print("\n[TEST 5] Empty DataFrame returns error")
    empty_df = pd.DataFrame()
    result = strategy.analyze_bars(empty_df)
    assert isinstance(result, StrategyError), "Should return StrategyError for empty data"
    print(f"  Error: {result.error}")
    print("  ✓ Correctly handled empty DataFrame")

    print("\n[TEST 6] Reset strategy for new instance")
    new_strategy = BuyAndHoldSkill()
    signal = new_strategy.analyze_bars(test_df)
    assert signal.action == "buy", "New instance should buy on first call"
    print("  ✓ New instance correctly starts with 'buy'")

    print("\n" + "=" * 60)
    print("✅ All buy-and-hold strategy tests passed!")
    print("=" * 60)
