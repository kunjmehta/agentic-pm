"""High-level orchestrator for backtesting operations.

Provides clean API for skills to execute backtests, forward simulations,
and position swap analysis. Coordinates engine, portfolio, and metrics modules.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Dict, Optional, Callable
import pandas as pd
from datetime import date

try:
    from src.agentic.agents.backtester.core.bt_types import (
        PortfolioSnapshot, BacktestResult, PositionState
    )
    from src.agentic.agents.backtester.core.engine import BacktestEngine
    from src.agentic.agents.backtester.core.portfolio import Portfolio
    from src.agentic.agents.backtester.core.metrics import calculate_all_metrics
    from src.agentic.agents.backtester.core.valuation import calculate_portfolio_value
except ModuleNotFoundError:
    from bt_types import PortfolioSnapshot, BacktestResult, PositionState
    from engine import BacktestEngine
    from portfolio import Portfolio
    from metrics import calculate_all_metrics
    from valuation import calculate_portfolio_value


# =============================================================================
# Full Backtest with Strategy
# =============================================================================

def run_backtest(
    strategy_name: str,
    symbol: str,
    start_date: date,
    end_date: date,
    initial_capital: float,
    bars_df: pd.DataFrame,
    strategy_signals: Optional[Callable] = None,
    save_to_db: bool = False
) -> BacktestResult:
    """Execute full backtest with strategy signals.

    High-level orchestration that:
    1. Initializes Portfolio and BacktestEngine
    2. Runs bar-by-bar simulation
    3. Calculates performance metrics
    4. Optionally saves results to database

    Args:
        strategy_name: Name of strategy being tested
        symbol: Stock ticker symbol
        start_date: Start date for backtest
        end_date: End date for backtest
        initial_capital: Starting capital
        bars_df: DataFrame with OHLCV data
        strategy_signals: Optional callable for strategy signals
        save_to_db: Whether to persist results to database

    Returns:
        BacktestResult with trades, metrics, summary, recommendation
    """
    # Initialize engine
    engine = BacktestEngine(
        initial_capital=initial_capital,
        strategy_signals=strategy_signals
    )

    # Run simulation
    result = engine.run(bars_df, start_date, end_date, symbol)

    # Update strategy name
    result["strategy"] = strategy_name

    # TODO: Save to database if requested
    if save_to_db:
        # Will integrate with BacktestDAO
        pass

    return result


# =============================================================================
# Forward Simulation (No Trades)
# =============================================================================

def run_snapshot_forward_simulation(
    snapshot: PortfolioSnapshot,
    end_date: date,
    bars_df: pd.DataFrame
) -> Dict:
    """Forward simulate a portfolio snapshot to end_date (no trading).

    Calculates what the snapshot portfolio would be worth at end_date
    if positions were held unchanged (buy-and-hold).

    Args:
        snapshot: Portfolio snapshot with positions
        end_date: Date to simulate forward to
        bars_df: Historical bars data for position symbols

    Returns:
        Dict with initial_worth, final_worth, return_pct, positions, metrics
    """
    snapshot_date = snapshot.get("date")
    if not snapshot_date:
        return {"error": "Snapshot missing date field"}

    positions = snapshot.get("positions", {})
    if not positions:
        return {
            "snapshot_date": str(snapshot_date),
            "end_date": str(end_date),
            "initial_worth": snapshot.get("equity", 0.0),
            "final_worth": snapshot.get("cash", 0.0),
            "return_pct": 0.0,
            "return_dollars": 0.0,
            "positions": {},
            "message": "No positions to simulate"
        }

    # Get symbols from positions
    symbols = list(positions.keys())

    # Get prices at snapshot_date
    snapshot_prices = {}
    for symbol in symbols:
        pos = positions[symbol]
        snapshot_prices[symbol] = pos.get("current_price", pos.get("cost_basis", 0.0))

    # Calculate initial worth
    cash = snapshot.get("cash", 0.0)
    initial_worth = calculate_portfolio_value(cash, positions, snapshot_prices)

    # Get prices at end_date
    end_prices = _get_prices_at_date(bars_df, end_date, symbols)

    if not end_prices:
        return {
            "error": f"No price data available at {end_date} for symbols: {symbols}"
        }

    # Calculate final worth (same positions, new prices)
    final_worth = calculate_portfolio_value(cash, positions, end_prices)

    # Calculate returns
    return_dollars = final_worth - initial_worth
    return_pct = (return_dollars / initial_worth * 100) if initial_worth > 0 else 0.0

    # Update position values at end_date
    updated_positions = {}
    for symbol, pos in positions.items():
        if symbol in end_prices:
            quantity = pos.get("quantity", 0)
            cost_basis = pos.get("cost_basis", 0.0)
            new_price = end_prices[symbol]
            market_value = quantity * new_price
            unrealized_pnl = (new_price - cost_basis) * quantity

            updated_positions[symbol] = {
                "symbol": symbol,
                "quantity": quantity,
                "cost_basis": cost_basis,
                "current_price": new_price,
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": (unrealized_pnl / (cost_basis * quantity) * 100) if cost_basis > 0 else 0.0
            }

    return {
        "snapshot_date": str(snapshot_date),
        "end_date": str(end_date),
        "initial_worth": initial_worth,
        "final_worth": final_worth,
        "return_pct": return_pct,
        "return_dollars": return_dollars,
        "positions_at_end": updated_positions,
        "metrics": {
            "total_return_pct": return_pct,
            "total_return_dollars": return_dollars
        }
    }


# =============================================================================
# Position Swap Simulation
# =============================================================================

def run_swap_simulation(
    snapshot: PortfolioSnapshot,
    end_date: date,
    bars_df: pd.DataFrame,
    swaps: Dict[str, Dict]
) -> Dict:
    """Simulate position swaps at snapshot_date and forward simulate.

    Swaps are instantaneous position replacements (NOT buy/sell trades).
    Example: Replace 50 shares of AAPL with 50 shares of TSLA at snapshot_date,
    then hold until end_date.

    Args:
        snapshot: Portfolio snapshot with positions
        end_date: Date to simulate forward to
        bars_df: Historical bars data
        swaps: Dict mapping symbol -> {"swap_to": "NEW_SYMBOL", "quantity": N}

    Returns:
        Dict with swaps_applied, initial_worth, final_worth, return_pct
    """
    snapshot_date = snapshot.get("date")
    if not snapshot_date:
        return {"error": "Snapshot missing date field"}

    positions = snapshot.get("positions", {})
    cash = snapshot.get("cash", 0.0)

    # Validate swaps
    for symbol, swap_info in swaps.items():
        if symbol not in positions:
            return {"error": f"Cannot swap {symbol} - position does not exist in snapshot"}

        swap_qty = swap_info.get("quantity", 0)
        current_qty = positions[symbol].get("quantity", 0)

        if swap_qty > current_qty:
            return {
                "error": f"Cannot swap {swap_qty} shares of {symbol} - only {current_qty} available"
            }

    # Get prices at snapshot_date for all symbols
    all_symbols = list(positions.keys()) + [s["swap_to"] for s in swaps.values()]
    snapshot_prices = _get_prices_at_date(bars_df, snapshot_date, all_symbols)

    if not snapshot_prices:
        return {"error": f"No price data at {snapshot_date}"}

    # Calculate initial worth (before swaps)
    initial_worth = calculate_portfolio_value(cash, positions, snapshot_prices)

    # Create modified positions with swaps
    modified_positions = dict(positions)

    swaps_applied = []
    for old_symbol, swap_info in swaps.items():
        new_symbol = swap_info["swap_to"]
        swap_quantity = swap_info["quantity"]

        # Remove from old position
        modified_positions[old_symbol]["quantity"] -= swap_quantity

        # Remove position if fully swapped
        if modified_positions[old_symbol]["quantity"] == 0:
            del modified_positions[old_symbol]

        # Add to new position (instantaneous replacement at snapshot_date prices)
        if new_symbol in modified_positions:
            # Add to existing position
            existing_qty = modified_positions[new_symbol]["quantity"]
            existing_basis = modified_positions[new_symbol]["cost_basis"]
            new_price = snapshot_prices.get(new_symbol, 0.0)

            # Average cost basis
            new_cost_basis = ((existing_qty * existing_basis) + (swap_quantity * new_price)) / (existing_qty + swap_quantity)
            modified_positions[new_symbol]["quantity"] += swap_quantity
            modified_positions[new_symbol]["cost_basis"] = new_cost_basis
        else:
            # Create new position
            new_price = snapshot_prices.get(new_symbol, 0.0)
            modified_positions[new_symbol] = {
                "symbol": new_symbol,
                "quantity": swap_quantity,
                "cost_basis": new_price,
                "current_price": new_price,
                "market_value": swap_quantity * new_price,
                "unrealized_pnl": 0.0,
                "unrealized_pnl_pct": 0.0,
                "side": "long"
            }

        swaps_applied.append({
            "from": old_symbol,
            "to": new_symbol,
            "quantity": swap_quantity,
            "price_at_swap": snapshot_prices.get(new_symbol, 0.0)
        })

    # Forward simulate modified positions
    modified_snapshot = {
        "date": snapshot_date,
        "cash": cash,
        "equity": calculate_portfolio_value(cash, modified_positions, snapshot_prices),
        "positions": modified_positions
    }

    forward_result = run_snapshot_forward_simulation(modified_snapshot, end_date, bars_df)

    # Add swap information
    forward_result["swaps_applied"] = swaps_applied
    forward_result["initial_worth_before_swap"] = initial_worth

    return forward_result


# =============================================================================
# Helper Functions
# =============================================================================

def _get_prices_at_date(bars_df: pd.DataFrame, target_date: date, symbols: list) -> Dict[str, float]:
    """Get closing prices for symbols at target_date.

    Args:
        bars_df: DataFrame with OHLCV data
        target_date: Date to get prices for
        symbols: List of symbols

    Returns:
        Dict mapping symbol -> close price
    """
    if bars_df.empty:
        return {}

    # Ensure timestamp column
    if 'timestamp' not in bars_df.columns:
        return {}

    # Convert to datetime if needed
    bars_df = bars_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(bars_df['timestamp']):
        bars_df['timestamp'] = pd.to_datetime(bars_df['timestamp'])

    # Filter to target date
    bars_df['date'] = bars_df['timestamp'].dt.date
    day_bars = bars_df[bars_df['date'] == target_date]

    if day_bars.empty:
        return {}

    # Get last close for each symbol
    prices = {}
    if 'symbol' in day_bars.columns:
        for symbol in symbols:
            symbol_bars = day_bars[day_bars['symbol'] == symbol]
            if not symbol_bars.empty:
                prices[symbol] = symbol_bars.iloc[-1]['close']
    else:
        # Single symbol case
        if symbols and len(day_bars) > 0:
            prices[symbols[0]] = day_bars.iloc[-1]['close']

    return prices


# =============================================================================
# Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Test controller functions."""
    print("=" * 60)
    print("Controller Tests")
    print("=" * 60)

    # Create sample data
    dates = pd.date_range(start='2024-01-02', end='2024-01-05', freq='D')
    bars_data = []

    for day in dates:
        for hour in range(10, 16):
            timestamp = day.replace(hour=hour, minute=0)
            bars_data.append({
                'timestamp': timestamp,
                'open': 150.0 + (day.day - 2) * 5,
                'high': 151.0 + (day.day - 2) * 5,
                'low': 149.0 + (day.day - 2) * 5,
                'close': 150.5 + (day.day - 2) * 5,
                'volume': 1000000
            })

    bars_df = pd.DataFrame(bars_data)
    print(f"\n1. Created sample data: {len(bars_df)} bars")

    # Test 2: Full backtest
    print("\n2. run_backtest():")
    result = run_backtest(
        strategy_name="buy-and-hold",
        symbol="AAPL",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 5),
        initial_capital=100000.0,
        bars_df=bars_df
    )
    print(f"   Status: {result['status']}")
    print(f"   Return: {result['metrics'].get('total_return_pct', 0):.2f}%")
    print(f"   Recommendation: {result['recommendation'][:50]}...")

    # Test 3: Forward simulation
    print("\n3. run_snapshot_forward_simulation():")
    snapshot: PortfolioSnapshot = {
        "date": date(2024, 1, 2),
        "cash": 50000.0,
        "equity": 65000.0,
        "positions": {
            "AAPL": {
                "symbol": "AAPL",
                "quantity": 100,
                "cost_basis": 150.0,
                "current_price": 150.5,
                "market_value": 15050.0,
                "unrealized_pnl": 50.0,
                "unrealized_pnl_pct": 0.33,
                "side": "long"
            }
        }
    }

    forward_result = run_snapshot_forward_simulation(
        snapshot=snapshot,
        end_date=date(2024, 1, 5),
        bars_df=bars_df
    )
    print(f"   Initial Worth: ${forward_result.get('initial_worth', 0):,.2f}")
    print(f"   Final Worth: ${forward_result.get('final_worth', 0):,.2f}")
    print(f"   Return: {forward_result.get('return_pct', 0):.2f}%")

    # Test 4: Swap simulation
    print("\n4. run_swap_simulation():")
    swaps = {
        "AAPL": {"swap_to": "TSLA", "quantity": 50}
    }

    # Note: This will fail without TSLA data, but demonstrates the API
    print(f"   Swaps: Swap 50 AAPL -> TSLA")
    print(f"   (Skipping actual test - requires multi-symbol data)")

    print("\n" + "=" * 60)
    print("Controller tests completed!")
    print("=" * 60)
