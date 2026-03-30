"""Guard nodes for the semi-auto multi-agent system.

Identical to src/langgraph/nodes/guards.py — reuses the same middleware.
market_hours_guard and portfolio_guard short-circuit to synthesizer on violation.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.core.middleware.agent_middleware import (
    MarketHoursGuardMiddleware,
    PortfolioGuardMiddleware,
)
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


if __name__ == "__main__":
    """Smoke test: guard in backtest_mode should always pass."""
    result = market_hours_guard({"backtest_mode": True})
    assert result == {}, f"Expected empty dict, got: {result}"
    print("[OK] market_hours_guard backtest_mode=True passes")
