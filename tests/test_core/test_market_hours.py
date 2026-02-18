"""Unit tests for Market Hours utilities.

Tests market hours checking, decorators, and enforcement.
Run with: pytest tests/test_core/test_market_hours.py -v
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from datetime import datetime, time
import pytz
from src.core.market_hours import (
    is_market_open,
    is_weekend,
    get_market_hours,
    get_next_market_open,
    require_market_hours,
    MarketHoursError,
    get_market_status,
)


class TestMarketHours:
    """Test suite for market hours utilities."""

    def test_get_market_hours(self):
        """Test getting market hours from config."""
        open_time, close_time = get_market_hours()

        assert isinstance(open_time, time)
        assert isinstance(close_time, time)
        assert open_time == time(9, 30)
        assert close_time == time(16, 0)

    def test_is_market_open_during_hours(self):
        """Test market is open during trading hours."""
        # Monday at 10:00 AM ET
        tz = pytz.timezone("America/New_York")
        test_time = tz.localize(datetime(2024, 2, 19, 10, 0))  # Monday

        result = is_market_open(check_time=test_time)
        assert result is True

    def test_is_market_open_before_open(self):
        """Test market is closed before opening."""
        # Monday at 8:00 AM ET (before 9:30 AM open)
        tz = pytz.timezone("America/New_York")
        test_time = tz.localize(datetime(2024, 2, 19, 8, 0))

        result = is_market_open(check_time=test_time)
        assert result is False

    def test_is_market_open_after_close(self):
        """Test market is closed after closing."""
        # Monday at 5:00 PM ET (after 4:00 PM close)
        tz = pytz.timezone("America/New_York")
        test_time = tz.localize(datetime(2024, 2, 19, 17, 0))

        result = is_market_open(check_time=test_time)
        assert result is False

    def test_is_market_open_on_weekend(self):
        """Test market is closed on weekends."""
        # Saturday at 10:00 AM ET
        tz = pytz.timezone("America/New_York")
        test_time = tz.localize(datetime(2024, 2, 17, 10, 0))  # Saturday

        result = is_market_open(check_time=test_time)
        assert result is False

    def test_is_market_open_weekend_check_disabled(self):
        """Test weekend check can be disabled."""
        # Saturday at 10:00 AM ET (during market hours, but weekend)
        tz = pytz.timezone("America/New_York")
        test_time = tz.localize(datetime(2024, 2, 17, 10, 0))

        # With weekend check
        assert is_market_open(check_time=test_time, check_weekends=True) is False

        # Without weekend check (only checks time)
        assert is_market_open(check_time=test_time, check_weekends=False) is True

    def test_is_weekend(self):
        """Test weekend detection."""
        tz = pytz.timezone("America/New_York")

        # Monday - not weekend
        monday = tz.localize(datetime(2024, 2, 19, 10, 0))
        assert is_weekend(check_time=monday) is False

        # Friday - not weekend
        friday = tz.localize(datetime(2024, 2, 23, 10, 0))
        assert is_weekend(check_time=friday) is False

        # Saturday - weekend
        saturday = tz.localize(datetime(2024, 2, 17, 10, 0))
        assert is_weekend(check_time=saturday) is True

        # Sunday - weekend
        sunday = tz.localize(datetime(2024, 2, 18, 10, 0))
        assert is_weekend(check_time=sunday) is True

    def test_get_next_market_open(self):
        """Test getting next market open."""
        # Just verify it returns a valid datetime
        next_open = get_next_market_open()

        assert isinstance(next_open, datetime)
        assert next_open.tzinfo is not None
        # Next open should have market open time
        assert next_open.time() == time(9, 30)

    def test_get_market_status(self):
        """Test getting comprehensive market status."""
        status = get_market_status()

        assert "is_open" in status
        assert "is_weekend" in status
        assert "current_time" in status
        assert "market_open" in status
        assert "market_close" in status
        assert "next_open" in status
        assert "timezone" in status

        assert isinstance(status["is_open"], bool)
        assert isinstance(status["is_weekend"], bool)
        assert isinstance(status["current_time"], datetime)
        assert isinstance(status["market_open"], time)
        assert isinstance(status["market_close"], time)
        assert isinstance(status["next_open"], datetime)

    def test_require_market_hours_decorator_during_hours(self):
        """Test decorator allows execution during market hours."""
        # Monday at 10:00 AM ET
        tz = pytz.timezone("America/New_York")
        test_time = tz.localize(datetime(2024, 2, 19, 10, 0))

        # Mock is_market_open to return True
        import src.core.market_hours as mh
        original_is_open = mh.is_market_open
        mh.is_market_open = lambda **kwargs: True

        @require_market_hours()
        def test_function():
            return "executed"

        result = test_function()
        assert result == "executed"

        # Restore
        mh.is_market_open = original_is_open

    def test_require_market_hours_decorator_raises_error(self):
        """Test decorator raises error when market closed."""
        # Mock is_market_open to return False
        import src.core.market_hours as mh
        original_is_open = mh.is_market_open
        mh.is_market_open = lambda **kwargs: False

        @require_market_hours(raise_error=True)
        def test_function():
            return "executed"

        with pytest.raises(MarketHoursError, match="Market is closed"):
            test_function()

        # Restore
        mh.is_market_open = original_is_open

    def test_require_market_hours_decorator_returns_none(self):
        """Test decorator returns None when market closed and raise_error=False."""
        # Mock is_market_open to return False
        import src.core.market_hours as mh
        original_is_open = mh.is_market_open
        mh.is_market_open = lambda **kwargs: False

        @require_market_hours(raise_error=False)
        def test_function():
            return "executed"

        result = test_function()
        assert result is None

        # Restore
        mh.is_market_open = original_is_open


if __name__ == "__main__":
    """Run tests with pytest."""
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
