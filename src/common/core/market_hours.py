"""Market hours utilities and decorators.

This module provides utilities to check if the market is open and decorators
to ensure functions only run during market hours. Useful for critical agents
that should refuse to operate outside trading hours.

Usage:
    from src.common.core.market_hours import require_market_hours, is_market_open

    @require_market_hours
    def execute_trade(symbol, quantity):
        # This will only run during market hours
        pass

    # Manual check
    if is_market_open():
        print("Market is open!")
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import functools
from datetime import datetime, time
from typing import Callable, Optional
import pytz
from src.common.utils import config, get_logger


logger = get_logger(__name__)


class MarketHoursError(Exception):
    """Raised when attempting to execute market operations outside trading hours."""
    pass


def get_market_timezone() -> pytz.timezone:
    """Get the market timezone from config.

    Returns:
        pytz.timezone: Market timezone (default: America/New_York)
    """
    tz_name = config.get("market_hours.timezone", default="America/New_York")
    return pytz.timezone(tz_name)


def get_market_hours() -> tuple[time, time]:
    """Get market open and close times from config.

    Returns:
        tuple[time, time]: (market_open, market_close) as time objects

    Example:
        >>> open_time, close_time = get_market_hours()
        >>> print(f"Market: {open_time} - {close_time}")
        Market: 09:30:00 - 16:00:00
    """
    open_str = config.get("market_hours.open", default="09:30")
    close_str = config.get("market_hours.close", default="16:00")

    # Parse time strings (format: "HH:MM")
    open_hour, open_min = map(int, open_str.split(":"))
    close_hour, close_min = map(int, close_str.split(":"))

    market_open = time(open_hour, open_min)
    market_close = time(close_hour, close_min)

    return market_open, market_close


def is_market_open(
    check_time: Optional[datetime] = None,
    check_weekends: bool = True
) -> bool:
    """Check if the market is currently open.

    Args:
        check_time: Time to check (default: current time)
        check_weekends: If True, returns False on weekends

    Returns:
        bool: True if market is open, False otherwise

    Example:
        >>> is_market_open()
        True
        >>> is_market_open(check_time=datetime(2024, 1, 1, 10, 0))  # Monday 10 AM
        True
    """
    if check_time is None:
        check_time = datetime.now(get_market_timezone())
    elif check_time.tzinfo is None:
        # If naive datetime, assume it's in market timezone
        check_time = get_market_timezone().localize(check_time)
    else:
        # Convert to market timezone
        check_time = check_time.astimezone(get_market_timezone())

    # Check if weekend (Saturday=5, Sunday=6)
    if check_weekends and check_time.weekday() >= 5:
        return False

    # Get market hours
    market_open, market_close = get_market_hours()

    # Check if current time is within market hours
    current_time = check_time.time()
    return market_open <= current_time < market_close


def is_weekend(check_time: Optional[datetime] = None) -> bool:
    """Check if given time is on a weekend.

    Args:
        check_time: Time to check (default: current time)

    Returns:
        bool: True if weekend (Saturday or Sunday)
    """
    if check_time is None:
        check_time = datetime.now(get_market_timezone())
    elif check_time.tzinfo is None:
        check_time = get_market_timezone().localize(check_time)
    else:
        check_time = check_time.astimezone(get_market_timezone())

    return check_time.weekday() >= 5


def get_next_market_open() -> datetime:
    """Get the next market open datetime.

    Returns:
        datetime: Next market open time

    Example:
        >>> next_open = get_next_market_open()
        >>> print(f"Next market open: {next_open}")
        Next market open: 2024-02-19 09:30:00-05:00
    """
    tz = get_market_timezone()
    now = datetime.now(tz)
    market_open, _ = get_market_hours()

    # Start with today
    next_open = now.replace(
        hour=market_open.hour,
        minute=market_open.minute,
        second=0,
        microsecond=0
    )

    # If market already opened today, or it's after hours, go to next day
    if now.time() >= market_open or is_weekend(now):
        from datetime import timedelta
        next_open += timedelta(days=1)

        # Skip weekends
        while next_open.weekday() >= 5:
            next_open += timedelta(days=1)

    return next_open


def require_market_hours(
    raise_error: bool = True,
    allow_weekends: bool = False
) -> Callable:
    """Decorator to ensure function only runs during market hours.

    Args:
        raise_error: If True, raises MarketHoursError. If False, returns None.
        allow_weekends: If True, allows execution on weekends

    Returns:
        Callable: Decorated function

    Raises:
        MarketHoursError: If market is closed and raise_error=True

    Example:
        >>> @require_market_hours()
        >>> def execute_trade(symbol, quantity):
        ...     print(f"Trading {quantity} shares of {symbol}")
        >>>
        >>> execute_trade("AAPL", 100)  # Only runs during market hours
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Check if market is open
            if not is_market_open(check_weekends=not allow_weekends):
                tz = get_market_timezone()
                now = datetime.now(tz)
                next_open = get_next_market_open()

                error_msg = (
                    f"Market is closed. Current time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}. "
                    f"Next open: {next_open.strftime('%Y-%m-%d %H:%M:%S %Z')}"
                )

                if raise_error:
                    logger.error(f"Function '{func.__name__}' blocked: {error_msg}")
                    raise MarketHoursError(error_msg)
                else:
                    logger.warning(
                        f"Function '{func.__name__}' skipped: {error_msg}"
                    )
                    return None

            # Market is open, execute function
            return func(*args, **kwargs)

        return wrapper
    return decorator


def get_market_status() -> dict:
    """Get detailed market status information.

    Returns:
        dict: Market status with keys:
            - is_open: bool
            - is_weekend: bool
            - current_time: datetime
            - market_open: time
            - market_close: time
            - next_open: datetime
            - timezone: str

    Example:
        >>> status = get_market_status()
        >>> print(status)
        {
            'is_open': True,
            'is_weekend': False,
            'current_time': datetime(2024, 2, 19, 10, 30),
            ...
        }
    """
    tz = get_market_timezone()
    now = datetime.now(tz)
    market_open, market_close = get_market_hours()

    return {
        "is_open": is_market_open(),
        "is_weekend": is_weekend(),
        "current_time": now,
        "market_open": market_open,
        "market_close": market_close,
        "next_open": get_next_market_open(),
        "timezone": str(tz)
    }


if __name__ == "__main__":
    """Test market hours utilities."""
    # Test market status
    status = get_market_status()
    print("Current Market Status:")
    print(f"  Is Open: {status['is_open']}")
    print(f"  Is Weekend: {status['is_weekend']}")
    print(f"  Current Time: {status['current_time'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  Market Hours: {status['market_open']} - {status['market_close']}")
    print(f"  Next Open: {status['next_open'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  Timezone: {status['timezone']}")

    # Test decorator
    @require_market_hours(raise_error=False)
    def test_function():
        return "Function executed!"

    print("\nTesting decorator:")
    result = test_function()
    if result:
        print(f"  ✓ {result}")
    else:
        print(f"  ✗ Function blocked (market closed)")

    # Test with error
    @require_market_hours(raise_error=True)
    def strict_function():
        return "This requires market hours!"

    print("\nTesting strict decorator:")
    try:
        result = strict_function()
        print(f"  ✓ {result}")
    except MarketHoursError as e:
        print(f"  ✗ Blocked: {e}")

    print("\n✓ Market hours test complete")
