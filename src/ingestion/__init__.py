"""Ingestion module for real-time market data.

This module handles ingestion of market data from external sources
(e.g., Alpaca WebSocket) and publishes to Redis Streams for downstream
consumption by backend services and UI.
"""

from src.ingestion.alpaca_redis_ingestion import AlpacaRedisIngestion

__all__ = ["AlpacaRedisIngestion"]
