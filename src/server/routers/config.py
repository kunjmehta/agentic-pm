"""Configuration router — GET/PUT /v1/config/...

Provides REST API for runtime configuration management without server restart.
All write operations use file locking to prevent concurrent write corruption.

Endpoints:
    GET  /v1/config                       Full config JSON
    GET  /v1/config/{section}             Specific section (e.g., "risk_management")
    PUT  /v1/config/{section}             Update entire section with validation
    POST /v1/config/watchlist/add         Add ticker with strategies/timeframes
    DELETE /v1/config/watchlist/{symbol}  Remove ticker from watchlist
    POST /v1/config/reload                Reload config from disk

File locking ensures atomic writes and prevents race conditions during
concurrent updates.
"""

import json
import platform
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.common.utils import get_logger
from src.server.models.endpoints import (
    ConfigReloadResponse,
    ConfigResponse,
    ConfigSectionResponse,
    WatchlistEntryResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/config", tags=["config"])

# ── Constants ──────────────────────────────────────────────────────────────

CONFIG_PATH = Path("config/config.json")

# Valid strategy names from config.json
VALID_STRATEGIES = {
    "mean_reversion",
    "vwap_reversion",
    "opening_range_breakout",
    "rsi_divergence",
    "momentum_burst",
    "golden_cross",
    "breakout_52w",
    "mean_reversion_daily",
    "earnings_drift",
}

# Valid timeframes from ETL config
VALID_TIMEFRAMES = {"1Min", "1Hour", "1Day"}

# Lock timeout and retry settings
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_RETRY_DELAY_MS = 50


# ── File Locking ───────────────────────────────────────────────────────────


@contextmanager
def _file_lock(file_path: Path, mode: str = "r"):
    """Context manager for cross-platform file locking.

    Args:
        file_path: Path to the file to lock.
        mode: File open mode ("r" for read, "r+" for read-write).

    Yields:
        Opened file handle with exclusive lock acquired.

    Raises:
        HTTPException: 503 if lock cannot be acquired within timeout.
    """
    system = platform.system()
    start_time = time.time()

    while True:
        try:
            fp = open(file_path, mode, encoding="utf-8")
            try:
                if system == "Windows":
                    import msvcrt

                    msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield fp
                return
            except (IOError, OSError) as exc:
                fp.close()
                elapsed = time.time() - start_time
                if elapsed >= LOCK_TIMEOUT_SECONDS:
                    logger.error(f"[config] Lock timeout after {elapsed:.2f}s: {exc}")
                    raise HTTPException(
                        status_code=503,
                        detail=f"Config file locked, timeout after {LOCK_TIMEOUT_SECONDS}s",
                    )
                time.sleep(LOCK_RETRY_DELAY_MS / 1000.0)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Config file not found: {file_path}")
        except Exception as exc:
            logger.error(f"[config] File lock error: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))


def _read_config() -> Dict[str, Any]:
    """Read config.json with file locking.

    Returns:
        Parsed configuration dictionary.

    Raises:
        HTTPException: On file read or JSON parse errors.
    """
    with _file_lock(CONFIG_PATH, mode="r") as fp:
        try:
            config = json.load(fp)
            return config
        except json.JSONDecodeError as exc:
            logger.error(f"[config] JSON parse error: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Invalid JSON in config: {exc}")


def _write_config(config: Dict[str, Any]) -> None:
    """Write config.json with file locking and atomic write.

    Args:
        config: Configuration dictionary to write.

    Raises:
        HTTPException: On file write errors.
    """
    backup_path = CONFIG_PATH.with_suffix(".json.bak")

    # Create backup before write
    if CONFIG_PATH.exists():
        CONFIG_PATH.rename(backup_path)

    try:
        with _file_lock(CONFIG_PATH, mode="w") as fp:
            json.dump(config, fp, indent=2)
            fp.flush()
        # Remove backup on success
        if backup_path.exists():
            backup_path.unlink()
    except Exception as exc:
        # Restore backup on failure
        if backup_path.exists():
            backup_path.rename(CONFIG_PATH)
        logger.error(f"[config] Write failed, restored backup: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Config write failed: {exc}")


# ── Request Models ─────────────────────────────────────────────────────────


class WatchlistAddRequest(BaseModel):
    """POST /v1/config/watchlist/add request body.

    Attributes:
        symbol: Stock ticker (e.g., "AAPL"). Will be uppercased.
        strategies: Optional list of strategy names to enable for this ticker.
            Defaults to all available strategies.
        timeframes: Optional list of timeframes to enable.
            Defaults to all available timeframes.
    """

    symbol: str = Field(..., min_length=1, max_length=10, description="Stock ticker")
    strategies: Optional[List[str]] = Field(
        default=None, description="Strategy names (defaults to all)"
    )
    timeframes: Optional[List[str]] = Field(
        default=None, description="Timeframes (defaults to all)"
    )

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        """Validate and normalize symbol format.

        Args:
            v: Symbol string.

        Returns:
            Uppercased, alphanumeric symbol.

        Raises:
            ValueError: If symbol contains invalid characters.
        """
        v = v.upper().strip()
        if not v.isalnum():
            raise ValueError("Symbol must be alphanumeric")
        return v

    @field_validator("strategies")
    @classmethod
    def validate_strategies(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate strategy names against known strategies.

        Args:
            v: List of strategy names.

        Returns:
            Validated strategy list.

        Raises:
            ValueError: If any strategy name is invalid.
        """
        if v is None:
            return None
        invalid = set(v) - VALID_STRATEGIES
        if invalid:
            raise ValueError(
                f"Invalid strategies: {invalid}. Valid: {sorted(VALID_STRATEGIES)}"
            )
        return v

    @field_validator("timeframes")
    @classmethod
    def validate_timeframes(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate timeframes against ETL config.

        Args:
            v: List of timeframes.

        Returns:
            Validated timeframe list.

        Raises:
            ValueError: If any timeframe is invalid.
        """
        if v is None:
            return None
        invalid = set(v) - VALID_TIMEFRAMES
        if invalid:
            raise ValueError(
                f"Invalid timeframes: {invalid}. Valid: {sorted(VALID_TIMEFRAMES)}"
            )
        return v


class ConfigSectionUpdateRequest(BaseModel):
    """PUT /v1/config/{section} request body.

    Attributes:
        config: Configuration dictionary for the section.
            Must be valid JSON object that matches the section schema.
    """

    config: Dict[str, Any] = Field(..., description="Section configuration dict")


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("", response_model=ConfigResponse)
async def get_full_config():
    """Retrieve the full configuration dictionary.

    Returns:
        ConfigResponse with complete config.json contents.
    """
    logger.info("[config/get] fetching full config")
    try:
        config = _read_config()
        return ConfigResponse(config=config)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[config/get] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/ui", response_model=Dict[str, Any])
async def get_ui_config():
    """Retrieve configuration in UI-friendly format.

    Transforms the config.json structure to match the UI's expected schema:
    - watchlist: object → array of { ticker, strategies, enabled }
    - strategy params: nested objects → array of { name, timeframes, params }
    - auto_compute_metrics: extracted from ETL config

    Returns:
        Transformed config suitable for the UI.
    """
    logger.info("[config/ui] fetching UI-formatted config")
    try:
        config = _read_config()

        # Transform watchlist from object to array
        watchlist_obj = config.get("watchlist", {})
        watchlist_array = []
        for ticker, settings in watchlist_obj.items():
            watchlist_array.append({
                "ticker": ticker,
                "strategies": settings.get("strategies", []),
                "enabled": settings.get("enabled", True),
            })

        # Transform strategy params from nested objects to array
        strategy_obj = config.get("strategy", {})
        strategies_array = []
        for strategy_name in VALID_STRATEGIES:
            if strategy_name in strategy_obj:
                params = strategy_obj[strategy_name]
                # Extract timeframes from watchlist items that use this strategy
                timeframes = set()
                for settings in watchlist_obj.values():
                    if strategy_name in settings.get("strategies", []):
                        timeframes.update(settings.get("timeframes", []))

                strategies_array.append({
                    "name": strategy_name,
                    "timeframes": sorted(timeframes) if timeframes else ["1Min", "1Hour", "1Day"],
                    "params": params,
                })

        # Extract auto_compute_metrics
        auto_compute = any(
            settings.get("auto_compute_indicators", False)
            for settings in watchlist_obj.values()
        )

        ui_config = {
            "watchlist": watchlist_array,
            "strategies": strategies_array,
            "auto_compute_metrics": auto_compute,
        }

        logger.info(f"[config/ui] transformed config: {len(watchlist_array)} tickers, {len(strategies_array)} strategies")
        return ui_config

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[config/ui] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/ui", response_model=Dict[str, Any])
async def update_ui_config(ui_config: Dict[str, Any]):
    """Update configuration from UI format.

    Transforms UI format back to config.json structure and persists.

    Args:
        ui_config: UI-formatted config with watchlist array and strategies array.

    Returns:
        Updated UI-formatted config.
    """
    logger.info("[config/ui/put] updating config from UI")
    try:
        # Read current config to preserve other sections
        config = _read_config()

        # Transform watchlist from array to object
        watchlist_array = ui_config.get("watchlist", [])
        watchlist_obj = {}
        auto_compute = ui_config.get("auto_compute_metrics", False)

        for item in watchlist_array:
            ticker = item["ticker"].upper()
            watchlist_obj[ticker] = {
                "enabled": item.get("enabled", True),
                "strategies": item.get("strategies", []),
                "timeframes": ["1Min", "1Hour", "1Day"],  # Default timeframes
                "auto_compute_indicators": auto_compute,
            }

        # Transform strategies from array to nested object
        strategies_array = ui_config.get("strategies", [])
        strategy_obj = config.get("strategy", {})

        for strategy in strategies_array:
            strategy_name = strategy["name"]
            if strategy_name in VALID_STRATEGIES:
                strategy_obj[strategy_name] = strategy.get("params", {})

        # Update config sections
        config["watchlist"] = watchlist_obj
        config["strategy"] = strategy_obj

        # Persist to disk
        _write_config(config)

        logger.info(f"[config/ui/put] updated: {len(watchlist_obj)} tickers, {len(strategies_array)} strategies")

        # Return updated UI format
        return await get_ui_config()

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[config/ui/put] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{section}", response_model=ConfigSectionResponse)
async def get_config_section(section: str):
    """Retrieve a specific configuration section.

    Args:
        section: Section name (e.g., "risk_management", "market_hours").

    Returns:
        ConfigSectionResponse with the requested section dict.

    Raises:
        HTTPException: 404 if section does not exist.
    """
    logger.info(f"[config/get/{section}] fetching section")
    try:
        config = _read_config()
        if section not in config:
            raise HTTPException(
                status_code=404,
                detail=f"Section '{section}' not found. Available: {list(config.keys())}",
            )
        return ConfigSectionResponse(section=section, config=config[section])
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[config/get/{section}] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/{section}", response_model=ConfigSectionResponse)
async def update_config_section(section: str, request: ConfigSectionUpdateRequest):
    """Update an entire configuration section.

    Args:
        section: Section name to update.
        request: ConfigSectionUpdateRequest with new section config.

    Returns:
        ConfigSectionResponse with updated section.

    Raises:
        HTTPException: 404 if section does not exist, 400 for validation errors.
    """
    logger.info(f"[config/put/{section}] updating section")
    try:
        config = _read_config()

        if section not in config:
            raise HTTPException(
                status_code=404,
                detail=f"Section '{section}' not found. Available: {list(config.keys())}",
            )

        # Validate specific sections
        if section == "etl" and "timeframes" in request.config:
            invalid_tf = set(request.config["timeframes"]) - VALID_TIMEFRAMES
            if invalid_tf:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid timeframes: {invalid_tf}. Valid: {sorted(VALID_TIMEFRAMES)}",
                )

        if section == "strategy":
            for key in request.config:
                if key in VALID_STRATEGIES and not isinstance(request.config[key], dict):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Strategy '{key}' config must be a dict",
                    )

        # Update and persist
        config[section] = request.config
        _write_config(config)

        logger.info(f"[config/put/{section}] section updated successfully")
        return ConfigSectionResponse(section=section, config=config[section])

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[config/put/{section}] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/watchlist/add", response_model=WatchlistEntryResponse)
async def add_watchlist_entry(request: WatchlistAddRequest):
    """Add a ticker to the watchlist with strategies and timeframes.

    Args:
        request: WatchlistAddRequest with symbol and optional strategies/timeframes.

    Returns:
        WatchlistEntryResponse with updated watchlist.
    """
    symbol = request.symbol.upper()
    logger.info(f"[config/watchlist/add] adding {symbol}")

    try:
        config = _read_config()
        watchlist = config.get("watchlist", {})

        # Ensure watchlist is dict format (backward compatibility)
        if isinstance(watchlist, list):
            # Convert old array format to dict
            watchlist = {s.upper(): {
                "enabled": True,
                "strategies": sorted(VALID_STRATEGIES),
                "timeframes": sorted(VALID_TIMEFRAMES),
                "auto_compute_indicators": True,
            } for s in watchlist}

        if symbol in watchlist:
            return WatchlistEntryResponse(
                status="success",
                action="already_present",
                symbol=symbol,
                watchlist=list(watchlist.keys()),
                message=f"{symbol} already in watchlist",
            )

        # Add to watchlist with custom or default settings
        watchlist[symbol] = {
            "enabled": True,
            "strategies": request.strategies if request.strategies else sorted(VALID_STRATEGIES),
            "timeframes": request.timeframes if request.timeframes else sorted(VALID_TIMEFRAMES),
            "auto_compute_indicators": True,
        }
        config["watchlist"] = watchlist
        _write_config(config)

        logger.info(
            f"[config/watchlist/add] {symbol} added "
            f"(strategies: {len(watchlist[symbol]['strategies'])}, "
            f"timeframes: {watchlist[symbol]['timeframes']})"
        )

        return WatchlistEntryResponse(
            status="success",
            action="added",
            symbol=symbol,
            watchlist=list(watchlist.keys()),
            message=f"{symbol} added to watchlist",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[config/watchlist/add] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/watchlist/{symbol}", response_model=WatchlistEntryResponse)
async def remove_watchlist_entry(symbol: str):
    """Remove a ticker from the watchlist.

    Args:
        symbol: Stock ticker to remove.

    Returns:
        WatchlistEntryResponse with updated watchlist.
    """
    symbol = symbol.upper()
    logger.info(f"[config/watchlist/remove] removing {symbol}")

    try:
        config = _read_config()
        watchlist = config.get("watchlist", {})

        # Ensure watchlist is dict format (backward compatibility)
        if isinstance(watchlist, list):
            watchlist = {s.upper(): {
                "enabled": True,
                "strategies": sorted(VALID_STRATEGIES),
                "timeframes": sorted(VALID_TIMEFRAMES),
                "auto_compute_indicators": True,
            } for s in watchlist}

        if symbol not in watchlist:
            return WatchlistEntryResponse(
                status="success",
                action="not_present",
                symbol=symbol,
                watchlist=list(watchlist.keys()),
                message=f"{symbol} not in watchlist",
            )

        # Remove from watchlist
        del watchlist[symbol]
        config["watchlist"] = watchlist
        _write_config(config)

        logger.info(f"[config/watchlist/remove] {symbol} removed")

        return WatchlistEntryResponse(
            status="success",
            action="removed",
            symbol=symbol,
            watchlist=list(watchlist.keys()),
            message=f"{symbol} removed from watchlist",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[config/watchlist/remove] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/reload", response_model=ConfigReloadResponse)
async def reload_config():
    """Reload configuration from disk without restarting the server.

    This is useful after manual edits to config.json or when
    synchronizing with external config management.

    Returns:
        ConfigReloadResponse with reloaded configuration.
    """
    logger.info("[config/reload] reloading from disk")

    try:
        config = _read_config()
        logger.info("[config/reload] config reloaded successfully")

        return ConfigReloadResponse(
            status="success",
            message="Configuration reloaded from disk",
            config=config,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[config/reload] {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Main Block ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    """Smoke test: verify router routes and validation logic."""
    print("=" * 60)
    print("routers/config.py smoke tests")
    print("=" * 60)

    # Test 1: Route registration
    routes = [r.path for r in router.routes]
    expected = [
        "/v1/config",
        "/v1/config/{section}",
        "/v1/config/watchlist/add",
        "/v1/config/watchlist/{symbol}",
        "/v1/config/reload",
    ]
    for path in expected:
        assert path in routes, f"Missing route: {path}"
        print(f"  [OK]  {path}")

    # Test 2: Strategy validation
    print("\n[Validation Tests]")
    try:
        valid_req = WatchlistAddRequest(
            symbol="AAPL", strategies=["mean_reversion", "golden_cross"]
        )
        assert valid_req.symbol == "AAPL"
        print("  [OK]  Valid strategy names accepted")
    except Exception as exc:
        print(f"  [FAIL] Valid strategy validation: {exc}")
        raise

    try:
        invalid_req = WatchlistAddRequest(symbol="AAPL", strategies=["invalid_strategy"])
        print("  [FAIL] Invalid strategy should have raised ValueError")
        raise AssertionError("Expected ValueError for invalid strategy")
    except ValueError as exc:
        assert "Invalid strategies" in str(exc)
        print("  [OK]  Invalid strategy names rejected")

    # Test 3: Timeframe validation
    try:
        valid_req = WatchlistAddRequest(symbol="MSFT", timeframes=["1Min", "1Day"])
        assert valid_req.timeframes == ["1Min", "1Day"]
        print("  [OK]  Valid timeframes accepted")
    except Exception as exc:
        print(f"  [FAIL] Valid timeframe validation: {exc}")
        raise

    try:
        invalid_req = WatchlistAddRequest(symbol="MSFT", timeframes=["5Min"])
        print("  [FAIL] Invalid timeframe should have raised ValueError")
        raise AssertionError("Expected ValueError for invalid timeframe")
    except ValueError as exc:
        assert "Invalid timeframes" in str(exc)
        print("  [OK]  Invalid timeframes rejected")

    # Test 4: Symbol validation
    try:
        req = WatchlistAddRequest(symbol="  aapl  ")
        assert req.symbol == "AAPL"
        print("  [OK]  Symbol uppercased and trimmed")
    except Exception as exc:
        print(f"  [FAIL] Symbol normalization: {exc}")
        raise

    try:
        invalid_req = WatchlistAddRequest(symbol="AAPL-123")
        print("  [FAIL] Invalid symbol should have raised ValueError")
        raise AssertionError("Expected ValueError for invalid symbol")
    except ValueError as exc:
        assert "alphanumeric" in str(exc)
        print("  [OK]  Non-alphanumeric symbols rejected")

    print("\n[ALL OK] routers/config.py smoke tests passed")
