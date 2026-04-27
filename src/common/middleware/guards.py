"""Guard nodes for the trading multi-agent LangGraph system.

market_hours_guard and portfolio_guard are thin LangGraph node wrappers
around MarketHoursGuardMiddleware and PortfolioGuardMiddleware. Both
short-circuit to the synthesizer node on violation.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.middleware.market_hours import MarketHoursGuardMiddleware
from src.common.middleware.portfolio_guard import PortfolioGuardMiddleware
from src.common.utils import get_logger

logger = get_logger(__name__)


def market_hours_guard(state: dict) -> dict:
    """Reject execution outside NYSE market hours.

    Bypassed automatically when state["backtest_mode"] is True.

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update. Sets routing_error + final_response on
        violation; returns empty dict when the guard passes.
    """
    backtest_mode: bool = state.get("backtest_mode", False)
    guard = MarketHoursGuardMiddleware(backtest_mode=backtest_mode)
    try:
        guard.before_agent(state, runtime=None)
        logger.info("[market_hours_guard] passed")
        return {}
    except RuntimeError as exc:
        error_msg = str(exc)
        logger.warning(f"[market_hours_guard] blocked: {error_msg}")
        return {
            "routing_error": error_msg,
            "final_response": (
                f"Market Hours Guard\n\n"
                f"Your request cannot be processed right now:\n\n{error_msg}\n\n"
                f"Please retry during NYSE market hours (Mon-Fri 9:30 AM - 4:00 PM ET) "
                f"or enable backtest_mode=True for historical queries."
            ),
        }


def portfolio_guard(state: dict) -> dict:
    """Halt execution when the daily portfolio loss limit is breached.

    Bypassed automatically when state["backtest_mode"] is True.

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update. Sets routing_error + final_response on
        violation; returns empty dict when the guard passes.
    """
    backtest_mode: bool = state.get("backtest_mode", False)
    guard = PortfolioGuardMiddleware(backtest_mode=backtest_mode)
    try:
        guard.before_agent(state, runtime=None)
        logger.info("[portfolio_guard] passed")
        return {}
    except RuntimeError as exc:
        error_msg = str(exc)
        logger.warning(f"[portfolio_guard] blocked: {error_msg}")
        return {
            "routing_error": error_msg,
            "final_response": (
                f"Portfolio Risk Guard\n\n"
                f"Execution halted:\n\n{error_msg}\n\n"
                f"Trading is suspended until the daily loss limit resets."
            ),
        }


if __name__ == "__main__":
    print("=" * 50)
    print("guards Smoke Tests")
    print("=" * 50)

    result = market_hours_guard({"backtest_mode": True})
    assert result == {}, f"Expected empty dict, got: {result}"
    print("[OK] market_hours_guard backtest_mode=True passes")

    result = portfolio_guard({"backtest_mode": True})
    assert result == {}, f"Expected empty dict, got: {result}"
    print("[OK] portfolio_guard backtest_mode=True passes")

    print("\n[ALL OK] guards smoke tests complete")
