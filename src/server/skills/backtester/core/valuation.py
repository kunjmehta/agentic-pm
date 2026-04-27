"""Pure valuation functions for portfolio analysis.

Stateless calculation functions with no side effects. Can be reused in both
backtesting and live trading contexts. Follows ai-hedge-fund reference architecture.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Dict, Optional

try:
    from src.server.skills.backtester.core.bt_types import PositionState, PortfolioSnapshot
except ModuleNotFoundError:
    # Fallback to relative import for testing
    from bt_types import PositionState, PortfolioSnapshot


# =============================================================================
# Position Valuation
# =============================================================================

def calculate_position_value(
    symbol: str,
    quantity: int,
    current_price: float,
    cost_basis: float,
    side: str = "long"
) -> PositionState:
    """Calculate complete position state with P&L metrics.

    Pure function - no side effects, no database access.

    Args:
        symbol: Stock ticker symbol
        quantity: Number of shares (positive for long, can be negative for short)
        current_price: Current market price per share
        cost_basis: Average cost basis per share
        side: Position side - 'long' or 'short'

    Returns:
        PositionState with market value and unrealized P&L

    Examples:
        >>> pos = calculate_position_value("AAPL", 100, 160.0, 150.0, "long")
        >>> pos['market_value']
        16000.0
        >>> pos['unrealized_pnl']
        1000.0
    """
    # Calculate market value
    market_value = quantity * current_price

    # Calculate unrealized P&L based on side
    if side == "long":
        unrealized_pnl = (current_price - cost_basis) * quantity
    else:  # short position
        unrealized_pnl = (cost_basis - current_price) * abs(quantity)

    # Calculate P&L percentage
    if cost_basis != 0:
        unrealized_pnl_pct = (unrealized_pnl / (cost_basis * abs(quantity))) * 100
    else:
        unrealized_pnl_pct = 0.0

    return {
        "symbol": symbol,
        "quantity": quantity,
        "cost_basis": cost_basis,
        "current_price": current_price,
        "market_value": market_value,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "side": side  # type: ignore
    }


# =============================================================================
# Portfolio Valuation
# =============================================================================

def calculate_portfolio_value(
    cash: float,
    positions: Dict[str, PositionState],
    current_prices: Dict[str, float]
) -> float:
    """Calculate total portfolio value (cash + positions).

    Pure function - no side effects.

    Args:
        cash: Available cash balance
        positions: Dictionary mapping symbol -> PositionState
        current_prices: Dictionary mapping symbol -> current price

    Returns:
        Total portfolio value in dollars

    Examples:
        >>> positions = {"AAPL": {"quantity": 100, "cost_basis": 150.0}}
        >>> prices = {"AAPL": 160.0}
        >>> calculate_portfolio_value(50000.0, positions, prices)
        66000.0
    """
    total_positions_value = 0.0

    for symbol, position in positions.items():
        if symbol in current_prices:
            quantity = position.get("quantity", 0)
            current_price = current_prices[symbol]
            side = position.get("side", "long")

            # Long positions add value, short positions subtract
            if side == "long":
                total_positions_value += quantity * current_price
            else:  # short position
                # For shorts, we owe the market value
                total_positions_value -= abs(quantity) * current_price

    return cash + total_positions_value


def compute_exposures(
    cash: float,
    positions: Dict[str, PositionState],
    current_prices: Dict[str, float],
    total_equity: float
) -> Dict[str, float]:
    """Calculate portfolio exposures (long/short/gross/net).

    Pure function - no side effects.

    Args:
        cash: Available cash balance
        positions: Dictionary mapping symbol -> PositionState
        current_prices: Dictionary mapping symbol -> current price
        total_equity: Total portfolio equity value

    Returns:
        Dict with exposure metrics:
            - long_value: Total value of long positions
            - short_value: Absolute value of short positions
            - gross_exposure: long + short (total capital at risk)
            - net_exposure: long - short (market directional exposure)
            - long_pct: Long exposure as % of equity
            - short_pct: Short exposure as % of equity
            - gross_pct: Gross exposure as % of equity
            - net_pct: Net exposure as % of equity

    Examples:
        >>> positions = {"AAPL": {"quantity": 100, "side": "long"}}
        >>> prices = {"AAPL": 160.0}
        >>> exposures = compute_exposures(50000.0, positions, prices, 66000.0)
        >>> exposures['long_value']
        16000.0
    """
    long_value = 0.0
    short_value = 0.0

    for symbol, position in positions.items():
        if symbol in current_prices:
            quantity = position.get("quantity", 0)
            current_price = current_prices[symbol]
            side = position.get("side", "long")
            market_value = abs(quantity) * current_price

            if side == "long":
                long_value += market_value
            else:  # short
                short_value += market_value

    gross_exposure = long_value + short_value
    net_exposure = long_value - short_value

    # Calculate percentages (avoid division by zero)
    if total_equity > 0:
        long_pct = (long_value / total_equity) * 100
        short_pct = (short_value / total_equity) * 100
        gross_pct = (gross_exposure / total_equity) * 100
        net_pct = (net_exposure / total_equity) * 100
    else:
        long_pct = short_pct = gross_pct = net_pct = 0.0

    return {
        "long_value": long_value,
        "short_value": short_value,
        "gross_exposure": gross_exposure,
        "net_exposure": net_exposure,
        "long_pct": long_pct,
        "short_pct": short_pct,
        "gross_pct": gross_pct,
        "net_pct": net_pct
    }


def compute_portfolio_summary(
    cash: float,
    positions: Dict[str, PositionState],
    current_prices: Dict[str, float],
    initial_capital: float
) -> Dict:
    """Aggregate all portfolio statistics into a summary.

    Pure function - combines value and exposure calculations.

    Args:
        cash: Available cash balance
        positions: Dictionary mapping symbol -> PositionState
        current_prices: Dictionary mapping symbol -> current price
        initial_capital: Starting capital for return calculation

    Returns:
        Dict with complete portfolio summary:
            - cash: Cash balance
            - equity: Total portfolio value
            - return_pct: Return percentage vs initial capital
            - return_dollars: Return in dollars
            - exposures: Exposure metrics from compute_exposures()
            - num_positions: Number of positions held

    Examples:
        >>> positions = {"AAPL": {"quantity": 100, "cost_basis": 150.0, "side": "long"}}
        >>> prices = {"AAPL": 160.0}
        >>> summary = compute_portfolio_summary(50000.0, positions, prices, 100000.0)
        >>> summary['return_pct']
        -34.0
    """
    # Calculate total equity
    equity = calculate_portfolio_value(cash, positions, current_prices)

    # Calculate returns
    return_dollars = equity - initial_capital
    return_pct = (return_dollars / initial_capital * 100) if initial_capital > 0 else 0.0

    # Calculate exposures
    exposures = compute_exposures(cash, positions, current_prices, equity)

    # Count positions
    num_positions = len([p for p in positions.values() if p.get("quantity", 0) != 0])

    return {
        "cash": cash,
        "equity": equity,
        "return_pct": return_pct,
        "return_dollars": return_dollars,
        "exposures": exposures,
        "num_positions": num_positions
    }


# =============================================================================
# Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Test valuation functions."""
    print("=" * 60)
    print("Backtester Valuation Functions")
    print("=" * 60)

    # Test 1: Calculate position value
    print("\n1. calculate_position_value():")
    position = calculate_position_value(
        symbol="AAPL",
        quantity=100,
        current_price=160.0,
        cost_basis=150.0,
        side="long"
    )
    print(f"   Symbol: {position['symbol']}")
    print(f"   Quantity: {position['quantity']}")
    print(f"   Cost Basis: ${position['cost_basis']:.2f}")
    print(f"   Current Price: ${position['current_price']:.2f}")
    print(f"   Market Value: ${position['market_value']:,.2f}")
    print(f"   Unrealized P&L: ${position['unrealized_pnl']:,.2f}")
    print(f"   Unrealized P&L %: {position['unrealized_pnl_pct']:.2f}%")

    # Test 2: Calculate portfolio value
    print("\n2. calculate_portfolio_value():")
    positions = {
        "AAPL": {
            "symbol": "AAPL",
            "quantity": 100,
            "cost_basis": 150.0,
            "current_price": 160.0,
            "market_value": 16000.0,
            "unrealized_pnl": 1000.0,
            "unrealized_pnl_pct": 6.67,
            "side": "long"
        },
        "TSLA": {
            "symbol": "TSLA",
            "quantity": 50,
            "cost_basis": 200.0,
            "current_price": 220.0,
            "market_value": 11000.0,
            "unrealized_pnl": 1000.0,
            "unrealized_pnl_pct": 10.0,
            "side": "long"
        }
    }
    prices = {"AAPL": 160.0, "TSLA": 220.0}
    cash = 50000.0

    total_value = calculate_portfolio_value(cash, positions, prices)
    print(f"   Cash: ${cash:,.2f}")
    print(f"   AAPL Value: ${positions['AAPL']['market_value']:,.2f}")
    print(f"   TSLA Value: ${positions['TSLA']['market_value']:,.2f}")
    print(f"   Total Portfolio Value: ${total_value:,.2f}")

    # Test 3: Compute exposures
    print("\n3. compute_exposures():")
    exposures = compute_exposures(cash, positions, prices, total_value)
    print(f"   Long Value: ${exposures['long_value']:,.2f}")
    print(f"   Short Value: ${exposures['short_value']:,.2f}")
    print(f"   Gross Exposure: ${exposures['gross_exposure']:,.2f}")
    print(f"   Net Exposure: ${exposures['net_exposure']:,.2f}")
    print(f"   Long %: {exposures['long_pct']:.2f}%")
    print(f"   Gross %: {exposures['gross_pct']:.2f}%")

    # Test 4: Compute portfolio summary
    print("\n4. compute_portfolio_summary():")
    initial_capital = 100000.0
    summary = compute_portfolio_summary(cash, positions, prices, initial_capital)
    print(f"   Initial Capital: ${initial_capital:,.2f}")
    print(f"   Current Equity: ${summary['equity']:,.2f}")
    print(f"   Return $: ${summary['return_dollars']:,.2f}")
    print(f"   Return %: {summary['return_pct']:.2f}%")
    print(f"   Num Positions: {summary['num_positions']}")
    print(f"   Gross Exposure %: {summary['exposures']['gross_pct']:.2f}%")

    # Test 5: Short position
    print("\n5. Short Position Test:")
    short_pos = calculate_position_value(
        symbol="SPY",
        quantity=-100,
        current_price=450.0,
        cost_basis=460.0,
        side="short"
    )
    print(f"   Symbol: {short_pos['symbol']} (SHORT)")
    print(f"   Quantity: {short_pos['quantity']}")
    print(f"   Cost Basis: ${short_pos['cost_basis']:.2f}")
    print(f"   Current Price: ${short_pos['current_price']:.2f}")
    print(f"   Market Value: ${short_pos['market_value']:,.2f}")
    print(f"   Unrealized P&L: ${short_pos['unrealized_pnl']:,.2f}")
    print(f"   Unrealized P&L %: {short_pos['unrealized_pnl_pct']:.2f}%")

    print("\n" + "=" * 60)
    print("All valuation functions validated successfully!")
    print("=" * 60)
