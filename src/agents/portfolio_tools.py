"""
Portfolio Manager Tools (Enhanced)
Module 5: Refactored to use Skills + DAO layers

Uses:
- src.skills.alpaca_portfolio_skills for API calls
- src.dao.portfolio_dao for observability and risk parameters
- Maintains caching and graceful degradation from Module 2
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
from langchain_core.tools import tool

from src.utils import get_logger
from src.skills.alpaca_portfolio_skills import (
    fetch_account_info,
    fetch_positions,
    fetch_orders,
    fetch_portfolio_history
)
from src.skills.alpaca_skills import fetch_historical_bars
from src.dao import PortfolioDAO, AlpacaDAO

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
    Saves snapshot to PortfolioDAO for historical tracking.

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

    # Use Skills layer instead of direct API calls
    try:
        # Fetch account info using alpaca_portfolio_skills
        account_data = fetch_account_info()

        # Fetch positions to count long/short
        positions_data = fetch_positions()
        long_count = sum(1 for p in positions_data if p["side"] == "long")
        short_count = sum(1 for p in positions_data if p["side"] == "short")

        result = {
            "equity": account_data["equity"],
            "cash": account_data["cash"],
            "buying_power": account_data["buying_power"],
            "long_positions": long_count,
            "short_positions": short_count,
            "portfolio_value": account_data["portfolio_value"],
            "last_equity": account_data["last_equity"],
            "timestamp": datetime.now().isoformat(),
            "cached": False
        }

        result_json = json.dumps(result)

        # Cache for 5 minutes
        _set_cache(cache_key, result_json)

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Portfolio status fetched in {duration_ms}ms")

        # Save snapshot to DAO for historical tracking
        try:
            dao = PortfolioDAO()
            dao.save_snapshot(
                timestamp=datetime.now(),
                equity=result["equity"],
                cash=result["cash"],
                buying_power=result["buying_power"],
                long_positions=long_count,
                short_positions=short_count,
                snapshot_source="alpaca"
            )
            dao.close()
        except Exception as dao_error:
            logger.warning(f"Failed to save snapshot to DAO: {dao_error}")

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
    Uses Skills layer for API calls.

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
        # Use Skills layer instead of direct API call
        positions_data = fetch_positions()

        total_market_value = 0.0
        total_unrealized_pl = 0.0

        # Calculate totals
        for pos in positions_data:
            total_market_value += pos["market_value"]
            total_unrealized_pl += pos["unrealized_pl"]

        result = {
            "positions": positions_data,
            "count": len(positions_data),
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
    from PortfolioDAO (position limits, concentration, daily loss, etc.).
    Uses risk parameters stored in portfolio_parameters table.

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

        # Get risk parameters from DAO instead of config
        dao = PortfolioDAO()
        risk_params = dao.get_risk_parameters()
        dao.close()

        # Extract limits with defaults
        position_limit_percent = risk_params.get("position_limit_percent", {}).get("value", 0.1)
        daily_loss_limit = risk_params.get("daily_loss_limit", {}).get("value", 0.05)
        max_position_size = risk_params.get("max_position_size", {}).get("value", 1000)

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

                # Check position size
                if abs(pos["qty"]) > max_position_size:
                    warnings.append({
                        "rule": "max_position_size",
                        "symbol": pos["symbol"],
                        "current": abs(pos["qty"]),
                        "limit": max_position_size,
                        "message": f"{pos['symbol']} position size {abs(pos['qty'])} exceeds limit {max_position_size}"
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
                "position_size",
                "cash_reserves"
            ],
            "risk_parameters_used": {
                "position_limit_percent": position_limit_percent,
                "max_position_size": max_position_size,
                "daily_loss_limit": daily_loss_limit
            },
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


@tool
def delegate_to_backtester(query: str, thread_id: str = "default") -> str:
    """Delegate backtesting to the Backtester agent.

    Use this when the user asks for:
    - Strategy backtesting
    - Historical performance analysis
    - "What if" simulations on past data
    - Validating trading strategies before deployment

    Args:
        query: The backtest query to pass to Backtester
        thread_id: Conversation thread ID (preserve context)

    Returns:
        JSON string with backtest results or error with fallback
    """
    logger.info(f"[DELEGATION] Portfolio Manager -> Backtester: {query}")

    try:
        # Import Backtester (from Phase 4)
        from src.agents.backtester.backtester import Backtester

        # Create Backtester instance
        backtester = Backtester(model="gpt-4o-mini")

        # Invoke with same thread_id for conversation continuity
        result = backtester.invoke(query, thread_id=thread_id, apply_middleware=True)

        logger.info("[DELEGATION] Backtester completed analysis")

        return json.dumps({
            "status": "success",
            "response": result["response"],
            "delegated_to": "backtester",
            "timestamp": result.get("timestamp", datetime.now().isoformat())
        })

    except Exception as e:
        logger.error(f"[DELEGATION] Backtester delegation failed: {e}", exc_info=True)

        # Graceful degradation
        return json.dumps({
            "status": "error",
            "error": "Backtester temporarily unavailable",
            "fallback_action": "Unable to run backtest simulation at this time",
            "recommendation": "Try again later or check data availability",
            "details": str(e),
            "timestamp": datetime.now().isoformat()
        })


<<<<<<< HEAD
# =============================================================================
# Historical Data Fetching Tool
# =============================================================================

@tool
def fetch_historical_data(symbol: str, start_date: str, end_date: str, timeframe: str = "1Min") -> str:
    """Fetch historical market data and save to database.

    Use this tool BEFORE delegating to Backtester to ensure data availability.
    This tool fetches data from Alpaca API and persists it to the database.

    Args:
        symbol: Stock ticker (e.g., 'AAPL')
        start_date: Start date in YYYY-MM-DD format (e.g., '2026-01-01')
        end_date: End date in YYYY-MM-DD format (e.g., '2026-01-31')
        timeframe: Bar timeframe (default: '1Min' for intraday backtesting)

    Returns:
        JSON string with fetch status:
        - status: 'success' or 'error'
        - bars_fetched: Number of bars retrieved
        - date_range: Confirmation of requested period
        - message: Human-readable result

    Example:
        fetch_historical_data.invoke({
            "symbol": "AAPL",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31"
        })
    """
    logger.info(f"[DATA FETCH] Fetching historical data for {symbol} from {start_date} to {end_date}")

    try:
        # Convert date strings to datetime objects
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)

        # Validate dates are historical
        now = datetime.now()
        if start_dt > now or end_dt > now:
            return json.dumps({
                "status": "error",
                "error": "Future dates not allowed",
                "message": f"Start or end date is in the future. Current date: {now.date()}",
                "suggestion": f"Use dates up to {now.date()}"
            })

        # First check if data already exists
        dao = AlpacaDAO()
        existing_bars = dao.get_bars(symbol, start=start_dt, end=end_dt, timeframe=timeframe)

        if not existing_bars.empty:
            bar_count = len(existing_bars)
            logger.info(f"[DATA FETCH] Data already exists: {bar_count} bars for {symbol}")
            return json.dumps({
                "status": "success",
                "bars_fetched": bar_count,
                "symbol": symbol,
                "date_range": f"{start_date} to {end_date}",
                "timeframe": timeframe,
                "message": f"Data already available: {bar_count} bars found in database",
                "data_source": "database_cache"
            })

        # Data doesn't exist, fetch from Alpaca API
        logger.info(f"[DATA FETCH] No existing data, fetching from Alpaca API...")

        # Use Alpaca skills to fetch and save data
        bars_df = fetch_historical_bars(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe
        )

        if bars_df is None or bars_df.empty:
            return json.dumps({
                "status": "error",
                "error": "No data returned from API",
                "symbol": symbol,
                "date_range": f"{start_date} to {end_date}",
                "message": f"Alpaca API returned no data for {symbol} in the specified range",
                "suggestion": "Verify symbol is correct and date range is valid (market was open)"
            })

        bar_count = len(bars_df)
        logger.info(f"[DATA FETCH] Successfully fetched {bar_count} bars for {symbol}")

        return json.dumps({
            "status": "success",
            "bars_fetched": bar_count,
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "timeframe": timeframe,
            "message": f"Successfully fetched and saved {bar_count} bars from Alpaca API",
            "data_source": "alpaca_api"
        })

    except Exception as e:
        logger.error(f"[DATA FETCH] Error fetching data for {symbol}: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "error": str(e),
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "message": f"Failed to fetch historical data: {str(e)}"
        })


@tool
def check_data_availability(symbol: str, start_date: str, end_date: str, timeframe: str = "1Min") -> str:
    """Check if historical data exists in database for given period.

    Use this tool BEFORE fetch_historical_data to avoid unnecessary API calls.
    This tool only queries the database, does not fetch from API.

    Args:
        symbol: Stock ticker (e.g., 'AAPL')
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        timeframe: Bar timeframe (default: '1Min')

    Returns:
        JSON string with availability status:
        - available: true/false
        - bar_count: Number of bars found (0 if not available)
        - coverage: Percentage of expected bars found
        - message: Human-readable result
    """
    logger.info(f"[DATA CHECK] Checking data availability for {symbol} from {start_date} to {end_date}")

    try:
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)

        dao = AlpacaDAO()
        bars_df = dao.get_bars(symbol, start=start_dt, end=end_dt, timeframe=timeframe)

        bar_count = len(bars_df)

        # Calculate expected bars (rough estimate: 390 bars per trading day for 1Min)
        trading_days = (end_dt - start_dt).days
        expected_bars = trading_days * 390 if timeframe == "1Min" else trading_days
        coverage_pct = (bar_count / expected_bars * 100) if expected_bars > 0 else 0

        if bar_count == 0:
            return json.dumps({
                "available": False,
                "bar_count": 0,
                "symbol": symbol,
                "date_range": f"{start_date} to {end_date}",
                "message": f"No data found for {symbol} in database",
                "action_needed": "fetch_historical_data"
            })
        elif coverage_pct < 80:
            return json.dumps({
                "available": "partial",
                "bar_count": bar_count,
                "expected_bars": expected_bars,
                "coverage_pct": round(coverage_pct, 1),
                "symbol": symbol,
                "date_range": f"{start_date} to {end_date}",
                "message": f"Partial data found: {bar_count} bars ({coverage_pct:.1f}% coverage)",
                "action_needed": "fetch_historical_data to fill gaps"
            })
        else:
            return json.dumps({
                "available": True,
                "bar_count": bar_count,
                "expected_bars": expected_bars,
                "coverage_pct": round(coverage_pct, 1),
                "symbol": symbol,
                "date_range": f"{start_date} to {end_date}",
                "message": f"Data available: {bar_count} bars ({coverage_pct:.1f}% coverage)",
                "action_needed": "none - proceed with backtest"
            })

    except Exception as e:
        logger.error(f"[DATA CHECK] Error checking data availability: {e}")
        return json.dumps({
            "available": False,
            "error": str(e),
            "message": f"Error checking data availability: {str(e)}"
        })


=======
>>>>>>> feat: Phase 4 - Backtester Agent Implementation
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
