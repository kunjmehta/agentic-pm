"""Redis connection manager with singleton pattern for cloud Redis.

This module provides a centralized Redis connection pool with:
- Singleton pattern for single connection pool
- SSL support for cloud Redis
- Connection pooling with health checks
- Auto-reconnection on failure
- Configuration from config.json and secret.json

Usage:
    from src.common.cache.redis_manager import RedisManager

    # Get singleton instance
    redis_mgr = RedisManager()

    # Get Redis client
    client = redis_mgr.get_client()
    client.set("key", "value")

    # Check health
    is_healthy = redis_mgr.health_check()
"""

import ssl
import time
from typing import Optional

import redis
from redis.connection import ConnectionPool

from src.common.utils.config_loader import config, secrets
from src.common.utils.logger import get_logger

logger = get_logger(__name__)


class RedisManager:
    """Singleton Redis connection manager for cloud Redis with SSL support.

    Provides thread-safe connection pooling, health checks, and auto-reconnection.
    Configuration loaded from config.json redis.cloud section and password from
    secret.json.
    """

    _instance: Optional["RedisManager"] = None
    _pool: Optional[ConnectionPool] = None
    _client: Optional[redis.Redis] = None

    def __new__(cls):
        """Singleton pattern: return existing instance if available."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize Redis connection pool from configuration.

        Raises:
            ValueError: If Redis is not enabled in config
            redis.RedisError: If connection fails
        """
        # Check if Redis is enabled
        if not config.get("redis.enabled", default=False):
            logger.warning("Redis is disabled in config.json")
            raise ValueError("Redis is not enabled in configuration")

        # Load cloud Redis configuration
        cloud_config = config.get("redis.cloud", default={})
        if not cloud_config:
            raise ValueError("redis.cloud configuration missing in config.json")

        host = cloud_config.get("host")
        port = cloud_config.get("port", 6379)
        password_key = cloud_config.get("password_secret_key", "redis.password")
        use_ssl = cloud_config.get("ssl", True)
        ssl_cert_reqs_str = cloud_config.get("ssl_cert_reqs", "required")
        max_connections = cloud_config.get("max_connections", 50)
        socket_timeout = cloud_config.get("socket_timeout", 5)
        socket_connect_timeout = cloud_config.get("socket_connect_timeout", 5)
        retry_on_timeout = cloud_config.get("retry_on_timeout", True)
        health_check_interval = cloud_config.get("health_check_interval", 30)

        # Get password from secrets
        password = secrets.get(password_key)
        if not password:
            raise ValueError(f"Redis password not found in secret.json at key '{password_key}'")

        # Map SSL cert requirements
        ssl_cert_reqs_map = {
            "none": ssl.CERT_NONE,
            "optional": ssl.CERT_OPTIONAL,
            "required": ssl.CERT_REQUIRED,
        }
        ssl_cert_reqs = ssl_cert_reqs_map.get(ssl_cert_reqs_str.lower(), ssl.CERT_REQUIRED)

        logger.info(f"Initializing Redis connection pool to {host}:{port} (SSL: {use_ssl})")

        # Create connection pool
        try:
            pool_kwargs = {
                "host": host,
                "port": port,
                "password": password,
                "max_connections": max_connections,
                "socket_timeout": socket_timeout,
                "socket_connect_timeout": socket_connect_timeout,
                "retry_on_timeout": retry_on_timeout,
                "health_check_interval": health_check_interval,
                "decode_responses": False,  # We'll use msgpack for serialization
            }

            # Add SSL parameters if enabled
            if use_ssl:
                pool_kwargs["ssl"] = True
                pool_kwargs["ssl_cert_reqs"] = ssl_cert_reqs

            self._pool = ConnectionPool(**pool_kwargs)

            # Create Redis client
            self._client = redis.Redis(connection_pool=self._pool)

            # Test connection
            self._client.ping()
            logger.info("Redis connection pool initialized successfully")

        except redis.RedisError as e:
            logger.error(f"Failed to initialize Redis connection: {e}")
            raise

    def get_client(self) -> redis.Redis:
        """Get Redis client from connection pool.

        Returns:
            redis.Redis: Redis client instance

        Raises:
            ValueError: If Redis client not initialized
        """
        if self._client is None:
            raise ValueError("Redis client not initialized")
        return self._client

    def health_check(self) -> bool:
        """Check Redis connection health.

        Returns:
            bool: True if connection is healthy, False otherwise
        """
        try:
            if self._client is None:
                logger.error("Redis client not initialized")
                return False

            self._client.ping()
            return True

        except redis.RedisError as e:
            logger.error(f"Redis health check failed: {e}")
            return False

    def reconnect(self) -> bool:
        """Attempt to reconnect to Redis.

        Returns:
            bool: True if reconnection successful, False otherwise
        """
        logger.info("Attempting Redis reconnection...")
        try:
            if self._client:
                self._client.close()

            # Reinitialize
            self._initialize()
            return True

        except Exception as e:
            logger.error(f"Redis reconnection failed: {e}")
            return False

    def close(self) -> None:
        """Close Redis connection and cleanup resources."""
        if self._client:
            logger.info("Closing Redis connection")
            self._client.close()
            self._client = None

        if self._pool:
            self._pool.disconnect()
            self._pool = None

    def get_info(self) -> dict:
        """Get Redis server info.

        Returns:
            dict: Redis server information
        """
        try:
            return self._client.info() if self._client else {}
        except redis.RedisError as e:
            logger.error(f"Failed to get Redis info: {e}")
            return {}

    def __repr__(self) -> str:
        """String representation of Redis manager."""
        cloud_config = config.get("redis.cloud", default={})
        host = cloud_config.get("host", "unknown")
        port = cloud_config.get("port", 6379)
        return f"RedisManager(host={host}, port={port}, healthy={self.health_check()})"


if __name__ == "__main__":
    """Test Redis manager with configuration."""
    import sys
    from pathlib import Path

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(project_root))

    print("=" * 60)
    print("RedisManager Tests")
    print("=" * 60)

    try:
        # Test 1: Initialize Redis manager
        print("\n[Test 1] Initialize Redis manager:")
        redis_mgr = RedisManager()
        print(f"  Manager: {redis_mgr}")
        print("  [OK] Redis manager initialized")

        # Test 2: Health check
        print("\n[Test 2] Health check:")
        is_healthy = redis_mgr.health_check()
        print(f"  Health status: {is_healthy}")
        assert is_healthy, "Redis connection should be healthy"
        print("  [OK] Health check passed")

        # Test 3: Get client and basic operations
        print("\n[Test 3] Basic Redis operations:")
        client = redis_mgr.get_client()

        # Set and get
        test_key = "test:redis_manager"
        test_value = "Hello Redis!"
        client.set(test_key, test_value)
        retrieved = client.get(test_key)
        assert retrieved.decode() == test_value, "Value mismatch"
        print(f"  SET/GET: {test_key} -> {retrieved.decode()}")

        # Delete
        client.delete(test_key)
        assert client.get(test_key) is None, "Key should be deleted"
        print("  [OK] Basic operations working")

        # Test 4: Get server info
        print("\n[Test 4] Redis server info:")
        info = redis_mgr.get_info()
        if info:
            print(f"  Redis version: {info.get('redis_version', 'unknown')}")
            print(f"  Connected clients: {info.get('connected_clients', 0)}")
            print(f"  Used memory: {info.get('used_memory_human', 'unknown')}")
        print("  [OK] Server info retrieved")

        # Test 5: Singleton pattern
        print("\n[Test 5] Singleton pattern:")
        redis_mgr2 = RedisManager()
        assert redis_mgr is redis_mgr2, "Should return same instance"
        print("  [OK] Singleton pattern verified")

        print("\n" + "=" * 60)
        print("✓ All RedisManager tests passed")
        print("=" * 60)

    except ValueError as e:
        print(f"\n✗ Configuration error: {e}")
        print("\nMake sure config.json has redis.cloud section:")
        print("""
{
  "redis": {
    "enabled": true,
    "cloud": {
      "host": "your-redis-cloud-host.com",
      "port": 6379,
      "password_secret_key": "redis.password",
      "ssl": true,
      "ssl_cert_reqs": "required",
      "max_connections": 50,
      "socket_timeout": 5,
      "socket_connect_timeout": 5,
      "retry_on_timeout": true,
      "health_check_interval": 30
    }
  }
}
        """)
        print("\nAnd secret.json has redis.password:")
        print("""
{
  "redis": {
    "password": "YOUR_REDIS_CLOUD_PASSWORD"
  }
}
        """)
        sys.exit(1)

    except redis.RedisError as e:
        print(f"\n✗ Redis connection error: {e}")
        print("\nCheck your Redis cloud configuration and network connectivity")
        sys.exit(1)

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
