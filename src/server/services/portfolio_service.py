"""Portfolio snapshot retrieval — no FastAPI or WebSocket dependency."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PortfolioSnapshot:
    """Current account + positions snapshot.

    Attributes:
        equity: Total equity value in USD.
        cash: Cash balance in USD.
        buying_power: Available buying power in USD.
        unrealized_pl: Sum of unrealized P&L across all open positions.
        positions: List of position dicts (symbol, qty, market_value, etc.).
        timestamp: ISO-8601 UTC timestamp of when the snapshot was taken.
    """

    equity: float
    cash: float
    buying_power: float
    unrealized_pl: float
    positions: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


async def get_portfolio_snapshot() -> PortfolioSnapshot:
    """Fetch current account + positions from Alpaca and return a structured snapshot.

    Returns:
        PortfolioSnapshot with current equity, cash, buying_power, unrealized_pl,
        and formatted positions list.
    """
    from src.common.external.alpaca_portfolio import fetch_account_info, fetch_positions

    account = await asyncio.to_thread(fetch_account_info)
    positions = await asyncio.to_thread(fetch_positions)

    total_unrealized_pl = sum(float(p.get("unrealized_pl", 0)) for p in positions)

    formatted = [
        {
            "symbol": p.get("symbol"),
            "qty": p.get("qty"),
            "market_value": p.get("market_value"),
            "unrealized_pl": p.get("unrealized_pl"),
            "avg_entry_price": p.get("avg_entry_price"),
            "current_price": p.get("current_price"),
            "side": p.get("side"),
        }
        for p in positions
    ]

    return PortfolioSnapshot(
        equity=float(account.get("equity", 0)),
        cash=float(account.get("cash", 0)),
        buying_power=float(account.get("buying_power", 0)),
        unrealized_pl=total_unrealized_pl,
        positions=formatted,
    )


if __name__ == "__main__":
    """Smoke test: verify module imports and dataclass construction."""
    print("=" * 60)
    print("services/portfolio_service.py smoke test")
    print("=" * 60)

    # Verify dataclass construction with explicit values
    snap = PortfolioSnapshot(
        equity=100_000.0,
        cash=50_000.0,
        buying_power=80_000.0,
        unrealized_pl=1_234.56,
        positions=[{"symbol": "AAPL", "qty": 10}],
    )
    assert snap.equity == 100_000.0
    assert snap.cash == 50_000.0
    assert snap.buying_power == 80_000.0
    assert snap.unrealized_pl == 1_234.56
    assert len(snap.positions) == 1
    assert snap.timestamp  # default factory populated
    print(f"  [OK]  PortfolioSnapshot: equity={snap.equity}, positions={len(snap.positions)}")

    # Verify function is importable and callable
    import asyncio
    assert callable(get_portfolio_snapshot)
    print("  [OK]  get_portfolio_snapshot is callable")

    print("\n[ALL OK] services/portfolio_service.py smoke test passed")
    print("=" * 60)
