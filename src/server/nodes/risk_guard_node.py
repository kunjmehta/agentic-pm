"""Risk Guard Node - Enforce hard risk limits before order execution.

Runs between pm_decision_node and order_executor_node to validate orders against
position sizing limits, sector concentration, and daily loss thresholds.

This node acts as a circuit breaker - if ANY risk limit is violated, the entire
order queue is cleared and an error is set in state, preventing execution.

Risk Limits Enforced:
    1. Max single position size: 5% of equity per symbol
    2. Max sector concentration: 20% of equity per sector
    3. Daily loss limit: -2% max unrealized P&L from market open
    4. Max total leverage: 1.0 (no margin, cash-only)
    5. Cash reserve minimum: 5% of equity must remain liquid

State Flow:
    Input: order_task_queue populated by pm_decision_node
    Output: Same queue (passed through) OR empty queue + error if violations detected
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger
from src.server.skills.portfolio.skills import get_portfolio_status_core

logger = get_logger(__name__)

# ── Risk Limits Configuration ─────────────────────────────────────────────────

MAX_SINGLE_POSITION_PCT = 0.05  # 5% of equity per symbol
MAX_SECTOR_CONCENTRATION_PCT = 0.20  # 20% of equity per sector
MAX_DAILY_LOSS_PCT = -0.02  # -2% max daily loss
MAX_LEVERAGE = 1.0  # No margin, cash only
MIN_CASH_RESERVE_PCT = 0.05  # 5% cash reserve minimum

# Sector mapping (simplified - in production, fetch from reference data)
SECTOR_MAP = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "GOOGL": "Technology",
    "AMZN": "Consumer Cyclical",
    "TSLA": "Consumer Cyclical",
    "JPM": "Financial Services",
    "BAC": "Financial Services",
    "XOM": "Energy",
    "CVX": "Energy",
    "JNJ": "Healthcare",
    "UNH": "Healthcare",
    "SPY": "ETF",
    "QQQ": "ETF",
}


def _get_sector(symbol: str) -> str:
    """Get sector for a symbol (fallback to 'Unknown' if not mapped)."""
    return SECTOR_MAP.get(symbol.upper(), "Unknown")


def _calculate_sector_exposure(
    current_positions: Dict[str, Dict],
    pending_orders: List[Dict],
    equity: float
) -> Dict[str, float]:
    """Calculate total sector exposure including pending orders.

    Args:
        current_positions: Dict of {symbol: {qty, market_value, ...}}
        pending_orders: List of order dicts with {symbol, side, qty, limit_price}
        equity: Total account equity

    Returns:
        Dict of {sector: exposure_pct} where exposure_pct is fraction of equity.
    """
    sector_exposure: Dict[str, float] = {}

    # Add current positions
    for symbol, pos in current_positions.items():
        sector = _get_sector(symbol)
        market_value = abs(float(pos.get("market_value", 0)))
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + market_value

    # Add pending orders
    for order in pending_orders:
        symbol = order.get("symbol", "")
        side = order.get("side", "buy")
        qty = abs(int(order.get("qty", 0)))
        price = float(order.get("limit_price", 0))
        notional = qty * price

        sector = _get_sector(symbol)
        if side.lower() == "buy":
            sector_exposure[sector] = sector_exposure.get(sector, 0.0) + notional
        else:
            # Selling reduces exposure
            sector_exposure[sector] = sector_exposure.get(sector, 0.0) - notional

    # Convert to percentages
    if equity > 0:
        return {sector: (value / equity) for sector, value in sector_exposure.items()}
    return {}


def risk_guard_node(state: dict) -> dict:
    """Validate orders against risk limits before execution.

    Args:
        state: Current GraphState dict with order_task_queue populated.

    Returns:
        Partial state update. If violations found:
            - error: Description of violations
            - order_task_queue: []  (cleared)
        Otherwise:
            - Passthrough (no modifications)
    """
    # Skip if no orders to execute
    if not state.get("_execute_orders"):
        logger.info("[risk_guard] no orders flagged for execution — skipping")
        return {}

    order_queue = state.get("order_task_queue") or []
    if not order_queue:
        logger.info("[risk_guard] order queue empty — skipping")
        return {}

    logger.info(f"[risk_guard] validating {len(order_queue)} orders against risk limits...")

    violations: List[str] = []

    # ── Get current portfolio state ────────────────────────────────────────────
    try:
        portfolio = get_portfolio_status_core()
        equity = float(portfolio.get("equity", 0))
        cash = float(portfolio.get("cash", 0))
        positions_dict = portfolio.get("positions", {})
        unrealized_pl = float(portfolio.get("unrealized_pl", 0))
        unrealized_pl_pct = float(portfolio.get("unrealized_plpc", 0))

        if equity <= 0:
            violations.append("Portfolio equity is zero or negative — cannot execute orders")
            logger.error(f"[risk_guard] VIOLATION: equity={equity}")
            return {
                "error": f"Risk Guard violations: {'; '.join(violations)}",
                "order_task_queue": [],
                "_execute_orders": False,
            }

    except Exception as exc:
        logger.error(f"[risk_guard] failed to fetch portfolio: {exc}", exc_info=True)
        return {
            "error": f"Risk Guard: Cannot validate orders (portfolio fetch failed: {exc})",
            "order_task_queue": [],
            "_execute_orders": False,
        }

    # ── Extract order details from queue ───────────────────────────────────────
    pending_orders = []
    for task in order_queue:
        params = task.get("params", {})
        symbol = params.get("symbol", "")
        side = params.get("side", "buy")
        qty = params.get("qty", 0)
        limit_price = params.get("limit_price", 0)

        if not symbol or not qty or not limit_price:
            logger.warning(f"[risk_guard] skipping incomplete order: {task}")
            continue

        pending_orders.append({
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "limit_price": limit_price,
            "task_id": task.get("task_id"),
        })

    logger.info(f"[risk_guard] extracted {len(pending_orders)} valid orders from queue")

    # ── Risk Check 1: Daily Loss Limit ─────────────────────────────────────────
    if unrealized_pl_pct < MAX_DAILY_LOSS_PCT:
        violations.append(
            f"Daily loss limit reached: {unrealized_pl_pct:.2%} "
            f"(limit: {MAX_DAILY_LOSS_PCT:.2%})"
        )
        logger.warning(f"[risk_guard] VIOLATION: daily loss {unrealized_pl_pct:.2%}")

    # ── Risk Check 2: Single Position Size Limit ───────────────────────────────
    for order in pending_orders:
        symbol = order["symbol"]
        notional = abs(order["qty"]) * order["limit_price"]
        position_pct = notional / equity

        if position_pct > MAX_SINGLE_POSITION_PCT:
            violations.append(
                f"{symbol}: Position size {position_pct:.2%} exceeds "
                f"{MAX_SINGLE_POSITION_PCT:.2%} limit"
            )
            logger.warning(
                f"[risk_guard] VIOLATION: {symbol} position size "
                f"{position_pct:.2%} > {MAX_SINGLE_POSITION_PCT:.2%}"
            )

    # ── Risk Check 3: Sector Concentration Limit ───────────────────────────────
    sector_exposure = _calculate_sector_exposure(positions_dict, pending_orders, equity)
    for sector, exposure_pct in sector_exposure.items():
        if exposure_pct > MAX_SECTOR_CONCENTRATION_PCT:
            violations.append(
                f"Sector '{sector}': Concentration {exposure_pct:.2%} exceeds "
                f"{MAX_SECTOR_CONCENTRATION_PCT:.2%} limit"
            )
            logger.warning(
                f"[risk_guard] VIOLATION: sector {sector} exposure "
                f"{exposure_pct:.2%} > {MAX_SECTOR_CONCENTRATION_PCT:.2%}"
            )

    # ── Risk Check 4: Cash Reserve Minimum ──────────────────────────────────────
    total_order_cost = sum(
        order["qty"] * order["limit_price"]
        for order in pending_orders
        if order["side"].lower() == "buy"
    )
    remaining_cash = cash - total_order_cost
    cash_reserve_pct = remaining_cash / equity if equity > 0 else 0.0

    if cash_reserve_pct < MIN_CASH_RESERVE_PCT:
        violations.append(
            f"Cash reserve {cash_reserve_pct:.2%} below minimum "
            f"{MIN_CASH_RESERVE_PCT:.2%} (${remaining_cash:,.2f} remaining)"
        )
        logger.warning(
            f"[risk_guard] VIOLATION: cash reserve {cash_reserve_pct:.2%} "
            f"< {MIN_CASH_RESERVE_PCT:.2%}"
        )

    # ── Risk Check 5: Leverage Limit ───────────────────────────────────────────
    total_position_value = sum(
        abs(float(pos.get("market_value", 0)))
        for pos in positions_dict.values()
    ) + total_order_cost
    leverage = total_position_value / equity if equity > 0 else 0.0

    if leverage > MAX_LEVERAGE:
        violations.append(
            f"Leverage {leverage:.2f}x exceeds maximum {MAX_LEVERAGE:.2f}x "
            f"(cash-only account)"
        )
        logger.warning(
            f"[risk_guard] VIOLATION: leverage {leverage:.2f}x > {MAX_LEVERAGE:.2f}x"
        )

    # ── Final Decision ──────────────────────────────────────────────────────────
    if violations:
        violation_summary = "; ".join(violations)
        logger.error(
            f"[risk_guard] BLOCKED {len(order_queue)} orders due to "
            f"{len(violations)} violations: {violation_summary}"
        )
        return {
            "error": f"Risk Guard violations: {violation_summary}",
            "order_task_queue": [],
            "_execute_orders": False,
        }

    logger.info(
        f"[risk_guard] ✓ ALL CHECKS PASSED — {len(order_queue)} orders approved "
        f"(equity=${equity:,.2f}, cash=${cash:,.2f}, sectors={len(sector_exposure)})"
    )
    return {}  # Passthrough - no modifications


if __name__ == "__main__":
    """Functional test with mock portfolio state."""
    print("=" * 60)
    print("Risk Guard Node Functional Test")
    print("=" * 60)

    # Test 1: Orders within limits (should pass)
    print("\n[1/3] Testing orders within limits...")
    state_ok = {
        "_execute_orders": True,
        "order_task_queue": [
            {
                "task_id": "ord_001",
                "function_name": "execute_order",
                "params": {
                    "symbol": "AAPL",
                    "side": "buy",
                    "qty": 10,
                    "limit_price": 150.0,
                },
            }
        ],
    }
    result_ok = risk_guard_node(state_ok)
    if result_ok.get("error"):
        print(f"[UNEXPECTED] Orders blocked: {result_ok['error']}")
    else:
        print("[OK] Orders approved (within risk limits)")

    # Test 2: Position size too large (should block)
    print("\n[2/3] Testing oversized position...")
    state_oversize = {
        "_execute_orders": True,
        "order_task_queue": [
            {
                "task_id": "ord_002",
                "function_name": "execute_order",
                "params": {
                    "symbol": "TSLA",
                    "side": "buy",
                    "qty": 100,
                    "limit_price": 250.0,  # $25k order on $100k equity = 25% > 5% limit
                },
            }
        ],
    }
    result_oversize = risk_guard_node(state_oversize)
    if result_oversize.get("error"):
        print(f"[OK] Orders blocked as expected: {result_oversize['error'][:80]}...")
    else:
        print("[UNEXPECTED] Orders approved (should have been blocked)")

    # Test 3: No orders to execute (should skip)
    print("\n[3/3] Testing empty order queue...")
    state_empty = {
        "_execute_orders": False,
        "order_task_queue": [],
    }
    result_empty = risk_guard_node(state_empty)
    if not result_empty:
        print("[OK] Skipped validation (no orders)")
    else:
        print(f"[UNEXPECTED] Returned state update: {result_empty}")

    print("\n" + "=" * 60)
    print("Risk Guard tests complete")
    print("=" * 60)
