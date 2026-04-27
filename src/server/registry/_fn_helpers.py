"""Shared utilities for all registry function sub-modules.

Provides:
  - Retry decorator with exponential backoff
  - Bar-fetch helpers (live and date-range)
  - Output validation helper (_out)
  - Timeframe normalisation
  - Re-exports: _to_native, _df_to_records
"""

import sys
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.common.utils import get_logger
from src.common.utils.converters import _to_native, df_to_records as _df_to_records  # noqa: F401

logger = get_logger(__name__)

# ── Timeframe normalisation ────────────────────────────────────────────────────

# Aliases LLM commonly emits → canonical values accepted by AlpacaDAO
_TIMEFRAME_ALIASES: Dict[str, str] = {
    "1d": "1Day", "1day": "1Day", "day": "1Day", "daily": "1Day",
    "1h": "1Hour", "1hour": "1Hour", "hour": "1Hour", "hourly": "1Hour",
    "1m": "1Min", "1min": "1Min", "minute": "1Min",
}
_VALID_TIMEFRAMES = {"1Min", "1Hour", "1Day"}


def _normalize_timeframe(tf: str, default: str = "1Min") -> str:
    """Normalise LLM timeframe strings to AlpacaDAO canonical form.

    Args:
        tf: Raw timeframe string from LLM (e.g. "1d", "1Day", "daily").
        default: Returned when tf is None or unrecognised.

    Returns:
        Canonical timeframe string accepted by AlpacaDAO.
    """
    if not tf:
        return default
    canonical = _TIMEFRAME_ALIASES.get(tf.lower(), tf)
    return canonical if canonical in _VALID_TIMEFRAMES else default


# ── Bar fetching ───────────────────────────────────────────────────────────────


def _fetch_bars_for_symbol(symbol: str, timeframe: str = "1Min", lookback_days: int = 90):
    """Fetch OHLCV bars from AlpacaDAO for a symbol.

    Args:
        symbol: Stock ticker.
        timeframe: Bar timeframe string e.g. "1Day", "1Min".
        lookback_days: How many calendar days to look back.

    Returns:
        pandas DataFrame or None on failure.
    """
    try:
        from src.common.utils.container import get_alpaca_dao
        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        df = get_alpaca_dao().get_bars(symbol, start=start, end=end, timeframe=timeframe)
        if df is None or df.empty:
            logger.warning(f"[registry] no bars found for {symbol}/{timeframe}")
            return None
        return df
    except Exception as exc:
        logger.warning(f"[registry] bar fetch failed for {symbol}: {exc}")
        return None


def _fetch_bars_range(
    skill_name: str,
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str,
):
    """Fetch bars from AlpacaDAO for an explicit date range.

    Args:
        skill_name: Caller label for logging.
        symbol: Stock ticker.
        start_date: Start date string "YYYY-MM-DD".
        end_date: End date string "YYYY-MM-DD".
        timeframe: AlpacaDAO canonical timeframe string.

    Returns:
        pandas DataFrame or None on failure.
    """
    try:
        from datetime import datetime as _dt
        from src.common.utils.container import get_alpaca_dao
        df = get_alpaca_dao().get_bars(
            symbol,
            _dt.fromisoformat(start_date),
            _dt.fromisoformat(end_date),
            timeframe,
        )
        if df is None or df.empty:
            logger.warning(f"[{skill_name}] no bars for {symbol}/{timeframe} {start_date}–{end_date}")
            return None
        return df
    except Exception as exc:
        logger.warning(f"[{skill_name}] bar fetch failed for {symbol}: {exc}")
        return None


# ── Output validation ──────────────────────────────────────────────────────────


def _out(model_cls: Any, raw: Dict) -> Dict:
    """Validate a raw skill result through its Pydantic output model.

    All output models use ``extra="allow"`` so extra fields pass through
    unchanged.  On unexpected validation failure the raw dict is returned
    as-is so the executor is never blocked.

    Args:
        model_cls: A Pydantic BaseModel subclass with ``extra="allow"``.
        raw: Raw dict returned by a skill function.

    Returns:
        Validated and coerced dict (defaults filled, types coerced).
    """
    try:
        return model_cls.model_validate(raw).model_dump()
    except Exception as exc:
        logger.debug(f"[registry._out] output validation skipped ({model_cls.__name__}): {exc}")
        return raw


# ── Retry decorator ────────────────────────────────────────────────────────────


def retry_on_transient_error(max_retries: int = 3, backoff_factor: int = 2, timeout_seconds: int = 30):
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

    Example:
        @retry_on_transient_error(max_retries=3)
        def fetch_data_from_api():
            return requests.get(url, timeout=10).json()
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

                    if attempt == max_retries or not is_retryable:
                        logger.warning(
                            f"[retry] {func.__name__} failed after {attempt} attempts: {exc}"
                        )
                        raise

                    if elapsed > timeout_seconds:
                        logger.warning(
                            f"[retry] {func.__name__} timeout after {elapsed:.1f}s (limit: {timeout_seconds}s)"
                        )
                        raise

                    wait_time = backoff_factor ** attempt
                    logger.warning(
                        f"[retry] {func.__name__} attempt {attempt + 1}/{max_retries} failed: {exc}. "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)

            raise last_exception if last_exception else RuntimeError("Retry logic error")

        return wrapper
    return decorator
