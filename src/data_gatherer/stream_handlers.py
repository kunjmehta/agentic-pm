"""Default handlers for Alpaca WebSocket stream data.

Provides ready-to-use callback functions for processing trades, bars, and status updates.
"""

import json
from datetime import datetime
from typing import Dict


def print_trade(trade: Dict) -> None:
    """Print trade data in a readable format.

    Args:
        trade: Trade message dict with keys: T, S, i, x, p, s, c, z, t
    """
    symbol = trade.get("S")
    price = trade.get("p")
    size = trade.get("s")
    exchange = trade.get("x")
    timestamp = trade.get("t")
    conditions = trade.get("c", [])

    print(f"[TRADE] {symbol} @ ${price:.2f} x {size} on {exchange} | {timestamp} | Conditions: {conditions}")


def print_daily_bar(bar: Dict) -> None:
    """Print daily bar data in a readable format.

    Args:
        bar: Bar message dict with keys: T, S, o, h, l, c, v, vw, n, t
    """
    symbol = bar.get("S")
    open_price = bar.get("o")
    high = bar.get("h")
    low = bar.get("l")
    close = bar.get("c")
    volume = bar.get("v")
    vwap = bar.get("vw")
    trade_count = bar.get("n")
    timestamp = bar.get("t")

    print(f"[BAR] {symbol} | O: ${open_price:.2f} H: ${high:.2f} L: ${low:.2f} C: ${close:.2f} | "
          f"Vol: {volume:,} VWAP: ${vwap:.2f} Trades: {trade_count} | {timestamp}")


def print_status(status: Dict) -> None:
    """Print trade status data in a readable format.

    Args:
        status: Status message dict with keys: T, S, sc, sm, rc, rm, z, t
    """
    symbol = status.get("S")
    status_code = status.get("sc")
    status_msg = status.get("sm")
    reason_code = status.get("rc")
    reason_msg = status.get("rm")
    timestamp = status.get("t")

    print(f"[STATUS] {symbol} | {status_msg} ({status_code}) - {reason_msg} ({reason_code}) | {timestamp}")


def log_trade(trade: Dict) -> None:
    """Log trade data as JSON (useful for data collection).

    Args:
        trade: Trade message dict
    """
    print(json.dumps({
        "type": "trade",
        "timestamp": datetime.utcnow().isoformat(),
        "data": trade
    }))


def log_daily_bar(bar: Dict) -> None:
    """Log daily bar data as JSON (useful for data collection).

    Args:
        bar: Bar message dict
    """
    print(json.dumps({
        "type": "daily_bar",
        "timestamp": datetime.utcnow().isoformat(),
        "data": bar
    }))


def log_status(status: Dict) -> None:
    """Log status data as JSON (useful for data collection).

    Args:
        status: Status message dict
    """
    print(json.dumps({
        "type": "status",
        "timestamp": datetime.utcnow().isoformat(),
        "data": status
    }))


# Example: Custom handler that accumulates trades
class TradeAccumulator:
    """Example handler class that accumulates trade data."""

    def __init__(self):
        """Initialize the accumulator."""
        self.trades = []
        self.total_volume = 0
        self.trade_count = 0

    def handle_trade(self, trade: Dict) -> None:
        """Accumulate trade data.

        Args:
            trade: Trade message dict
        """
        self.trades.append(trade)
        self.total_volume += trade.get("s", 0)
        self.trade_count += 1

        # Print summary every 10 trades
        if self.trade_count % 10 == 0:
            avg_price = sum(t.get("p", 0) for t in self.trades[-10:]) / 10
            print(f"[ACCUMULATOR] Last 10 trades | Avg Price: ${avg_price:.2f} | Total Volume: {self.total_volume:,}")

    def get_summary(self) -> Dict:
        """Get summary statistics.

        Returns:
            Dict with trade statistics
        """
        if not self.trades:
            return {}

        prices = [t.get("p", 0) for t in self.trades]
        return {
            "trade_count": self.trade_count,
            "total_volume": self.total_volume,
            "avg_price": sum(prices) / len(prices) if prices else 0,
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
        }


if __name__ == "__main__":
    """Demo the handlers with sample data."""
    print("=" * 60)
    print("Stream Handlers Demo")
    print("=" * 60)

    # Sample trade
    sample_trade = {
        "T": "t",
        "S": "AAPL",
        "i": 12345,
        "x": "NASDAQ",
        "p": 182.52,
        "s": 100,
        "c": ["@", "F", "T"],
        "z": "C",
        "t": "2024-02-17T14:30:00.123456Z"
    }

    # Sample bar
    sample_bar = {
        "T": "d",
        "S": "AAPL",
        "o": 181.50,
        "h": 183.00,
        "l": 180.75,
        "c": 182.52,
        "v": 5000000,
        "vw": 182.10,
        "n": 25000,
        "t": "2024-02-17"
    }

    # Sample status
    sample_status = {
        "T": "s",
        "S": "AAPL",
        "sc": "H",
        "sm": "Halted",
        "rc": "T1",
        "rm": "News Pending",
        "z": "C",
        "t": "2024-02-17T14:30:00Z"
    }

    print("\n1. Print Handlers:")
    print_trade(sample_trade)
    print_daily_bar(sample_bar)
    print_status(sample_status)

    print("\n2. JSON Log Handlers:")
    log_trade(sample_trade)
    log_daily_bar(sample_bar)
    log_status(sample_status)

    print("\n3. Trade Accumulator:")
    accumulator = TradeAccumulator()
    for i in range(15):
        sample_trade["i"] = i
        sample_trade["p"] = 182.00 + (i * 0.1)
        sample_trade["s"] = 100 + (i * 10)
        accumulator.handle_trade(sample_trade)

    print(f"\nFinal Summary: {accumulator.get_summary()}")

    print("\n" + "=" * 60)
