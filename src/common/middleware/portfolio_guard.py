"""Portfolio risk guard middleware.

Enforces daily P&L loss limits before allowing Portfolio Manager execution.
Checks the latest portfolio snapshot against the configured daily_loss_limit.
Bypassed automatically when backtest_mode=True.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from typing import Any, Optional

from src.common.utils import get_logger

logger = get_logger(__name__)


class PortfolioGuardMiddleware:
    """Middleware to enforce risk limits for Portfolio Manager.

    Uses before_agent hook to check portfolio risk parameters before execution.
    """

    def __init__(self, backtest_mode: bool = False):
        """Initialize portfolio guard.

        Args:
            backtest_mode: If True, bypass the check (for testing / backtests).
        """
        self.backtest_mode = backtest_mode

    def before_agent(self, state: dict, runtime: Any) -> Optional[dict]:
        """Check risk limits before agent execution.

        Args:
            state: Current agent state.
            runtime: Agent runtime context.

        Returns:
            None to continue execution.

        Raises:
            RuntimeError: If daily loss limit is breached.
        """
        if self.backtest_mode:
            logger.info("Portfolio guard bypassed (backtest mode)")
            return None

        try:
            from src.common.dao import PortfolioDAO

            dao = PortfolioDAO()
            latest_snapshot = dao.get_latest_snapshot()

            if latest_snapshot:
                risk_params = dao.get_risk_parameters()
                daily_loss_limit = risk_params.get("daily_loss_limit", {}).get("value", 0.05)
                daily_pnl_percent = latest_snapshot.get("daily_pnl_percent")

                if daily_pnl_percent is not None and daily_pnl_percent < -daily_loss_limit:
                    error_msg = (
                        f"Daily loss limit exceeded: {daily_pnl_percent * 100:.2f}% "
                        f"(limit: -{daily_loss_limit * 100:.2f}%). "
                        f"Trading halted for risk management."
                    )
                    logger.error(error_msg)
                    dao.close()
                    raise RuntimeError(error_msg)

                logger.info(
                    f"Portfolio health check passed: daily P&L {daily_pnl_percent * 100:.2f}%"
                )

            dao.close()

        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning(f"Portfolio guard check skipped: {exc}")

        return None


if __name__ == "__main__":
    print("=" * 60)
    print("PortfolioGuardMiddleware Smoke Test")
    print("=" * 60)

    guard = PortfolioGuardMiddleware(backtest_mode=True)
    result = guard.before_agent({}, None)
    assert result is None
    print("[OK] backtest_mode=True bypasses check")

    print("\n[ALL OK] PortfolioGuardMiddleware smoke test complete")
