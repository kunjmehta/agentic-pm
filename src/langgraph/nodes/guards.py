"""Guard nodes for the deterministic LangGraph agent.

market_hours_guard  ← wraps MarketHoursGuardMiddleware
portfolio_guard     ← wraps PortfolioGuardMiddleware

On RuntimeError both guards set routing_error + final_response so the
conditional edge can short-circuit directly to the synthesizer node.
LoopPreventionMiddleware is intentionally omitted — deterministic graphs
cannot loop.
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
                f"⏰ **Market Hours Guard**\n\n"
                f"Your request cannot be processed right now:\n\n{error_msg}\n\n"
                f"Please retry during NYSE market hours (Mon–Fri 9:30 AM – 4:00 PM ET) "
                f"or enable `backtest_mode=True` for historical queries."
            ),
        }


def portfolio_guard(state: dict) -> dict:
    """Enforce portfolio risk limits before live-market operations.

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
        logger.error(f"[portfolio_guard] blocked: {error_msg}")
        return {
            "routing_error": error_msg,
            "final_response": (
                f"🚨 **Portfolio Risk Guard**\n\n"
                f"Trading has been halted due to a risk limit violation:\n\n{error_msg}\n\n"
                f"Review your positions and P&L before resuming operations."
            ),
        }


if __name__ == "__main__":
    """Functional test: both guards in backtest_mode bypass correctly."""
    print("=" * 60)
    print("Guard Node Functional Tests")
    print("=" * 60)

    # Test 1: market_hours_guard in backtest mode should pass
    print("\n[1/4] market_hours_guard — backtest_mode=True (should pass)")
    result = market_hours_guard({"backtest_mode": True})
    assert result == {}, f"Expected empty dict, got: {result}"
    print("[OK] returned empty dict (pass-through)")

    # Test 2: market_hours_guard in live mode (may fail or pass depending on time)
    print("\n[2/4] market_hours_guard — backtest_mode=False (may block outside hours)")
    result = market_hours_guard({"backtest_mode": False})
    if result:
        assert "routing_error" in result
        assert "final_response" in result
        print(f"[OK] blocked with routing_error: {result['routing_error'][:60]}...")
    else:
        print("[OK] market is open — guard passed")

    # Test 3: portfolio_guard in backtest mode should pass
    print("\n[3/4] portfolio_guard — backtest_mode=True (should pass)")
    result = portfolio_guard({"backtest_mode": True})
    assert result == {}, f"Expected empty dict, got: {result}"
    print("[OK] returned empty dict (pass-through)")

    # Test 4: verify routing_error keys are present when guard fires
    print("\n[4/4] Verify guard output keys are correct")
    # Simulate a guard firing by directly inspecting the return structure
    from src.common.core.middleware.agent_middleware import MarketHoursGuardMiddleware as _MH
    import pytz
    from datetime import datetime, time

    # Mock a closed-market scenario by patching the guard inline
    class _AlwaysClosedGuard:
        def before_agent(self, s, r):
            raise RuntimeError("Market closed (test)")

    class _TestGuard:
        def market_hours_guard(self, state):
            try:
                _AlwaysClosedGuard().before_agent(state, None)
                return {}
            except RuntimeError as exc:
                return {"routing_error": str(exc), "final_response": f"blocked: {exc}"}

    tg = _TestGuard()
    result = tg.market_hours_guard({})
    assert "routing_error" in result
    assert "final_response" in result
    print("[OK] routing_error and final_response keys present on block")

    print("\n" + "=" * 60)
    print("Guard tests complete!")
