"""Shared utilities for quant skill modules.

Provides the ``_fetch_bars`` helper used by all strategy skill classes.
"""

import sys
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)


def retry_on_transient_error(max_retries=3, backoff_factor=2, timeout_seconds=30):
    """Retry decorator for transient API failures with exponential backoff.

    Handles common transient errors:
    - Network timeouts (requests.exceptions.Timeout, httpx.TimeoutException)
    - HTTP 429 Rate Limit Exceeded
    - HTTP 5xx Server Errors
    - Connection errors

    Args:
        max_retries: Maximum number of retry attempts. Default 3.
        backoff_factor: Exponential backoff multiplier. Default 2 (1s, 2s, 4s).
        timeout_seconds: Max time to wait for retries. Default 30s.

    Returns:
        Decorated function with retry logic.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            last_exception = None

            for attempt in range(max_retries + 1):  # +1 for initial attempt
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    elapsed = time.time() - start_time

                    # Check if error is retryable
                    is_timeout = any([
                        "timeout" in str(exc).lower(),
                        "timed out" in str(exc).lower(),
                        exc.__class__.__name__ in ("Timeout", "TimeoutException", "ReadTimeout"),
                    ])
                    is_rate_limit = "429" in str(exc) or "rate limit" in str(exc).lower()
                    is_server_error = any(
                        f"{code}" in str(exc) for code in (500, 502, 503, 504)
                    )
                    is_connection_error = any([
                        "connection" in str(exc).lower(),
                        "network" in str(exc).lower(),
                        exc.__class__.__name__ in ("ConnectionError", "ConnectionResetError"),
                    ])

                    is_retryable = is_timeout or is_rate_limit or is_server_error or is_connection_error

                    # Don't retry on last attempt or non-retryable errors
                    if attempt == max_retries or not is_retryable:
                        logger.warning(
                            f"[retry] {func.__name__} failed after {attempt} attempts: {exc}"
                        )
                        raise

                    # Check timeout
                    if elapsed > timeout_seconds:
                        logger.warning(
                            f"[retry] {func.__name__} timeout after {elapsed:.1f}s (limit: {timeout_seconds}s)"
                        )
                        raise

                    # Exponential backoff
                    wait_time = backoff_factor ** attempt
                    logger.warning(
                        f"[retry] {func.__name__} attempt {attempt + 1}/{max_retries} failed: {exc}. "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)

            # Should never reach here, but just in case
            raise last_exception if last_exception else RuntimeError("Retry logic error")

        return wrapper
    return decorator


@retry_on_transient_error(max_retries=3, backoff_factor=2)
def _fetch_bars(
    symbol: str,
    timeframe: str = "1Day",
    lookback_days: int = 90,
) -> Optional[pd.DataFrame]:
    """Fetch OHLCV bars from AlpacaDAO.

    Args:
        symbol: Stock ticker.
        timeframe: AlpacaDAO canonical timeframe (e.g. ``"1Day"``, ``"1Min"``).
        lookback_days: Calendar days to look back from now.

    Returns:
        DataFrame or ``None`` if unavailable.
    """
    try:
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        df = dao.get_bars(symbol, start=start, end=end, timeframe=timeframe)
        dao.close()
        if df is None or df.empty:
            logger.warning("[quant._utils] No bars for %s/%s", symbol, timeframe)
            return None
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("[quant._utils] Bar fetch failed for %s: %s", symbol, exc)
        return None
