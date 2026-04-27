"""Scheduled backtest executor service.

This module provides automatic post-EOD backtesting capabilities.
Backtests are scheduled to run after market close (4 PM ET weekdays)
and execute configured strategies across all watchlist symbols.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.common.utils import config, get_logger
from src.server.services.notifications.helpers import (
    notify_backtest_completed,
    notify_backtest_failed
)

logger = get_logger(__name__)


class BacktestScheduler:
    """Schedules and executes post-EOD backtests.

    Reads configuration from config.json and executes backtests
    automatically after market close. Each configured backtest
    is run for all specified symbols.
    """

    def __init__(self):
        """Initialize scheduler with config settings."""
        self.scheduler = AsyncIOScheduler()
        self.enabled = config.get("scheduled_backtests.enabled", default=False)
        self.schedule = config.get("scheduled_backtests.schedule", default="0 17 * * 1-5")
        logger.info(f"BacktestScheduler initialized: enabled={self.enabled}, schedule={self.schedule}")

    def start(self):
        """Start scheduled backtest executor.

        Registers the scheduled job and starts the scheduler.
        Only starts if enabled in configuration.
        """
        if not self.enabled:
            logger.info("Scheduled backtests disabled in config")
            return

        # Parse cron schedule (e.g., "0 17 * * 1-5" = 4:30 PM ET weekdays)
        parts = self.schedule.split()
        if len(parts) != 5:
            logger.error(f"Invalid cron schedule: {self.schedule}")
            return

        minute, hour, day, month, day_of_week = parts

        self.scheduler.add_job(
            self._run_all_scheduled_backtests,
            'cron',
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            id='scheduled_backtests',
            name='EOD Scheduled Backtests',
            timezone='America/New_York'  # Use ET timezone
        )

        self.scheduler.start()
        logger.info(f"[OK] Scheduled backtests enabled: {self.schedule}")

    def stop(self):
        """Stop the scheduler gracefully."""
        if hasattr(self, 'scheduler') and self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("[OK] Backtest scheduler stopped")

    async def _run_all_scheduled_backtests(self):
        """Execute all configured scheduled backtests.

        This is the main execution function called by the scheduler.
        Iterates through all configured backtests and symbols,
        executing each combination.
        """
        default_backtests = config.get("scheduled_backtests.default_backtests", default=[])
        symbols = config.get("scheduled_backtests.apply_to_symbols", default=[])

        logger.info(
            f"[SCHEDULER] Starting scheduled backtest run: "
            f"{len(default_backtests)} backtests × {len(symbols)} symbols = "
            f"{len(default_backtests) * len(symbols)} total executions"
        )

        start_time = datetime.now()
        success_count = 0
        error_count = 0

        for backtest_config in default_backtests:
            for symbol in symbols:
                try:
                    await self._execute_backtest(symbol, backtest_config)
                    success_count += 1
                except Exception as exc:
                    logger.error(
                        f"[SCHEDULER] Failed backtest {backtest_config['name']} for {symbol}: {exc}",
                        exc_info=True
                    )
                    error_count += 1

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"[SCHEDULER] Completed scheduled backtest run: "
            f"{success_count} succeeded, {error_count} failed, "
            f"elapsed {elapsed:.1f}s"
        )

    async def _execute_backtest(self, symbol: str, backtest_config: dict):
        """Execute a single backtest.

        Args:
            symbol: Stock symbol to backtest
            backtest_config: Backtest configuration dict from config.json

        This method invokes the graph workflow in backtest mode
        with the configured prompt and parameters.
        """
        try:
            # Lazy import to avoid circular dependencies
            from src.server.graph import build_graph
            from src.server.state import make_initial_state

            # Substitute symbol in prompt
            prompt = backtest_config['prompt'].replace('{symbol}', symbol)

            # Create unique thread ID for this scheduled backtest run
            thread_id = (
                f"scheduled_{backtest_config['name']}_{symbol}_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )

            # Create initial state for backtest workflow
            initial_state = make_initial_state(
                query=prompt,
                thread_id=thread_id,
                backtest_mode=True
            )

            # Build and run graph (bypass HITL in scheduled mode)
            graph = build_graph()
            result = await graph.ainvoke(initial_state)

            tasks_executed = result.get('tasks_executed', 0)

            logger.info(
                f"[SCHEDULER] ✓ Completed: {backtest_config['name']} for {symbol} "
                f"(thread: {thread_id}, tasks: {tasks_executed})"
            )

            # Send notification on scheduled backtest completion
            try:
                await notify_backtest_completed(
                    backtest_id=thread_id,
                    strategy=backtest_config.get('strategy', 'unknown'),
                    symbol=symbol,
                    timeframe=backtest_config.get('timeframe', 'unknown'),
                    sharpe_ratio=None,  # Not available from graph result
                    total_return=None,
                    max_drawdown=None
                )
            except Exception as notify_exc:
                logger.warning(f"Failed to send scheduled backtest notification: {notify_exc}")

        except Exception as exc:
            logger.error(
                f"[SCHEDULER] ✗ Failed: {backtest_config['name']} for {symbol}: {exc}",
                exc_info=True
            )

            # Send notification on scheduled backtest failure
            try:
                await notify_backtest_failed(
                    backtest_id=thread_id if 'thread_id' in locals() else "unknown",
                    strategy=backtest_config.get('strategy', 'unknown'),
                    symbol=symbol,
                    timeframe=backtest_config.get('timeframe', 'unknown'),
                    error_message=str(exc)
                )
            except Exception as notify_exc:
                logger.warning(f"Failed to send scheduled backtest failure notification: {notify_exc}")

            raise


# Global singleton instance
backtest_scheduler = BacktestScheduler()


if __name__ == "__main__":
    """Test scheduler instantiation."""
    print("=" * 60)
    print("BacktestScheduler Smoke Test")
    print("=" * 60)

    # Test 1: Scheduler instantiation
    scheduler = BacktestScheduler()
    assert scheduler is not None, "Scheduler should instantiate"
    print("  [OK] Scheduler instantiated")

    # Test 2: Config loading
    assert hasattr(scheduler, 'enabled'), "Should have enabled attribute"
    assert hasattr(scheduler, 'schedule'), "Should have schedule attribute"
    print(f"  [OK] Config loaded: enabled={scheduler.enabled}, schedule={scheduler.schedule}")

    # Test 3: Start/stop (don't actually start if disabled)
    if scheduler.enabled:
        print("  [SKIP] Scheduler enabled - skipping start/stop test")
    else:
        print("  [OK] Scheduler disabled - no action needed")

    print("\n" + "=" * 60)
    print("BacktestScheduler Smoke Test Passed")
    print("=" * 60)
