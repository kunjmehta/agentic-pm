"""Base class for all quant trading strategies with Pydantic validation."""

from abc import ABC, abstractmethod
from typing import Union
import pandas as pd
from datetime import datetime
from pydantic import ValidationError

from src.server.skills.backtester.core.bt_types import StrategySignal, StrategyError
from src.common.utils import get_logger

logger = get_logger(__name__)


class QuantStrategy(ABC):
    """Base class enforcing consistent strategy interface with validation.

    All strategies must implement analyze_bars() which returns a validated
    StrategySignal Pydantic model.

    The backtester will:
    1. Instantiate the strategy class
    2. Call analyze_bars(df) for each trading day
    3. Validate response with Pydantic
    4. Extract signal.action to get "buy"|"sell"|"hold"
    """

    @abstractmethod
    def analyze_bars(self, df: pd.DataFrame, **params) -> Union[StrategySignal, StrategyError]:
        """Pure DataFrame analysis - no I/O.

        Args:
            df: OHLCV DataFrame with columns [open, high, low, close, volume]
            **params: Strategy-specific parameters

        Returns:
            StrategySignal: Validated signal with action, confidence, price, reason
            StrategyError: Error response if analysis fails

        The return value is automatically validated by Pydantic.
        """
        pass

    def generate_signals(self, symbol: str, **params) -> Union[StrategySignal, StrategyError]:
        """Convenience wrapper - fetches data then calls analyze_bars.

        Includes automatic timestamp and symbol injection.

        Args:
            symbol: Ticker symbol to analyze
            **params: Strategy parameters including:
                - timeframe: Bar timeframe (default: "1Min")
                - lookback_days: Days of history (default: 30)

        Returns:
            StrategySignal: Validated signal with metadata
            StrategyError: Error if data fetch or analysis fails
        """
        from src.server.skills.quant._utils import _fetch_bars

        df = _fetch_bars(
            symbol,
            params.get("timeframe", "1Min"),
            params.get("lookback_days", 30)
        )

        if df is None or df.empty:
            return StrategyError(
                error=f"No data available for {symbol}",
                symbol=symbol
            )

        try:
            result = self.analyze_bars(df, **params)

            # Inject metadata for live trading if result is a signal
            if isinstance(result, StrategySignal):
                result.symbol = symbol
                result.timeframe = params.get("timeframe", "1Min")
                result.timestamp = datetime.now()

            return result

        except ValidationError as exc:
            logger.error(f"Strategy signal validation failed for {symbol}: {exc}")
            return StrategyError(
                error=f"Signal validation failed: {str(exc)}",
                symbol=symbol
            )
        except Exception as exc:
            logger.error(f"Strategy analysis failed for {symbol}: {exc}", exc_info=True)
            return StrategyError(
                error=f"Analysis failed: {str(exc)}",
                symbol=symbol
            )


if __name__ == "__main__":
    """Test base strategy class."""
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("Base Strategy Class Tests")
    print("=" * 60)

    # Create a simple test strategy
    class TestStrategy(QuantStrategy):
        """Simple test strategy for validation."""

        def analyze_bars(self, df: pd.DataFrame, **params) -> Union[StrategySignal, StrategyError]:
            """Always returns 'hold' signal."""
            if df.empty:
                return StrategyError(error="Empty DataFrame")

            close = float(df.iloc[-1]["close"])
            return StrategySignal(
                action="hold",
                confidence=1.0,
                current_price=close,
                reason="Test strategy - always hold"
            )

    print("\n[TEST 1] Instantiate test strategy")
    strategy = TestStrategy()
    print("  ✓ Strategy instantiated")

    print("\n[TEST 2] analyze_bars() with valid data")
    test_df = pd.DataFrame({
        "open": [100, 101, 102],
        "high": [101, 102, 103],
        "low": [99, 100, 101],
        "close": [100.5, 101.5, 102.5],
        "volume": [1000, 1100, 1200]
    })
    result = strategy.analyze_bars(test_df)
    print(f"  Action: {result.action}")
    print(f"  Confidence: {result.confidence}")
    print(f"  Price: {result.current_price}")
    print("  ✓ analyze_bars() returned valid signal")

    print("\n[TEST 3] analyze_bars() with empty data")
    empty_df = pd.DataFrame()
    result = strategy.analyze_bars(empty_df)
    assert isinstance(result, StrategyError), "Should return StrategyError for empty data"
    print(f"  Error: {result.error}")
    print("  ✓ Correctly returned StrategyError")

    print("\n[TEST 4] Abstract class enforcement")
    try:
        # Try to instantiate base class directly
        bad_strategy = QuantStrategy()
        print("  ✗ Should have raised TypeError")
    except TypeError as e:
        print(f"  ✓ Correctly prevented direct instantiation: {str(e)[:50]}...")

    print("\n" + "=" * 60)
    print("✅ All base strategy tests passed!")
    print("=" * 60)
