"""
Portfolio Manager Tools (Initial - Lightweight)
Module 2: Interface-first implementation with direct API calls

This module will be refactored in Module 5 to use proper Skills + DAO layers.
Current implementation: Direct Alpaca API calls with caching and graceful degradation.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
from langchain_core.tools import tool

from src.utils import get_logger, secrets, config

logger = get_logger(__name__)

# =============================================================================
# Caching Layer (Improvement #4)
# =============================================================================

_cache: Dict[str, str] = {}
_cache_ttl: Dict[str, datetime] = {}
CACHE_TTL_MINUTES = 5


def _get_cached(key: str) -> Optional[str]:
    """Get cached value if still valid."""
    now = datetime.now()
    if key in _cache and _cache_ttl.get(key, now) > now:
        logger.info(f"Cache hit for key: {key}")
        return _cache[key]
    return None


def _set_cache(key: str, value: str, ttl_minutes: int = CACHE_TTL_MINUTES):
    """Set cached value with TTL."""
    _cache[key] = value
    _cache_ttl[key] = datetime.now() + timedelta(minutes=ttl_minutes)
    logger.info(f"Cached key: {key} (TTL: {ttl_minutes}min)")


def _clear_cache():
    """Clear all cached values."""
    _cache.clear()
    _cache_ttl.clear()
    logger.info("Cache cleared")


# =============================================================================
# Portfolio Status Tool
# =============================================================================

@tool
def get_portfolio_status() -> str:
    """Fetch current portfolio status from Alpaca.

    Returns account equity, cash, buying power, and position counts.
    Results are cached for 5 minutes to reduce API calls.

    Returns:
        JSON string with portfolio status including:
        - equity: Total portfolio value
        - cash: Available cash
        - buying_power: Margin buying power
        - long_positions: Number of long positions
        - short_positions: Number of short positions
        - cached: Whether result is from cache
    """
    cache_key = "portfolio_status"
    start_time = time.time()

    # Check cache first (Improvement #4: Caching)
    cached_result = _get_cached(cache_key)
    if cached_result:
        result = json.loads(cached_result)
        result["cached"] = True
        result["cache_age_seconds"] = int((datetime.now() - _cache_ttl[cache_key] + timedelta(minutes=CACHE_TTL_MINUTES)).total_seconds())
        return json.dumps(result)

    # Direct API call (will refactor to skills layer in Module 5)
    try:
        from alpaca.trading.client import TradingClient

        api_key = secrets.get("alpaca.api_key")
        secret_key = secrets.get("alpaca.secret_key")

        client = TradingClient(api_key, secret_key)

        # Fetch account info
        account = client.get_account()

        # Fetch positions to count long/short
        positions = client.get_all_positions()
        long_count = sum(1 for p in positions if float(p.qty) > 0)
        short_count = sum(1 for p in positions if float(p.qty) < 0)

        result = {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "long_positions": long_count,
            "short_positions": short_count,
            "portfolio_value": float(account.portfolio_value),
            "last_equity": float(account.last_equity),
            "timestamp": datetime.now().isoformat(),
            "cached": False
        }

        result_json = json.dumps(result)

        # Cache for 5 minutes
        _set_cache(cache_key, result_json)

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Portfolio status fetched in {duration_ms}ms")

        return result_json

    except Exception as e:
        logger.error(f"Failed to fetch portfolio status: {e}", exc_info=True)

        # Graceful degradation: Return cached data if available (Improvement #8)
        if cache_key in _cache:
            logger.warning("Returning stale cached data due to API failure")
            result = json.loads(_cache[cache_key])
            result["cached"] = True
            result["stale"] = True
            result["error"] = str(e)
            return json.dumps(result)

        # No cache available, return error
        return json.dumps({
            "error": "Failed to fetch portfolio status",
            "details": str(e),
            "timestamp": datetime.now().isoformat()
        })


# =============================================================================
# Positions Summary Tool
# =============================================================================

@tool
def get_positions_summary() -> str:
    """Fetch current positions with P&L breakdown.

    Returns detailed position information including unrealized P&L,
    cost basis, and current market value for each position.

    Returns:
        JSON string with positions array and summary statistics
    """
    cache_key = "positions_summary"
    start_time = time.time()

    # Check cache
    cached_result = _get_cached(cache_key)
    if cached_result:
        return cached_result

    try:
        from alpaca.trading.client import TradingClient

        api_key = secrets.get("alpaca.api_key")
        secret_key = secrets.get("alpaca.secret_key")

        client = TradingClient(api_key, secret_key)
        positions = client.get_all_positions()

        positions_list = []
        total_market_value = 0.0
        total_unrealized_pl = 0.0

        for pos in positions:
            position_data = {
                "symbol": pos.symbol,
                "qty": float(pos.qty),
                "side": "long" if float(pos.qty) > 0 else "short",
                "market_value": float(pos.market_value),
                "cost_basis": float(pos.cost_basis),
                "unrealized_pl": float(pos.unrealized_pl),
                "unrealized_plpc": float(pos.unrealized_plpc),
                "current_price": float(pos.current_price),
                "avg_entry_price": float(pos.avg_entry_price)
            }
            positions_list.append(position_data)
            total_market_value += float(pos.market_value)
            total_unrealized_pl += float(pos.unrealized_pl)

        result = {
            "positions": positions_list,
            "count": len(positions_list),
            "total_market_value": total_market_value,
            "total_unrealized_pl": total_unrealized_pl,
            "timestamp": datetime.now().isoformat()
        }

        result_json = json.dumps(result)
        _set_cache(cache_key, result_json)

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Positions summary fetched in {duration_ms}ms")

        return result_json

    except Exception as e:
        logger.error(f"Failed to fetch positions: {e}", exc_info=True)

        # Graceful degradation
        if cache_key in _cache:
            logger.warning("Returning stale cached positions")
            return _cache[cache_key]

        return json.dumps({
            "error": "Failed to fetch positions",
            "details": str(e),
            "positions": [],
            "count": 0
        })


# =============================================================================
# Portfolio Health Check Tool
# =============================================================================

@tool
def check_portfolio_health() -> str:
    """Check portfolio health against risk parameters.

    Validates current portfolio state against configured risk limits
    from config.json (position limits, concentration, etc.).

    Returns:
        JSON string with health status and any violations
    """
    try:
        # Get current portfolio status
        portfolio_status = json.loads(get_portfolio_status.invoke({}))

        if "error" in portfolio_status:
            return json.dumps({
                "health_status": "unknown",
                "error": "Cannot check health - portfolio status unavailable",
                "details": portfolio_status.get("details")
            })

        # Get risk parameters from config
        risk_params = config.get("risk_management", {})
        max_daily_trades = risk_params.get("max_daily_trades", 10)
        position_limit_percent = risk_params.get("position_limit_percent", 0.1)

        # Get positions
        positions_data = json.loads(get_positions_summary.invoke({}))

        violations = []
        warnings = []

        # Check position concentration
        equity = portfolio_status.get("equity", 0)
        if equity > 0:
            for pos in positions_data.get("positions", []):
                position_percent = abs(pos["market_value"]) / equity
                if position_percent > position_limit_percent:
                    violations.append({
                        "rule": "position_limit_percent",
                        "symbol": pos["symbol"],
                        "current": position_percent,
                        "limit": position_limit_percent,
                        "message": f"{pos['symbol']} represents {position_percent*100:.1f}% of portfolio (limit: {position_limit_percent*100:.1f}%)"
                    })

        # Check if we have cash
        cash_percent = portfolio_status.get("cash", 0) / equity if equity > 0 else 0
        if cash_percent < 0.05:  # Less than 5% cash
            warnings.append({
                "rule": "cash_reserve",
                "current": cash_percent,
                "message": f"Low cash reserves: {cash_percent*100:.1f}%"
            })

        # Determine health status
        if violations:
            health_status = "unhealthy"
        elif warnings:
            health_status = "warning"
        else:
            health_status = "healthy"

        result = {
            "health_status": health_status,
            "violations": violations,
            "warnings": warnings,
            "checks_performed": [
                "position_concentration",
                "cash_reserves"
            ],
            "timestamp": datetime.now().isoformat()
        }

        return json.dumps(result)

    except Exception as e:
        logger.error(f"Failed to check portfolio health: {e}", exc_info=True)
        return json.dumps({
            "health_status": "error",
            "error": str(e)
        })


# =============================================================================
# Quant Analyst Delegation Tool
# =============================================================================

@tool
def delegate_to_quant_analyst(query: str, thread_id: str = "default") -> str:
    """Delegate technical analysis to the Quant Analyst agent.

    Use this when the user asks for:
    - Stock analysis
    - Technical indicators
    - Trading strategy recommendations
    - Mean reversion signals

    Args:
        query: The analysis query to pass to Quant Analyst
        thread_id: Conversation thread ID (preserve context)

    Returns:
        JSON string with Quant Analyst response or error with fallback
    """
    logger.info(f"[DELEGATION] Portfolio Manager -> Quant Analyst: {query}")

    try:
        # Import Quant Analyst (from Phase 2)
        from src.agents.quant.analyst import QuantAnalyst

        # Create Quant Analyst instance
        quant = QuantAnalyst(backtest_mode=True)

        # Invoke with same thread_id for conversation continuity
        result = quant.invoke(query, apply_middleware=True)

        logger.info("[DELEGATION] Quant Analyst completed analysis")

        return json.dumps({
            "status": "success",
            "response": result["response"],
            "delegated_to": "quant_analyst",
            "timestamp": result.get("timestamp", datetime.now().isoformat())
        })

    except Exception as e:
        logger.error(f"[DELEGATION] Quant delegation failed: {e}", exc_info=True)

        # Graceful degradation (Improvement #8)
        return json.dumps({
            "status": "error",
            "error": "Quant Analyst temporarily unavailable",
            "fallback_action": "Unable to perform technical analysis at this time",
            "recommendation": "Try again in a few minutes or check system health",
            "details": str(e),
            "timestamp": datetime.now().isoformat()
        })


# =============================================================================
# Utility Functions
# =============================================================================

def clear_portfolio_cache():
    """Clear all portfolio-related caches.

    Useful for forcing fresh data fetch or testing.
    """
    _clear_cache()


# =============================================================================
# Main Block for Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Functional tests for portfolio tools."""
    import argparse

    parser = argparse.ArgumentParser(description="Test portfolio tools")
    parser.add_argument("--test", choices=["status", "positions", "health", "delegate", "all"],
                        default="all", help="Which test to run")
    parser.add_argument("--no-cache", action="store_true", help="Clear cache before testing")

    args = parser.parse_args()

    if args.no_cache:
        clear_portfolio_cache()
        print("Cache cleared")

    print("=" * 60)
    print("Portfolio Tools Functional Tests")
    print("=" * 60)

    if args.test in ["status", "all"]:
        print("\n[TEST 1] get_portfolio_status()")
        print("-" * 60)
        result = get_portfolio_status.invoke({})
        data = json.loads(result)
        print(json.dumps(data, indent=2))

        # Test caching
        print("\n[TEST 1b] get_portfolio_status() - Test Cache")
        result2 = get_portfolio_status.invoke({})
        data2 = json.loads(result2)
        if data2.get("cached"):
            print("[OK] Cache working - returned cached result")
        else:
            print("[WARN] Cache not working - fetched fresh data")

    if args.test in ["positions", "all"]:
        print("\n[TEST 2] get_positions_summary()")
        print("-" * 60)
        result = get_positions_summary.invoke({})
        data = json.loads(result)
        print(json.dumps(data, indent=2))

    if args.test in ["health", "all"]:
        print("\n[TEST 3] check_portfolio_health()")
        print("-" * 60)
        result = check_portfolio_health.invoke({})
        data = json.loads(result)
        print(json.dumps(data, indent=2))

    if args.test in ["delegate", "all"]:
        print("\n[TEST 4] delegate_to_quant_analyst()")
        print("-" * 60)
        result = delegate_to_quant_analyst.invoke({
            "query": "Analyze AAPL using mean reversion strategy",
            "thread_id": "test-thread-001"
        })
        data = json.loads(result)
        print(json.dumps(data, indent=2))

    print("\n" + "=" * 60)
    print("Tests Complete")
    print("=" * 60)
