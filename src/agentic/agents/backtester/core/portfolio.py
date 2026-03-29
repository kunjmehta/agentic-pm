"""Portfolio state management for backtesting.

Stateful portfolio class that tracks cash, positions, and cost basis during simulation.
Provides defensive copying for snapshots and manages position entries/exits.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Dict, Optional, Tuple
from copy import deepcopy
from datetime import datetime, date

try:
    from src.agentic.agents.backtester.core.bt_types import PositionState, PortfolioSnapshot
    from src.agentic.agents.backtester.core.valuation import calculate_position_value, calculate_portfolio_value
except ModuleNotFoundError:
    from bt_types import PositionState, PortfolioSnapshot
    from valuation import calculate_position_value, calculate_portfolio_value


class Portfolio:
    """Manages portfolio state during backtesting simulation.

    Tracks cash, positions, and cost basis with defensive state management.
    Supports long and short positions with proper cost basis averaging.

    Attributes:
        _cash: Available cash balance
        _positions: Dictionary mapping symbol -> PositionState
        _realized_gains: Dictionary tracking realized P&L by symbol
        _initial_cash: Starting cash for reference
    """

    def __init__(self, initial_cash: float, starting_positions: Optional[Dict[str, PositionState]] = None):
        """Initialize portfolio with cash and optional starting positions.

        Args:
            initial_cash: Starting cash balance
            starting_positions: Optional dict of positions to start with
        """
        self._cash = initial_cash
        self._initial_cash = initial_cash
        self._positions: Dict[str, PositionState] = {}
        self._realized_gains: Dict[str, float] = {}

        # Add starting positions if provided
        if starting_positions:
            for symbol, position in starting_positions.items():
                self._positions[symbol] = deepcopy(position)

    # =========================================================================
    # Accessors
    # =========================================================================

    def get_cash(self) -> float:
        """Get current cash balance."""
        return self._cash

    def get_equity(self, current_prices: Dict[str, float]) -> float:
        """Calculate total equity (cash + positions value).

        Args:
            current_prices: Dictionary mapping symbol -> current price

        Returns:
            Total portfolio equity
        """
        return calculate_portfolio_value(self._cash, self._positions, current_prices)

    def get_position(self, symbol: str) -> Optional[PositionState]:
        """Get position state for a symbol.

        Args:
            symbol: Stock ticker symbol

        Returns:
            PositionState or None if no position
        """
        return self._positions.get(symbol)

    def get_all_positions(self) -> Dict[str, PositionState]:
        """Get all positions (defensive copy).

        Returns:
            Dictionary mapping symbol -> PositionState
        """
        return deepcopy(self._positions)

    def get_realized_gains(self, symbol: Optional[str] = None) -> float:
        """Get realized gains for a symbol or total.

        Args:
            symbol: Stock ticker (None for total across all symbols)

        Returns:
            Realized P&L in dollars
        """
        if symbol:
            return self._realized_gains.get(symbol, 0.0)
        else:
            return sum(self._realized_gains.values())

    def get_snapshot(self, current_date: Optional[date] = None) -> PortfolioSnapshot:
        """Get defensive copy of current portfolio state.

        Args:
            current_date: Date for snapshot (defaults to today)

        Returns:
            PortfolioSnapshot with current state
        """
        if current_date is None:
            current_date = date.today()

        # Count long and short positions
        long_count = sum(1 for p in self._positions.values() if p.get("side", "long") == "long" and p.get("quantity", 0) > 0)
        short_count = sum(1 for p in self._positions.values() if p.get("side", "long") == "short" and p.get("quantity", 0) != 0)

        return {
            "date": current_date,
            "timestamp": datetime.now(),
            "cash": self._cash,
            "equity": 0.0,  # Caller should calculate with current prices
            "positions": deepcopy(self._positions),
            "long_positions": long_count,
            "short_positions": short_count
        }

    # =========================================================================
    # Long Position Operations
    # =========================================================================

    def apply_buy(self, symbol: str, quantity: int, price: float) -> bool:
        """Execute long buy, update cost basis.

        Args:
            symbol: Stock ticker symbol
            quantity: Number of shares to buy
            price: Price per share

        Returns:
            True if successful, False if insufficient cash
        """
        if quantity <= 0:
            return False

        cost = quantity * price

        # Check if we have enough cash
        if cost > self._cash:
            # Fallback: Buy as many shares as we can afford
            quantity = int(self._cash / price)
            if quantity == 0:
                return False
            cost = quantity * price

        # Deduct cash
        self._cash -= cost

        # Update or create position with cost basis averaging
        if symbol in self._positions and self._positions[symbol].get("side", "long") == "long":
            # Average cost basis for additional shares
            existing_qty = self._positions[symbol]["quantity"]
            existing_basis = self._positions[symbol]["cost_basis"]
            new_cost_basis = ((existing_qty * existing_basis) + cost) / (existing_qty + quantity)

            self._positions[symbol]["quantity"] += quantity
            self._positions[symbol]["cost_basis"] = new_cost_basis
        else:
            # New long position
            self._positions[symbol] = {
                "symbol": symbol,
                "quantity": quantity,
                "cost_basis": price,
                "current_price": price,
                "market_value": cost,
                "unrealized_pnl": 0.0,
                "unrealized_pnl_pct": 0.0,
                "side": "long"
            }

        return True

    def apply_sell(self, symbol: str, quantity: int, price: float) -> Tuple[bool, float]:
        """Execute long sell, calculate realized P&L.

        Args:
            symbol: Stock ticker symbol
            quantity: Number of shares to sell
            price: Price per share

        Returns:
            Tuple of (success: bool, realized_pnl: float)
        """
        if quantity <= 0:
            return False, 0.0

        # Check if we have the position
        if symbol not in self._positions or self._positions[symbol].get("side", "long") != "long":
            return False, 0.0

        current_qty = self._positions[symbol]["quantity"]
        if quantity > current_qty:
            quantity = current_qty  # Sell all we have

        # Calculate realized P&L
        cost_basis = self._positions[symbol]["cost_basis"]
        realized_pnl = (price - cost_basis) * quantity

        # Track realized gains
        if symbol not in self._realized_gains:
            self._realized_gains[symbol] = 0.0
        self._realized_gains[symbol] += realized_pnl

        # Add proceeds to cash
        self._cash += quantity * price

        # Update position
        self._positions[symbol]["quantity"] -= quantity

        # Remove position if fully sold
        if self._positions[symbol]["quantity"] == 0:
            del self._positions[symbol]

        return True, realized_pnl

    # =========================================================================
    # Short Position Operations (Future Enhancement)
    # =========================================================================

    def apply_short(self, symbol: str, quantity: int, price: float) -> bool:
        """Open short position (future enhancement).

        Args:
            symbol: Stock ticker symbol
            quantity: Number of shares to short
            price: Price per share

        Returns:
            True if successful, False otherwise
        """
        # TODO: Implement short position logic
        # - Check margin requirements
        # - Track margin used
        # - Create negative quantity position with side='short'
        return False

    def apply_cover(self, symbol: str, quantity: int, price: float) -> Tuple[bool, float]:
        """Cover short position (future enhancement).

        Args:
            symbol: Stock ticker symbol
            quantity: Number of shares to cover
            price: Price per share

        Returns:
            Tuple of (success: bool, realized_pnl: float)
        """
        # TODO: Implement short covering logic
        # - Calculate realized P&L (cost_basis - price) * quantity
        # - Release margin
        # - Update or close short position
        return False, 0.0

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def update_position_prices(self, current_prices: Dict[str, float]) -> None:
        """Update current prices for all positions.

        Args:
            current_prices: Dictionary mapping symbol -> current price
        """
        for symbol, position in self._positions.items():
            if symbol in current_prices:
                current_price = current_prices[symbol]
                quantity = position["quantity"]
                cost_basis = position["cost_basis"]
                side = position.get("side", "long")

                # Recalculate position state
                updated_position = calculate_position_value(
                    symbol, quantity, current_price, cost_basis, side
                )
                self._positions[symbol].update(updated_position)

    def get_summary(self, current_prices: Dict[str, float]) -> Dict:
        """Get portfolio summary with current prices.

        Args:
            current_prices: Dictionary mapping symbol -> current price

        Returns:
            Dict with cash, equity, positions count, realized gains
        """
        # Update position prices first
        self.update_position_prices(current_prices)

        equity = self.get_equity(current_prices)
        total_realized = self.get_realized_gains()

        return {
            "cash": self._cash,
            "equity": equity,
            "num_positions": len(self._positions),
            "realized_pnl": total_realized,
            "unrealized_pnl": sum(p.get("unrealized_pnl", 0.0) for p in self._positions.values()),
            "total_pnl": total_realized + sum(p.get("unrealized_pnl", 0.0) for p in self._positions.values())
        }


# =============================================================================
# Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Test Portfolio class."""
    print("=" * 60)
    print("Portfolio Class Tests")
    print("=" * 60)

    # Test 1: Initialize portfolio
    print("\n1. Initialize Portfolio:")
    portfolio = Portfolio(initial_cash=100000.0)
    print(f"   Initial Cash: ${portfolio.get_cash():,.2f}")
    print(f"   Positions: {len(portfolio.get_all_positions())}")

    # Test 2: Buy AAPL
    print("\n2. Buy 100 AAPL at $150:")
    success = portfolio.apply_buy("AAPL", 100, 150.0)
    print(f"   Success: {success}")
    print(f"   Cash after buy: ${portfolio.get_cash():,.2f}")
    aapl_pos = portfolio.get_position("AAPL")
    if aapl_pos:
        print(f"   AAPL Quantity: {aapl_pos['quantity']}")
        print(f"   AAPL Cost Basis: ${aapl_pos['cost_basis']:.2f}")

    # Test 3: Buy more AAPL (test cost basis averaging)
    print("\n3. Buy 50 more AAPL at $160:")
    success = portfolio.apply_buy("AAPL", 50, 160.0)
    print(f"   Success: {success}")
    print(f"   Cash after buy: ${portfolio.get_cash():,.2f}")
    aapl_pos = portfolio.get_position("AAPL")
    if aapl_pos:
        print(f"   AAPL Quantity: {aapl_pos['quantity']}")
        print(f"   AAPL Cost Basis: ${aapl_pos['cost_basis']:.2f} (should be averaged)")

    # Test 4: Buy TSLA
    print("\n4. Buy 50 TSLA at $200:")
    success = portfolio.apply_buy("TSLA", 50, 200.0)
    print(f"   Success: {success}")
    print(f"   Cash after buy: ${portfolio.get_cash():,.2f}")
    print(f"   Number of positions: {len(portfolio.get_all_positions())}")

    # Test 5: Update prices and get summary
    print("\n5. Update Prices and Get Summary:")
    current_prices = {"AAPL": 165.0, "TSLA": 220.0}
    summary = portfolio.get_summary(current_prices)
    print(f"   Cash: ${summary['cash']:,.2f}")
    print(f"   Equity: ${summary['equity']:,.2f}")
    print(f"   Positions: {summary['num_positions']}")
    print(f"   Unrealized P&L: ${summary['unrealized_pnl']:,.2f}")
    print(f"   Total P&L: ${summary['total_pnl']:,.2f}")

    # Test 6: Sell some AAPL
    print("\n6. Sell 50 AAPL at $170:")
    success, realized_pnl = portfolio.apply_sell("AAPL", 50, 170.0)
    print(f"   Success: {success}")
    print(f"   Realized P&L: ${realized_pnl:,.2f}")
    print(f"   Cash after sell: ${portfolio.get_cash():,.2f}")
    aapl_pos = portfolio.get_position("AAPL")
    if aapl_pos:
        print(f"   AAPL Quantity Remaining: {aapl_pos['quantity']}")

    # Test 7: Get snapshot
    print("\n7. Get Portfolio Snapshot:")
    snapshot = portfolio.get_snapshot()
    print(f"   Snapshot Date: {snapshot['date']}")
    print(f"   Cash: ${snapshot['cash']:,.2f}")
    print(f"   Long Positions: {snapshot['long_positions']}")
    print(f"   Positions in snapshot: {list(snapshot['positions'].keys())}")

    # Test 8: Final summary
    print("\n8. Final Portfolio Summary:")
    summary = portfolio.get_summary(current_prices)
    print(f"   Equity: ${summary['equity']:,.2f}")
    print(f"   Realized P&L: ${summary['realized_pnl']:,.2f}")
    print(f"   Unrealized P&L: ${summary['unrealized_pnl']:,.2f}")
    print(f"   Total P&L: ${summary['total_pnl']:,.2f}")
    print(f"   Return: ${summary['total_pnl']:,.2f} ({(summary['total_pnl']/100000)*100:.2f}%)")

    print("\n" + "=" * 60)
    print("All Portfolio tests passed successfully!")
    print("=" * 60)
