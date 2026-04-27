"""Unit tests for ConfigLoader.

Tests the generic configuration loader with singleton pattern.
Run with: pytest tests/test_core/test_config_loader.py -v
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import patch, mock_open
import json
from src.common.utils.config_loader import ConfigLoader, config, secrets


class TestConfigLoader:
    """Test suite for ConfigLoader class."""

    def setup_method(self):
        """Clear singleton cache before each test."""
        ConfigLoader._instances.clear()

    def test_singleton_pattern(self):
        """Test that ConfigLoader implements singleton pattern."""
        # Create two instances with same path
        path = Path("test_config.json")

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data='{"key": "value"}')):
                loader1 = ConfigLoader(path)
                loader2 = ConfigLoader(path)

                # Should be the same instance
                assert loader1 is loader2

    def test_load_config_success(self):
        """Test successful config loading."""
        test_config = {"watchlist": ["AAPL"], "sandbox_mode": True}
        config_json = json.dumps(test_config)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                loader = ConfigLoader(Path("test.json"))

                assert loader.get("watchlist") == ["AAPL"]
                assert loader.get("sandbox_mode") is True

    def test_load_config_file_not_found(self):
        """Test error when config file doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            with pytest.raises(FileNotFoundError, match="Configuration file not found"):
                ConfigLoader(Path("nonexistent.json"))

    def test_get_simple_key(self):
        """Test getting simple top-level key."""
        test_config = {"watchlist": ["AAPL", "GOOGL"]}
        config_json = json.dumps(test_config)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                loader = ConfigLoader(Path("test.json"))

                result = loader.get("watchlist")
                assert result == ["AAPL", "GOOGL"]

    def test_get_nested_key(self):
        """Test getting nested key with dot notation."""
        test_config = {
            "risk_management": {
                "max_daily_trades": 10,
                "max_position_size": 1000
            }
        }
        config_json = json.dumps(test_config)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                loader = ConfigLoader(Path("test.json"))

                result = loader.get("risk_management.max_daily_trades")
                assert result == 10

    def test_get_deeply_nested_key(self):
        """Test getting deeply nested key."""
        test_config = {
            "level1": {
                "level2": {
                    "level3": "deep_value"
                }
            }
        }
        config_json = json.dumps(test_config)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                loader = ConfigLoader(Path("test.json"))

                result = loader.get("level1.level2.level3")
                assert result == "deep_value"

    def test_get_nonexistent_key_with_default(self):
        """Test getting nonexistent key returns default."""
        test_config = {"existing": "value"}
        config_json = json.dumps(test_config)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                loader = ConfigLoader(Path("test.json"))

                result = loader.get("nonexistent", default="default_value")
                assert result == "default_value"

    def test_get_nonexistent_nested_key(self):
        """Test getting nonexistent nested key returns default."""
        test_config = {"level1": {"existing": "value"}}
        config_json = json.dumps(test_config)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                loader = ConfigLoader(Path("test.json"))

                result = loader.get("level1.nonexistent", default=None)
                assert result is None

    def test_get_all(self):
        """Test getting all configuration data."""
        test_config = {"key1": "value1", "key2": "value2"}
        config_json = json.dumps(test_config)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                loader = ConfigLoader(Path("test.json"))

                result = loader.get_all()
                assert result == test_config
                # Verify it's a copy, not the original
                assert result is not loader._data

    def test_reload(self):
        """Test reloading configuration."""
        config1 = {"version": 1}
        config2 = {"version": 2}

        with patch("pathlib.Path.exists", return_value=True):
            # First load
            with patch("builtins.open", mock_open(read_data=json.dumps(config1))):
                loader = ConfigLoader(Path("test.json"))
                assert loader.get("version") == 1

            # Reload with new data
            with patch("builtins.open", mock_open(read_data=json.dumps(config2))):
                loader.reload()
                assert loader.get("version") == 2


class TestGlobalInstances:
    """Test global config and secrets instances."""

    def test_config_instance_loads(self):
        """Test that global config instance loads correctly."""
        # The config instance should load config.json
        watchlist = config.get("watchlist")
        assert isinstance(watchlist, list)
        assert "AAPL" in watchlist

    def test_secrets_instance_loads(self):
        """Test that global secrets instance loads correctly."""
        # The secrets instance should load secret.json
        # Just test that it doesn't raise an error
        alpaca_key = secrets.get("alpaca.api_key", default="NOT_SET")
        assert alpaca_key is not None

    def test_get_config_convenience_function(self):
        """Test get_config convenience function."""
        from src.common.utils.config_loader import get_config

        result = get_config("watchlist")
        assert isinstance(result, list)

    def test_get_secret_convenience_function(self):
        """Test get_secret convenience function."""
        from src.common.utils.config_loader import get_secret

        result = get_secret("alpaca.api_key", default="DEFAULT")
        assert result is not None


if __name__ == "__main__":
    """Run tests with pytest."""
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
