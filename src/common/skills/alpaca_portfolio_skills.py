"""Alpaca Portfolio API integration functions.

This module provides functions to interact with Alpaca's Trading API
for portfolio management, account information, positions, and orders.

Reference: https://docs.alpaca.markets/reference/
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime
from typing import Optional, List, Dict
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import OrderSide, QueryOrderStatus
from src.common.utils import secrets, get_logger

# Initialize logger
logger = get_logger(__name__)

# Initialize Alpaca client with credentials from secrets
API_KEY = secrets.get("alpaca.api_key")
SECRET_KEY = secrets.get("alpaca.secret_key")

# Initialize trading client
trading_client = TradingClient(API_KEY, SECRET_KEY)
logger.info("Alpaca trading client initialized")


# =============================================================================
# Account Information
# =============================================================================

def fetch_account_info() -> Dict:
    """Fetch current account information from Alpaca.

    Returns account equity, cash, buying power, and other account metrics.

    Reference: https://docs.alpaca.markets/reference/getaccount-1

    Returns:
        Dict with account information including:
        - equity: Total account value
        - cash: Available cash
        - buying_power: Margin buying power
        - portfolio_value: Current portfolio value
        - account_status: Account status (ACTIVE, etc.)

    Raises:
        Exception: If API request fails
    """
    logger.info("Fetching account information from Alpaca")

    try:
        account = trading_client.get_account()

        account_data = {
            "id": str(account.id),
            "account_number": str(account.account_number),
            "status": account.status.value,
            "currency": account.currency,
            "buying_power": float(account.buying_power),
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "pattern_day_trader": account.pattern_day_trader,
            "trading_blocked": account.trading_blocked,
            "transfers_blocked": account.transfers_blocked,
            "account_blocked": account.account_blocked,
            "created_at": str(account.created_at),
            "shorting_enabled": account.shorting_enabled,
            "equity": float(account.equity),
            "last_equity": float(account.last_equity),
            "multiplier": float(account.multiplier),
            "initial_margin": float(account.initial_margin),
            "maintenance_margin": float(account.maintenance_margin),
            "last_maintenance_margin": float(account.last_maintenance_margin),
            "daytrade_count": account.daytrade_count,
        }

        logger.info(f"Account info fetched: equity=${account_data['equity']:.2f}, "
                   f"cash=${account_data['cash']:.2f}")

        return account_data

    except Exception as e:
        error_msg = f"Failed to fetch account info: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg)


# =============================================================================
# Positions
# =============================================================================

def fetch_positions() -> List[Dict]:
    """Fetch all current positions from Alpaca.

    Returns detailed position information including unrealized P&L,
    cost basis, and current market value for each position.

    Reference: https://docs.alpaca.markets/reference/getallopenpositions-1

    Returns:
        List of dicts, each containing:
        - symbol: Stock ticker
        - qty: Quantity (positive for long, negative for short)
        - side: 'long' or 'short'
        - market_value: Current market value
        - cost_basis: Total cost basis
        - unrealized_pl: Unrealized profit/loss
        - unrealized_plpc: Unrealized P&L percentage
        - current_price: Current market price
        - avg_entry_price: Average entry price

    Raises:
        Exception: If API request fails
    """
    logger.info("Fetching all positions from Alpaca")

    try:
        positions = trading_client.get_all_positions()

        positions_list = []
        for pos in positions:
            position_data = {
                "asset_id": str(pos.asset_id),
                "symbol": pos.symbol,
                "exchange": pos.exchange.value,
                "asset_class": pos.asset_class.value,
                "avg_entry_price": float(pos.avg_entry_price),
                "qty": float(pos.qty),
                "qty_available": float(pos.qty_available),
                "side": "long" if float(pos.qty) > 0 else "short",
                "market_value": float(pos.market_value),
                "cost_basis": float(pos.cost_basis),
                "unrealized_pl": float(pos.unrealized_pl),
                "unrealized_plpc": float(pos.unrealized_plpc),
                "unrealized_intraday_pl": float(pos.unrealized_intraday_pl),
                "unrealized_intraday_plpc": float(pos.unrealized_intraday_plpc),
                "current_price": float(pos.current_price),
                "lastday_price": float(pos.lastday_price),
                "change_today": float(pos.change_today),
            }
            positions_list.append(position_data)

        logger.info(f"Fetched {len(positions_list)} positions")

        return positions_list

    except Exception as e:
        error_msg = f"Failed to fetch positions: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg)


def fetch_position(symbol: str) -> Dict:
    """Fetch a specific position by symbol.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")

    Returns:
        Dict with position details (same structure as fetch_positions items)

    Raises:
        Exception: If position not found or API request fails
    """
    logger.info(f"Fetching position for {symbol}")

    try:
        pos = trading_client.get_open_position(symbol)

        position_data = {
            "asset_id": str(pos.asset_id),
            "symbol": pos.symbol,
            "exchange": pos.exchange.value,
            "asset_class": pos.asset_class.value,
            "avg_entry_price": float(pos.avg_entry_price),
            "qty": float(pos.qty),
            "qty_available": float(pos.qty_available),
            "side": "long" if float(pos.qty) > 0 else "short",
            "market_value": float(pos.market_value),
            "cost_basis": float(pos.cost_basis),
            "unrealized_pl": float(pos.unrealized_pl),
            "unrealized_plpc": float(pos.unrealized_plpc),
            "current_price": float(pos.current_price),
        }

        logger.info(f"Position for {symbol}: qty={position_data['qty']}, "
                   f"unrealized_pl=${position_data['unrealized_pl']:.2f}")

        return position_data

    except Exception as e:
        error_msg = f"Failed to fetch position for {symbol}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg)


# =============================================================================
# Orders
# =============================================================================

def fetch_orders(
    status: Optional[str] = None,
    limit: int = 100,
    after: Optional[datetime] = None,
    until: Optional[datetime] = None
) -> List[Dict]:
    """Fetch orders from Alpaca with optional filters.

    Reference: https://docs.alpaca.markets/reference/getallorders-1

    Args:
        status: Filter by status - 'open', 'closed', 'all' (default: 'all')
        limit: Maximum number of orders to return (default: 100)
        after: Filter orders after this timestamp
        until: Filter orders before this timestamp

    Returns:
        List of dicts, each containing order details:
        - id: Order ID
        - symbol: Stock ticker
        - qty: Order quantity
        - side: 'buy' or 'sell'
        - type: Order type (market, limit, etc.)
        - status: Order status
        - filled_qty: Filled quantity
        - filled_avg_price: Average fill price

    Raises:
        Exception: If API request fails
    """
    logger.info(f"Fetching orders (status={status}, limit={limit})")

    try:
        # Map status string to QueryOrderStatus enum
        status_map = {
            "open": QueryOrderStatus.OPEN,
            "closed": QueryOrderStatus.CLOSED,
            "all": QueryOrderStatus.ALL,
        }

        query_status = status_map.get(status, QueryOrderStatus.ALL)

        # Build request
        request = GetOrdersRequest(
            status=query_status,
            limit=limit,
            after=after,
            until=until
        )

        orders = trading_client.get_orders(filter=request)

        orders_list = []
        for order in orders:
            order_data = {
                "id": str(order.id),
                "client_order_id": str(order.client_order_id),
                "created_at": str(order.created_at),
                "updated_at": str(order.updated_at),
                "submitted_at": str(order.submitted_at),
                "filled_at": str(order.filled_at) if order.filled_at else None,
                "expired_at": str(order.expired_at) if order.expired_at else None,
                "canceled_at": str(order.canceled_at) if order.canceled_at else None,
                "asset_id": order.asset_id,
                "symbol": order.symbol,
                "asset_class": order.asset_class.value,
                "qty": float(order.qty) if order.qty else None,
                "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
                "type": order.type.value,
                "side": order.side.value,
                "time_in_force": order.time_in_force.value,
                "limit_price": float(order.limit_price) if order.limit_price else None,
                "stop_price": float(order.stop_price) if order.stop_price else None,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                "status": order.status.value,
                "extended_hours": order.extended_hours,
                "legs": order.legs,
            }
            orders_list.append(order_data)

        logger.info(f"Fetched {len(orders_list)} orders")

        return orders_list

    except Exception as e:
        error_msg = f"Failed to fetch orders: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg)


# =============================================================================
# Portfolio History
# =============================================================================

def fetch_portfolio_history(
    period: str = "1M",
    timeframe: str = "1D",
    extended_hours: bool = False
) -> Dict:
    """Fetch portfolio performance history from Alpaca.

    Reference: https://docs.alpaca.markets/reference/getportfoliohistory-1

    Args:
        period: Time period - "1D", "1W", "1M", "3M", "1A", "all"
        timeframe: Aggregation timeframe - "1Min", "5Min", "15Min", "1H", "1D"
        extended_hours: Include extended hours data

    Returns:
        Dict with portfolio history:
        - timestamp: List of timestamps
        - equity: List of equity values
        - profit_loss: List of profit/loss values
        - profit_loss_pct: List of P&L percentages
        - base_value: Starting portfolio value
        - timeframe: Aggregation timeframe used

    Raises:
        Exception: If API request fails
    """
    logger.info(f"Fetching portfolio history (period={period}, timeframe={timeframe})")

    try:
        from alpaca.trading.requests import GetPortfolioHistoryRequest

        request = GetPortfolioHistoryRequest(
            period=period,
            timeframe=timeframe,
            extended_hours=extended_hours
        )

        history = trading_client.get_portfolio_history(request)

        history_data = {
            "timestamp": [str(ts) for ts in history.timestamp],
            "equity": [float(e) for e in history.equity],
            "profit_loss": [float(pl) for pl in history.profit_loss],
            "profit_loss_pct": [float(plp) for plp in history.profit_loss_pct],
            "base_value": float(history.base_value),
            "timeframe": history.timeframe,
        }

        logger.info(f"Portfolio history fetched: {len(history_data['timestamp'])} data points")

        return history_data

    except Exception as e:
        error_msg = f"Failed to fetch portfolio history: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg)


# =============================================================================
# Watchlists
# =============================================================================

def fetch_watchlists() -> List[Dict]:
    """Fetch all watchlists from Alpaca.

    Reference: https://docs.alpaca.markets/reference/getwatchlists-1

    Returns:
        List of watchlist dictionaries, each containing:
        - id: Watchlist UUID
        - name: Watchlist name
        - account_id: Account UUID
        - created_at: Creation timestamp
        - updated_at: Last update timestamp
        - assets: List of asset dicts with symbol info

    Raises:
        Exception: If API request fails
    """
    logger.info("Fetching watchlists from Alpaca")

    try:
        watchlists = trading_client.get_watchlists()

        watchlists_data = []
        for wl in watchlists:
            watchlist_dict = {
                "id": str(wl.id),
                "name": wl.name,
                "account_id": str(wl.account_id),
                "created_at": str(wl.created_at) if hasattr(wl, 'created_at') else None,
                "updated_at": str(wl.updated_at) if hasattr(wl, 'updated_at') else None,
                "assets": []
            }

            # Get watchlist details to fetch assets
            try:
                detailed_wl = trading_client.get_watchlist_by_id(wl.id)
                if hasattr(detailed_wl, 'assets'):
                    watchlist_dict["assets"] = [
                        {
                            "symbol": asset.symbol,
                            "class": asset.asset_class if hasattr(asset, 'asset_class') else None,
                            "exchange": asset.exchange if hasattr(asset, 'exchange') else None
                        }
                        for asset in detailed_wl.assets
                    ]
            except Exception as e:
                logger.warning(f"Could not fetch assets for watchlist {wl.name}: {e}")

            watchlists_data.append(watchlist_dict)

        logger.info(f"Fetched {len(watchlists_data)} watchlists")

        return watchlists_data

    except Exception as e:
        error_msg = f"Failed to fetch watchlists: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg)


def get_all_watchlist_symbols() -> List[str]:
    """Get all unique symbols across all watchlists.

    Returns:
        List of unique stock symbols from all watchlists

    Raises:
        Exception: If API request fails
    """
    try:
        watchlists = fetch_watchlists()
        symbols = set()

        for wl in watchlists:
            for asset in wl.get("assets", []):
                if asset.get("symbol"):
                    symbols.add(asset["symbol"])

        symbols_list = sorted(list(symbols))
        logger.info(f"Found {len(symbols_list)} unique symbols across all watchlists")

        return symbols_list

    except Exception as e:
        error_msg = f"Failed to get watchlist symbols: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg)


# =============================================================================
# Main Block for Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Functional tests for Alpaca portfolio skills."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Test Alpaca portfolio skills")
    parser.add_argument("--test", choices=["account", "positions", "orders", "history", "all"],
                        default="all", help="Which test to run")
    parser.add_argument("--symbol", default="AAPL", help="Symbol for position test")

    args = parser.parse_args()

    print("=" * 60)
    print("Alpaca Portfolio Skills Functional Tests")
    print("=" * 60)

    if args.test in ["account", "all"]:
        print("\n[TEST 1] fetch_account_info()")
        print("-" * 60)
        try:
            account = fetch_account_info()
            print(json.dumps(account, indent=2))
        except Exception as e:
            print(f"[FAIL] {e}")

    if args.test in ["positions", "all"]:
        print("\n[TEST 2] fetch_positions()")
        print("-" * 60)
        try:
            positions = fetch_positions()
            print(json.dumps(positions, indent=2))
        except Exception as e:
            print(f"[FAIL] {e}")

        # Test single position if symbol specified
        if args.symbol:
            print(f"\n[TEST 2b] fetch_position('{args.symbol}')")
            print("-" * 60)
            try:
                position = fetch_position(args.symbol)
                print(json.dumps(position, indent=2))
            except Exception as e:
                print(f"[FAIL] {e}")

    if args.test in ["orders", "all"]:
        print("\n[TEST 3] fetch_orders()")
        print("-" * 60)
        try:
            orders = fetch_orders(status="all", limit=10)
            print(json.dumps(orders, indent=2))
        except Exception as e:
            print(f"[FAIL] {e}")

    if args.test in ["history", "all"]:
        print("\n[TEST 4] fetch_portfolio_history()")
        print("-" * 60)
        try:
            history = fetch_portfolio_history(period="1M", timeframe="1D")
            print(json.dumps(history, indent=2))
        except Exception as e:
            print(f"[FAIL] {e}")

    print("\n" + "=" * 60)
    print("Tests Complete")
    print("=" * 60)
