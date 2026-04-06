"""Generic configuration loader for config.json and secret.json.

This module provides a centralized way to load and access application
configuration and secrets. It uses singleton pattern to ensure configs
are loaded only once.

Usage:
    from src.common.utils.config_loader import config, secrets

    # Access config values
    watchlist = config.get("watchlist")
    max_trades = config.get("risk_management.max_daily_trades")

    # Access secrets
    alpaca_key = secrets.get("alpaca.api_key")

    # With defaults
    feed = config.get("data_feed", default="iex")
"""

import json
import platform
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# ── Constants ──────────────────────────────────────────────────────────────

# Valid strategy names (must match config.json strategy section keys)
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

# Valid timeframes (must match ETL config)
VALID_TIMEFRAMES = {"1Min", "1Hour", "1Day"}

# Lock timeout and retry settings for file writes
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_RETRY_DELAY_MS = 50


# ── File Locking Utilities ─────────────────────────────────────────────────


@contextmanager
def _file_lock(file_path: Path, mode: str = "r"):
    """Context manager for cross-platform file locking.

    Args:
        file_path: Path to the file to lock.
        mode: File open mode ("r" for read, "w" for write, "r+" for read-write).

    Yields:
        Opened file handle with exclusive lock acquired.

    Raises:
        TimeoutError: If lock cannot be acquired within timeout.
        FileNotFoundError: If file doesn't exist and mode is read.
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
            except (IOError, OSError):
                fp.close()
                elapsed = time.time() - start_time
                if elapsed >= LOCK_TIMEOUT_SECONDS:
                    raise TimeoutError(
                        f"Config file locked, timeout after {LOCK_TIMEOUT_SECONDS}s"
                    )
                time.sleep(LOCK_RETRY_DELAY_MS / 1000.0)
        except FileNotFoundError:
            if mode in ("r", "r+"):
                raise
            # For write mode, create parent dirs if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            fp = open(file_path, mode, encoding="utf-8")
            yield fp
            return


# ── Backward Compatibility Utilities ───────────────────────────────────────


def normalize_watchlist(watchlist: Union[List[str], Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize watchlist to dict format with backward compatibility.

    Supports both old array format and new dict format:
    - Old: ["AAPL", "TSLA"] → converts to dict with default strategies
    - New: {"AAPL": {...}, "TSLA": {...}} → returns as-is

    Args:
        watchlist: Watchlist in either array or dict format.

    Returns:
        Watchlist in dict format with symbol → config mapping.

    Example:
        >>> normalize_watchlist(["AAPL", "TSLA"])
        {
            "AAPL": {
                "enabled": True,
                "strategies": ["mean_reversion", ...],
                "timeframes": ["1Min", "1Hour", "1Day"],
                "auto_compute_indicators": True
            },
            "TSLA": {...}
        }
    """
    if isinstance(watchlist, list):
        # Old array format - convert to dict with all strategies enabled
        return {
            symbol.upper(): {
                "enabled": True,
                "strategies": sorted(VALID_STRATEGIES),
                "timeframes": sorted(VALID_TIMEFRAMES),
                "auto_compute_indicators": True,
            }
            for symbol in watchlist
        }
    elif isinstance(watchlist, dict):
        # New dict format - validate and return
        normalized = {}
        for symbol, config in watchlist.items():
            if not isinstance(config, dict):
                # Handle malformed entry - treat as enabled symbol with defaults
                normalized[symbol.upper()] = {
                    "enabled": True,
                    "strategies": sorted(VALID_STRATEGIES),
                    "timeframes": sorted(VALID_TIMEFRAMES),
                    "auto_compute_indicators": True,
                }
            else:
                # Ensure all required fields exist
                normalized[symbol.upper()] = {
                    "enabled": config.get("enabled", True),
                    "strategies": config.get("strategies", sorted(VALID_STRATEGIES)),
                    "timeframes": config.get("timeframes", sorted(VALID_TIMEFRAMES)),
                    "auto_compute_indicators": config.get("auto_compute_indicators", True),
                }
        return normalized
    else:
        # Invalid format - return empty dict
        return {}


def validate_strategies(strategies: List[str]) -> bool:
    """Validate that all strategies are in the valid set.

    Args:
        strategies: List of strategy names to validate.

    Returns:
        True if all strategies are valid, False otherwise.
    """
    return all(s in VALID_STRATEGIES for s in strategies)


def validate_timeframes(timeframes: List[str]) -> bool:
    """Validate that all timeframes are in the valid set.

    Args:
        timeframes: List of timeframes to validate.

    Returns:
        True if all timeframes are valid, False otherwise.
    """
    return all(tf in VALID_TIMEFRAMES for tf in timeframes)


class ConfigLoader:
    """Generic configuration loader with singleton pattern.

    Supports nested key access using dot notation (e.g., "alpaca.api_key").
    Configs are loaded once and cached for performance.
    """

    _instances = {}  # Class-level cache for singleton instances

    def __new__(cls, config_path: Path):
        """Singleton pattern: return existing instance if available."""
        path_key = str(config_path)
        if path_key not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[path_key] = instance
        return cls._instances[path_key]

    def __init__(self, config_path: Path):
        """Initialize config loader.

        Args:
            config_path: Path to the JSON configuration file

        Raises:
            FileNotFoundError: If config file doesn't exist
            json.JSONDecodeError: If config file is invalid JSON
        """
        # Only initialize once (singleton)
        if hasattr(self, '_loaded'):
            return

        self.config_path = config_path
        self._data = self._load_config()
        self._loaded = True

    def _load_config(self) -> dict:
        """Load configuration from JSON file with backward compatibility.

        Automatically normalizes watchlist from array to dict format if needed.

        Returns:
            dict: Parsed configuration data with normalized watchlist

        Raises:
            FileNotFoundError: If config file doesn't exist
            json.JSONDecodeError: If config file is invalid JSON
        """
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}\n"
                f"Please create it with the required settings."
            )

        with open(self.config_path, "r") as f:
            data = json.load(f)

        # Apply backward compatibility transform for watchlist
        if "watchlist" in data:
            data["watchlist"] = normalize_watchlist(data["watchlist"])

        return data

    def write(self, data: Dict[str, Any]) -> None:
        """Write configuration to JSON file with atomic file locking.

        Creates a backup before writing and restores on failure.

        Args:
            data: Configuration dictionary to write.

        Raises:
            TimeoutError: If file lock cannot be acquired.
            IOError: If write operation fails.
        """
        backup_path = self.config_path.with_suffix(".json.bak")

        # Create backup before write
        if self.config_path.exists():
            self.config_path.rename(backup_path)

        try:
            with _file_lock(self.config_path, mode="w") as fp:
                json.dump(data, fp, indent=2)
                fp.flush()
            # Update in-memory cache
            self._data = data.copy()
            # Remove backup on success
            if backup_path.exists():
                backup_path.unlink()
        except Exception as exc:
            # Restore backup on failure
            if backup_path.exists():
                if self.config_path.exists():
                    self.config_path.unlink()
                backup_path.rename(self.config_path)
            raise IOError(f"Config write failed: {exc}") from exc

    def update_section(self, section: str, config: Dict[str, Any]) -> None:
        """Update a specific configuration section.

        Args:
            section: Section name to update.
            config: New configuration for the section.

        Raises:
            KeyError: If section doesn't exist in config.
            TimeoutError: If file lock cannot be acquired.
        """
        if section not in self._data:
            raise KeyError(f"Section '{section}' not found in config")

        data = self._data.copy()
        data[section] = config
        self.write(data)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key.

        Supports dot notation for nested keys:
        - "watchlist" -> returns config["watchlist"]
        - "alpaca.api_key" -> returns config["alpaca"]["api_key"]
        - "risk_management.max_daily_trades" -> returns nested value

        Args:
            key: Configuration key (supports dot notation)
            default: Default value if key not found

        Returns:
            Configuration value or default if not found

        Example:
            >>> config.get("watchlist")
            ["AAPL"]
            >>> config.get("risk_management.max_daily_trades")
            10
            >>> config.get("nonexistent.key", default=42)
            42
        """
        keys = key.split(".")
        value = self._data

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_all(self) -> dict:
        """Get all configuration data.

        Returns:
            dict: Complete configuration dictionary
        """
        return self._data.copy()

    def reload(self) -> None:
        """Reload configuration from file with backward compatibility.

        Automatically normalizes watchlist format on reload.
        Useful for hot-reloading config changes without restarting the app.
        """
        self._data = self._load_config()

    def get_watchlist_symbols(self) -> List[str]:
        """Get list of enabled watchlist symbols.

        Returns:
            List of uppercase symbol strings for enabled watchlist entries.
        """
        watchlist = self.get("watchlist", {})
        if isinstance(watchlist, dict):
            return [
                symbol for symbol, config in watchlist.items()
                if config.get("enabled", True)
            ]
        return []

    def get_watchlist_strategies(self, symbol: str) -> List[str]:
        """Get strategies enabled for a specific symbol.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            List of strategy names enabled for the symbol.
        """
        watchlist = self.get("watchlist", {})
        if isinstance(watchlist, dict):
            symbol_config = watchlist.get(symbol.upper(), {})
            return symbol_config.get("strategies", [])
        return []

    def get_watchlist_timeframes(self, symbol: str) -> List[str]:
        """Get timeframes enabled for a specific symbol.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            List of timeframe strings enabled for the symbol.
        """
        watchlist = self.get("watchlist", {})
        if isinstance(watchlist, dict):
            symbol_config = watchlist.get(symbol.upper(), {})
            return symbol_config.get("timeframes", [])
        return []

    def __repr__(self) -> str:
        """String representation of config loader."""
        return f"ConfigLoader('{self.config_path}')"


# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Singleton instances for config and secrets
config = ConfigLoader(PROJECT_ROOT / "config" / "config.json")
secrets = ConfigLoader(PROJECT_ROOT / "config" / "secret.json")


# Convenience functions for backward compatibility
def get_config(key: str, default: Any = None) -> Any:
    """Get configuration value from config.json.

    Args:
        key: Configuration key (supports dot notation)
        default: Default value if key not found

    Returns:
        Configuration value or default
    """
    return config.get(key, default)


def get_secret(key: str, default: Any = None) -> Any:
    """Get secret value from secret.json.

    Args:
        key: Secret key (supports dot notation)
        default: Default value if key not found

    Returns:
        Secret value or default
    """
    return secrets.get(key, default)


def reload_config() -> None:
    """Reload both config.json and secret.json."""
    config.reload()
    secrets.reload()


if __name__ == "__main__":
    """Test the config loader with backward compatibility."""
    # Add project root to path for direct execution
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(project_root))

    print("=" * 60)
    print("ConfigLoader Tests")
    print("=" * 60)

    # Test 1: Basic config loading
    print("\n[Test 1] Config.json values:")
    print(f"  Watchlist: {config.get('watchlist')}")
    print(f"  Max daily trades: {config.get('risk_management.max_daily_trades')}")
    print(f"  Market open: {config.get('market_hours.open')}")
    print(f"  Sandbox mode: {config.get('sandbox_mode')}")
    print(f"  Non-existent (default): {config.get('nonexistent', default='N/A')}")
    print("  [OK] Basic config loading")

    # Test 2: Watchlist normalization (backward compatibility)
    print("\n[Test 2] Watchlist backward compatibility:")

    # Test array format conversion
    array_watchlist = ["AAPL", "tsla", "MSFT"]
    normalized = normalize_watchlist(array_watchlist)
    assert isinstance(normalized, dict), "Should convert array to dict"
    assert "AAPL" in normalized, "Should contain AAPL"
    assert "TSLA" in normalized, "Should uppercase symbols"
    assert normalized["AAPL"]["enabled"] is True, "Should default enabled=True"
    assert len(normalized["AAPL"]["strategies"]) == 9, "Should have all 9 strategies"
    assert len(normalized["AAPL"]["timeframes"]) == 3, "Should have all 3 timeframes"
    print("  [OK] Array format -> dict conversion")

    # Test dict format pass-through
    dict_watchlist = {
        "AAPL": {
            "enabled": True,
            "strategies": ["mean_reversion", "golden_cross"],
            "timeframes": ["1Min", "1Day"],
            "auto_compute_indicators": True
        }
    }
    normalized = normalize_watchlist(dict_watchlist)
    assert isinstance(normalized, dict), "Should keep dict format"
    assert len(normalized["AAPL"]["strategies"]) == 2, "Should preserve custom strategies"
    assert len(normalized["AAPL"]["timeframes"]) == 2, "Should preserve custom timeframes"
    print("  [OK] Dict format pass-through")

    # Test 3: Validation functions
    print("\n[Test 3] Validation functions:")
    assert validate_strategies(["mean_reversion", "golden_cross"]) is True
    assert validate_strategies(["invalid_strategy"]) is False
    print("  [OK] Strategy validation")

    assert validate_timeframes(["1Min", "1Day"]) is True
    assert validate_timeframes(["5Min"]) is False
    print("  [OK] Timeframe validation")

    # Test 4: Watchlist helper methods
    print("\n[Test 4] Watchlist helper methods:")
    symbols = config.get_watchlist_symbols()
    print(f"  Enabled symbols: {symbols}")
    if symbols:
        first_symbol = symbols[0]
        strategies = config.get_watchlist_strategies(first_symbol)
        timeframes = config.get_watchlist_timeframes(first_symbol)
        print(f"  {first_symbol} strategies: {strategies[:3]}... ({len(strategies)} total)")
        print(f"  {first_symbol} timeframes: {timeframes}")
    print("  [OK] Watchlist helpers")

    # Test 5: Constants
    print("\n[Test 5] Constants:")
    print(f"  Valid strategies: {len(VALID_STRATEGIES)} strategies")
    print(f"  Valid timeframes: {sorted(VALID_TIMEFRAMES)}")
    assert len(VALID_STRATEGIES) == 9, "Should have 9 valid strategies"
    assert len(VALID_TIMEFRAMES) == 3, "Should have 3 valid timeframes"
    print("  [OK] Constants defined")

    print("\nAll config keys:")
    for key in config.get_all().keys():
        print(f"  - {key}")

    print("\n" + "=" * 60)
    print("✓ All ConfigLoader tests passed")
    print("=" * 60)
