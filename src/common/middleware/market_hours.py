"""Market hours guard middleware.

Rejects agent execution outside NYSE market hours (Mon–Fri 9:30 AM – 4:00 PM ET).
Bypassed automatically when backtest_mode=True.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from datetime import datetime, time
from typing import Any, Optional

import pytz

from src.common.utils import get_logger

logger = get_logger(__name__)


class MarketHoursGuardMiddleware:
    """Middleware to reject execution outside NYSE market hours.

    Uses before_agent hook to check market hours before agent execution.
    """

    def __init__(self, backtest_mode: bool = False):
        """Initialize market hours guard.

        Args:
            backtest_mode: If True, bypass the check (for testing / historical queries).
        """
        self.backtest_mode = backtest_mode

    def before_agent(self, state: dict, runtime: Any) -> Optional[dict]:
        """Check market hours before agent execution.

        Args:
            state: Current agent state.
            runtime: Agent runtime context.

        Returns:
            None to continue execution.

        Raises:
            RuntimeError: If market is closed and not in backtest mode.
        """
        if self.backtest_mode:
            logger.info("Market hours guard bypassed (backtest mode)")
            return None

        eastern = pytz.timezone("America/New_York")
        now_et = datetime.now(eastern)
        current_time = now_et.time()

        market_open = time(9, 30)
        market_close = time(16, 0)

        is_weekday = now_et.weekday() < 5
        is_market_hours = market_open <= current_time <= market_close

        if not (is_weekday and is_market_hours):
            error_msg = (
                f"Market is CLOSED. Current time: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}. "
                f"Market hours: Mon-Fri 9:30 AM - 4:00 PM ET"
            )
            logger.warning(error_msg)
            raise RuntimeError(error_msg)

        logger.info(f"Market is OPEN. Proceeding at {now_et.strftime('%H:%M:%S %Z')}")
        return None


if __name__ == "__main__":
    print("=" * 60)
    print("MarketHoursGuardMiddleware Smoke Test")
    print("=" * 60)

    guard = MarketHoursGuardMiddleware(backtest_mode=True)
    result = guard.before_agent({}, None)
    assert result is None
    print("[OK] backtest_mode=True bypasses check")

    guard_live = MarketHoursGuardMiddleware(backtest_mode=False)
    try:
        guard_live.before_agent({}, None)
        print("[OK] Market is currently open")
    except RuntimeError as exc:
        print(f"[OK] Market closed (expected outside hours): {exc}")

    print("\n[ALL OK] MarketHoursGuardMiddleware smoke test complete")
