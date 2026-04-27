"""Utilities for the Agentic Portfolio Manager.

This module provides essential utility functions:
- ConfigLoader: Generic configuration and secrets loader
- Logger: Centralized logging setup

Usage:
    from src.common.utils import config, secrets, get_logger

    # Access configuration
    watchlist = config.get("watchlist")
    api_key = secrets.get("alpaca.api_key")

    # Get logger
    logger = get_logger(__name__)
"""

# Config loader exports
from .config_loader import (
    config,
    secrets,
    get_config,
    get_secret,
    reload_config,
    ConfigLoader,
)

# Logger exports
from .logger import (
    get_logger,
    setup_logging,
    LoggerSetup,
)

__all__ = [
    # Config
    "config",
    "secrets",
    "get_config",
    "get_secret",
    "reload_config",
    "ConfigLoader",
    # Logger
    "get_logger",
    "setup_logging",
    "LoggerSetup",
]
