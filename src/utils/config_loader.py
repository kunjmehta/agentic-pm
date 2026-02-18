"""Generic configuration loader for config.json and secret.json.

This module provides a centralized way to load and access application
configuration and secrets. It uses singleton pattern to ensure configs
are loaded only once.

Usage:
    from src.core.config_loader import config, secrets

    # Access config values
    watchlist = config.get("watchlist")
    max_trades = config.get("risk_management.max_daily_trades")

    # Access secrets
    alpaca_key = secrets.get("alpaca.api_key")

    # With defaults
    feed = config.get("data_feed", default="iex")
"""

import json
from pathlib import Path
from typing import Any, Optional


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
        """Load configuration from JSON file.

        Returns:
            dict: Parsed configuration data

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
            return json.load(f)

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
        """Reload configuration from file.

        Useful for hot-reloading config changes without restarting the app.
        """
        self._data = self._load_config()

    def __repr__(self) -> str:
        """String representation of config loader."""
        return f"ConfigLoader('{self.config_path}')"


# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent

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
    """Test the config loader."""
    # Add project root to path for direct execution
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    print("Testing ConfigLoader...\n")

    # Test config.json
    print("Config.json values:")
    print(f"  Watchlist: {config.get('watchlist')}")
    print(f"  Max daily trades: {config.get('risk_management.max_daily_trades')}")
    print(f"  Market open: {config.get('market_hours.open')}")
    print(f"  Sandbox mode: {config.get('sandbox_mode')}")
    print(f"  Non-existent (default): {config.get('nonexistent', default='N/A')}")

    print("\nSecret.json values:")
    print(f"  Alpaca API key: {secrets.get('alpaca.api_key', 'NOT_FOUND')[:10]}...")
    print(f"  Alpha Vantage key: {secrets.get('alpha_vantage.api_key', 'NOT_FOUND')[:10]}...")

    print("\nAll config keys:")
    for key in config.get_all().keys():
        print(f"  - {key}")

    print("\n✓ ConfigLoader test complete")
