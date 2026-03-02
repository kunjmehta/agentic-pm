"""Shared pytest fixtures and configuration."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest


@pytest.fixture(scope="session")
def project_root_path():
    """Return the project root path."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def test_symbol():
    """Return a test symbol for use in tests."""
    return "TEST"


@pytest.fixture(scope="session")
def sample_indicators():
    """Return sample technical indicators."""
    return {
        "macd": {"value": 0.52, "signal": 0.48, "histogram": 0.04},
        "rsi": 65.3,
        "bollinger": {"upper": 150.5, "middle": 148.0, "lower": 145.5}
    }


@pytest.fixture(scope="session")
def sample_signals():
    """Return sample trading signals."""
    return {
        "momentum": "bullish",
        "volatility": "normal",
        "volume_trend": "increasing"
    }


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "requires_api: marks tests that require API keys"
    )
