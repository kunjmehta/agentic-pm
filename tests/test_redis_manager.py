"""Unit tests for Redis Manager.

Tests the Redis connection manager functionality using mocks
to avoid requiring actual Redis connection.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import ssl


class TestRedisManager:
    """Test suite for RedisManager."""

    @patch("src.common.cache.redis_manager.config")
    @patch("src.common.cache.redis_manager.secrets")
    @patch("src.common.cache.redis_manager.redis.Redis")
    @patch("src.common.cache.redis_manager.ConnectionPool")
    def test_initialize_with_valid_config(
        self, mock_pool, mock_redis, mock_secrets, mock_config
    ):
        """Test successful initialization with valid configuration."""
        # Setup mocks
        mock_config.get.side_effect = lambda key, default=None: {
            "redis.enabled": True,
            "redis.cloud": {
                "host": "test-redis.cloud.com",
                "port": 6379,
                "password_secret_key": "redis.password",
                "ssl": True,
                "ssl_cert_reqs": "required",
                "max_connections": 50,
                "socket_timeout": 5,
                "socket_connect_timeout": 5,
                "retry_on_timeout": True,
                "health_check_interval": 30,
            },
        }.get(key, default)

        mock_secrets.get.return_value = "test-password"

        # Mock Redis client
        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        # Import after patching to ensure singleton is created with mocks
        from src.common.cache.redis_manager import RedisManager

        # Reset singleton
        RedisManager._instance = None

        # Initialize
        redis_mgr = RedisManager()

        # Verify connection pool created with correct parameters
        mock_pool.assert_called_once()
        call_kwargs = mock_pool.call_args.kwargs

        assert call_kwargs["host"] == "test-redis.cloud.com"
        assert call_kwargs["port"] == 6379
        assert call_kwargs["password"] == "test-password"
        assert call_kwargs["ssl"] is True
        assert call_kwargs["ssl_cert_reqs"] == ssl.CERT_REQUIRED
        assert call_kwargs["max_connections"] == 50

        # Verify Redis client created
        mock_redis.assert_called_once()
        mock_client.ping.assert_called_once()

    @patch("src.common.cache.redis_manager.config")
    def test_initialize_with_redis_disabled(self, mock_config):
        """Test initialization fails when Redis is disabled."""
        mock_config.get.return_value = False

        from src.common.cache.redis_manager import RedisManager

        # Reset singleton
        RedisManager._instance = None

        with pytest.raises(ValueError, match="Redis is not enabled"):
            RedisManager()

    @patch("src.common.cache.redis_manager.config")
    @patch("src.common.cache.redis_manager.secrets")
    def test_initialize_without_password(self, mock_secrets, mock_config):
        """Test initialization fails without password."""
        mock_config.get.side_effect = lambda key, default=None: {
            "redis.enabled": True,
            "redis.cloud": {
                "host": "test-redis.cloud.com",
                "port": 6379,
                "password_secret_key": "redis.password",
            },
        }.get(key, default)

        mock_secrets.get.return_value = None

        from src.common.cache.redis_manager import RedisManager

        # Reset singleton
        RedisManager._instance = None

        with pytest.raises(ValueError, match="Redis password not found"):
            RedisManager()

    @patch("src.common.cache.redis_manager.config")
    @patch("src.common.cache.redis_manager.secrets")
    @patch("src.common.cache.redis_manager.redis.Redis")
    @patch("src.common.cache.redis_manager.ConnectionPool")
    def test_health_check_success(
        self, mock_pool, mock_redis, mock_secrets, mock_config
    ):
        """Test health check returns True when connection is healthy."""
        # Setup mocks
        mock_config.get.side_effect = lambda key, default=None: {
            "redis.enabled": True,
            "redis.cloud": {
                "host": "test-redis.cloud.com",
                "port": 6379,
                "password_secret_key": "redis.password",
            },
        }.get(key, default)

        mock_secrets.get.return_value = "test-password"

        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        from src.common.cache.redis_manager import RedisManager

        # Reset singleton
        RedisManager._instance = None

        redis_mgr = RedisManager()

        # Health check
        is_healthy = redis_mgr.health_check()

        assert is_healthy is True
        assert mock_client.ping.call_count == 2  # Once during init, once during check

    @patch("src.common.cache.redis_manager.config")
    @patch("src.common.cache.redis_manager.secrets")
    @patch("src.common.cache.redis_manager.redis.Redis")
    @patch("src.common.cache.redis_manager.ConnectionPool")
    def test_singleton_pattern(
        self, mock_pool, mock_redis, mock_secrets, mock_config
    ):
        """Test that RedisManager follows singleton pattern."""
        # Setup mocks
        mock_config.get.side_effect = lambda key, default=None: {
            "redis.enabled": True,
            "redis.cloud": {
                "host": "test-redis.cloud.com",
                "port": 6379,
                "password_secret_key": "redis.password",
            },
        }.get(key, default)

        mock_secrets.get.return_value = "test-password"

        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        from src.common.cache.redis_manager import RedisManager

        # Reset singleton
        RedisManager._instance = None

        # Create two instances
        redis_mgr1 = RedisManager()
        redis_mgr2 = RedisManager()

        # Should be same instance
        assert redis_mgr1 is redis_mgr2

        # Connection pool should only be created once
        assert mock_pool.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
