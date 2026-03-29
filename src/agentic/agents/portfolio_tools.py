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
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Literal, Optional
from langchain_core.tools import tool

from src.common.utils import get_logger
from src.agentic.agents.portfolio.skills.portfoliostatus.status import (
    get_portfolio_status_core,
    get_positions_summary_core
)
from src.agentic.agents.portfolio.skills.health.health import check_portfolio_health_core
from src.agentic.agents.portfolio.skills.datamanagement.data import (
    fetch_historical_data_core,
    check_data_availability_core
)
from src.agentic.agents.portfolio.skills.delegation.delegation import (
    delegate_to_quant_analyst_core,
    delegate_to_backtester_core
)

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

    USE WHEN: user asks about equity, cash, buying power, or aggregate portfolio value.
    DO NOT USE WHEN: user wants individual position details or P&L per stock (use get_positions_summary).
    DO NOT USE WHEN: user asks about risk limits or violations (use check_portfolio_health).

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
    logger.info(f"[TOOL] Calling: get_portfolio_status")
    logger.info(f"[TOOL] Input: {json.dumps({}, indent=2)}")

    cache_key = "portfolio_status"
    start_time = time.time()

    # Check cache first (Improvement #4: Caching)
    cached_result = _get_cached(cache_key)
    if cached_result:
        result = json.loads(cached_result)
        result["cached"] = True
        result["cache_age_seconds"] = int((datetime.now() - _cache_ttl[cache_key] + timedelta(minutes=CACHE_TTL_MINUTES)).total_seconds())
        output = json.dumps(result)
        logger.info(f"[TOOL] Output: {output[:500]}..." if len(output) > 500 else f"[TOOL] Output: {output}")
        return output

    # Use Skills layer instead of direct API calls
    try:
        # Call core skill function
        result = get_portfolio_status_core()
        result["cached"] = False

        result_json = json.dumps(result)

        # Cache for 5 minutes
        _set_cache(cache_key, result_json)

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Portfolio status fetched in {duration_ms}ms")

        # Log output
        if len(result_json) > 500:
            logger.info(f"[TOOL] Output: {result_json[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {result_json}")

        return result_json

    except Exception as e:
        error_msg = f"Failed to fetch portfolio status: {e}"
        logger.error(f"[TOOL] Error: {error_msg}", exc_info=True)

        # Graceful degradation: Return cached data if available (Improvement #8)
        if cache_key in _cache:
            logger.warning("Returning stale cached data due to API failure")
            result = json.loads(_cache[cache_key])
            result["cached"] = True
            result["stale"] = True
            result["error"] = str(e)
            output = json.dumps(result)
            logger.info(f"[TOOL] Output: {output[:500]}..." if len(output) > 500 else f"[TOOL] Output: {output}")
            return output

        # No cache available, return error
        error_result = json.dumps({
            "error": "Failed to fetch portfolio status",
            "details": str(e),
            "timestamp": datetime.now().isoformat()
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


# =============================================================================
# Positions Summary Tool
# =============================================================================

@tool
def get_positions_summary() -> str:
    """Fetch current positions with P&L breakdown.

    USE WHEN: user asks about individual holdings, positions, P&L per stock, "what do I own".
    DO NOT USE WHEN: user wants aggregate account value (use get_portfolio_status instead).

    Returns detailed position information including unrealized P&L,
    cost basis, and current market value for each position.

    Returns:
        JSON string with positions array and summary statistics
    """
    logger.info(f"[TOOL] Calling: get_positions_summary")
    logger.info(f"[TOOL] Input: {json.dumps({}, indent=2)}")

    cache_key = "positions_summary"
    start_time = time.time()

    # Check cache
    cached_result = _get_cached(cache_key)
    if cached_result:
        logger.info(f"[TOOL] Output: {cached_result[:500]}..." if len(cached_result) > 500 else f"[TOOL] Output: {cached_result}")
        return cached_result

    try:
        # Call core skill function
        result = get_positions_summary_core()

        result_json = json.dumps(result)
        _set_cache(cache_key, result_json)

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Positions summary fetched in {duration_ms}ms")

        # Log output
        if len(result_json) > 500:
            logger.info(f"[TOOL] Output: {result_json[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {result_json}")

        return result_json

    except Exception as e:
        error_msg = f"Failed to fetch positions: {e}"
        logger.error(f"[TOOL] Error: {error_msg}", exc_info=True)

        # Graceful degradation
        if cache_key in _cache:
            logger.warning("Returning stale cached positions")
            output = _cache[cache_key]
            logger.info(f"[TOOL] Output: {output[:500]}..." if len(output) > 500 else f"[TOOL] Output: {output}")
            return output

        error_result = json.dumps({
            "error": "Failed to fetch positions",
            "details": str(e),
            "positions": [],
            "count": 0
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


# =============================================================================
# Portfolio Health Check Tool
# =============================================================================

@tool
def check_portfolio_health() -> str:
    """Check portfolio health against risk parameters.

    USE WHEN: user asks about risk, violations, health status, or "is it safe to trade". Always
    call this before making any trading recommendations.
    DO NOT USE WHEN: user just wants to see current portfolio values (use get_portfolio_status).

    Validates current portfolio state against configured risk limits
    (position concentration, position size, daily loss limits).

    Returns:
        JSON string with health status and any violations
    """
    logger.info(f"[TOOL] Calling: check_portfolio_health")
    logger.info(f"[TOOL] Input: {json.dumps({}, indent=2)}")

    try:
        # Get current portfolio status
        portfolio_status = json.loads(get_portfolio_status.invoke({}))

        if "error" in portfolio_status:
            return json.dumps({
                "health_status": "unknown",
                "error": "Cannot check health - portfolio status unavailable",
                "details": portfolio_status.get("details")
            })

        # Get positions
        positions_data = json.loads(get_positions_summary.invoke({}))

        # Call core function from skill file
        result = check_portfolio_health_core(portfolio_status, positions_data)
        result["timestamp"] = datetime.now().isoformat()
        result["cached"] = False

        output = json.dumps(result)
        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")

        return output

    except Exception as e:
        error_msg = f"Failed to check portfolio health: {e}"
        logger.error(f"[TOOL] Error: {error_msg}", exc_info=True)
        error_result = json.dumps({
            "health_status": "error",
            "error": str(e)
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


# =============================================================================
# Quant Analyst Delegation Tool
# =============================================================================

@tool
def delegate_to_quant_analyst(query: str, thread_id: str = "default") -> str:
    """Delegate technical analysis to the Quant Analyst agent.

    USE WHEN: user asks for technical indicators, buy/sell signals, RSI, MACD, momentum,
    mean reversion analysis, or "should I buy X" (technical view).
    DO NOT USE WHEN: user asks about portfolio status or health (handle directly).
    DO NOT USE WHEN: user needs historical data fetched (use fetch_historical_data instead).

    Args:
        query: The analysis query to pass to Quant Analyst
        thread_id: Conversation thread ID (preserve context)

    Returns:
        JSON string with Quant Analyst response or error with fallback
    """
    logger.info(f"[TOOL] Calling: delegate_to_quant_analyst")
    logger.info(f"[TOOL] Input: {json.dumps({'query': query, 'thread_id': thread_id}, indent=2)}")
    logger.info(f"[DELEGATION] Portfolio Manager -> Quant Analyst: {query}")

    try:
        # Call core function from skill file
        result = delegate_to_quant_analyst_core(query, thread_id)

        logger.info("[DELEGATION] Quant Analyst completed analysis")

        output = json.dumps(result)
        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")
        return output

    except Exception as e:
        error_msg = f"Quant delegation failed: {e}"
        logger.error(f"[DELEGATION] {error_msg}", exc_info=True)
        logger.error(f"[TOOL] Error: {error_msg}")

        # Graceful degradation (Improvement #8)
        error_result = json.dumps({
            "status": "error",
            "error": "Quant Analyst temporarily unavailable",
            "fallback_action": "Unable to perform technical analysis at this time",
            "recommendation": "Try again in a few minutes or check system health",
            "details": str(e),
            "timestamp": datetime.now().isoformat()
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


@tool
def delegate_to_backtester(
    symbol: str,
    strategy: Literal["buy-and-hold", "mean-reversion", "momentum"],
    start_date: str,
    end_date: str,
    timeframe: str = "1Min",
    initial_capital: float = 100000.0,
    thread_id: str = "default"
) -> str:
    """Delegate a backtest to the Backtester agent.

    USE WHEN: user asks to backtest a strategy after data availability has been confirmed.
    ALWAYS call check_data_availability first; fetch with fetch_historical_data if needed.
    DO NOT USE WHEN: data has not been verified for the requested date range.

    Args:
        symbol: Stock ticker (e.g. 'AAPL')
        strategy: Strategy to run — exactly one of 'buy-and-hold', 'mean-reversion', 'momentum'
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        timeframe: Bar timeframe (default '1Min')
        initial_capital: Starting capital in USD (default 100000)
        thread_id: Conversation thread ID (preserve context)

    Returns:
        JSON string with backtest metrics or error
    """
    logger.info(f"[TOOL] Calling: delegate_to_backtester")
    logger.info(f"[TOOL] Input: {json.dumps({'symbol': symbol, 'strategy': strategy, 'start_date': start_date, 'end_date': end_date}, indent=2)}")
    logger.info(f"[DELEGATION] Portfolio Manager -> Backtester: {symbol} {strategy} {start_date}→{end_date}")

    try:
        result = delegate_to_backtester_core(
            symbol=symbol,
            strategy=strategy,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            initial_capital=initial_capital,
            thread_id=thread_id
        )

        logger.info("[DELEGATION] Backtester completed analysis")

        output = json.dumps(result)
        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")
        return output

    except Exception as e:
        error_msg = f"Backtester delegation failed: {e}"
        logger.error(f"[DELEGATION] {error_msg}", exc_info=True)
        logger.error(f"[TOOL] Error: {error_msg}")

        # Graceful degradation
        error_result = json.dumps({
            "status": "error",
            "error": "Backtester temporarily unavailable",
            "fallback_action": "Unable to run backtest simulation at this time",
            "recommendation": "Try again later or check data availability",
            "details": str(e),
            "timestamp": datetime.now().isoformat()
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


# =============================================================================
# Historical Data Fetching Tool
# =============================================================================

@tool
def fetch_historical_data(symbol: str, start_date: str, end_date: str, timeframe: str = "1Min") -> str:
    """Fetch historical market data and save to database.

    USE WHEN: check_data_availability returns available=false and data must be fetched
    before delegating to Backtester.
    DO NOT USE WHEN: check_data_availability already confirmed available=true (skip fetch).

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
    logger.info(f"[TOOL] Calling: fetch_historical_data")
    logger.info(f"[TOOL] Input: {json.dumps({'symbol': symbol, 'start_date': start_date, 'end_date': end_date, 'timeframe': timeframe}, indent=2)}")
    logger.info(f"[DATA FETCH] Fetching historical data for {symbol} from {start_date} to {end_date}")

    try:
        # Call core function from skill file
        result = fetch_historical_data_core(symbol, start_date, end_date, timeframe)

        output = json.dumps(result)
        if result.get("status") == "error":
            error_msg = result.get("error", "Unknown error")
            logger.error(f"[DATA FETCH] {error_msg}")
        else:
            logger.info(f"[DATA FETCH] Successfully fetched {result.get('bars_fetched', 0)} bars for {symbol}")

        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")
        return output

    except Exception as e:
        error_msg = f"Error fetching data for {symbol}: {e}"
        logger.error(f"[DATA FETCH] {error_msg}", exc_info=True)
        logger.error(f"[TOOL] Error: {error_msg}")
        error_result = json.dumps({
            "status": "error",
            "error": str(e),
            "symbol": symbol,
            "date_range": f"{start_date} to {end_date}",
            "message": f"Failed to fetch historical data: {str(e)}"
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


@tool
def check_data_availability(symbol: str, start_date: str, end_date: str, timeframe: str = "1Min") -> str:
    """Check if historical data exists in database for given period.

    USE WHEN: BEFORE every backtest delegation — always verify data exists first.
    DO NOT USE WHEN: data availability is already confirmed for this symbol/date range.

    Only queries the local database — does not call Alpaca API.

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
    logger.info(f"[TOOL] Calling: check_data_availability")
    logger.info(f"[TOOL] Input: {json.dumps({'symbol': symbol, 'start_date': start_date, 'end_date': end_date, 'timeframe': timeframe}, indent=2)}")
    logger.info(f"[DATA CHECK] Checking data availability for {symbol} from {start_date} to {end_date}")

    try:
        # Call core function from skill file
        result = check_data_availability_core(symbol, start_date, end_date, timeframe)

        output = json.dumps(result)
        logger.info(f"[DATA CHECK] {result.get('message', 'Check complete')}")
        if len(output) > 500:
            logger.info(f"[TOOL] Output: {output[:500]}... (truncated)")
        else:
            logger.info(f"[TOOL] Output: {output}")
        return output

    except Exception as e:
        error_msg = f"Error checking data availability: {e}"
        logger.error(f"[DATA CHECK] {error_msg}")
        logger.error(f"[TOOL] Error: {error_msg}")
        error_result = json.dumps({
            "available": False,
            "error": str(e),
            "message": f"Error checking data availability: {str(e)}"
        })
        logger.info(f"[TOOL] Output: {error_result}")
        return error_result


# =============================================================================
# Dispatch Capture (used by src/graph portfolio_agent_node)
# =============================================================================

# Thread-safe global instead of ContextVar: DeepAgent executes tools in worker
# threads whose context copies are invisible to the main thread that calls
# get_captured_dispatch(). A plain dict protected by a lock is always visible.
_dispatch_lock = threading.Lock()
_dispatch_captured: Optional[dict] = None


@tool
def declare_dispatch(dispatch_json: str) -> str:
    """Declare the parallel analysis tasks for the graph to execute.

    Call this as your FINAL action after gathering portfolio context.
    The graph will use this declaration to fan out quant and backtest
    tasks in parallel. Do NOT call delegate_to_quant_analyst or
    delegate_to_backtester — this tool replaces both.

    Args:
        dispatch_json: JSON string conforming to AgentDispatch schema:
            {
              "quant_tasks": [{"task_id": "quant-AAPL-001", "symbol": "AAPL",
                               "analysis_type": "full", "use_precomputed": true,
                               "lookback_minutes": 100}],
              "backtest_tasks": [{"task_id": "bt-AAPL-A-001", "workflow": "A",
                                  "symbol": "AAPL", "strategy": "mean-reversion",
                                  "start_date": "2026-01-01", "end_date": "2026-01-31"}],
              "portfolio_context": {"portfolio_status": {...}, "positions_summary": {...}},
              "reasoning_summary": "Dispatching full quant + backtest for AAPL."
            }
            Use empty lists for quant_tasks/backtest_tasks for pure portfolio queries.

    Returns:
        Confirmation string that dispatch was registered.
    """
    global _dispatch_captured
    try:
        parsed = json.loads(dispatch_json)
        with _dispatch_lock:
            _dispatch_captured = parsed
        n_quant = len(parsed.get("quant_tasks", []))
        n_bt = len(parsed.get("backtest_tasks", []))
        logger.info(f"[declare_dispatch] captured: {n_quant} quant, {n_bt} backtest tasks")
        return f"Dispatch registered: {n_quant} quant tasks, {n_bt} backtest tasks."
    except Exception as exc:
        logger.error(f"[declare_dispatch] failed to parse dispatch_json: {exc}")
        return f"Dispatch parse error: {exc}"


def get_captured_dispatch() -> Optional[dict]:
    """Return the AgentDispatch dict captured by the last declare_dispatch call.

    Returns:
        Captured dispatch dict or None if not set.
    """
    with _dispatch_lock:
        return _dispatch_captured


def reset_dispatch_capture() -> None:
    """Reset the dispatch capture for a fresh agent invocation."""
    global _dispatch_captured
    with _dispatch_lock:
        _dispatch_captured = None


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
