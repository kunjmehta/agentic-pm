"""Portfolio Manager agent module.

Exports:
    PortfolioManager: Central coordinator for portfolio management
"""

def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    if name == "PortfolioManager":
        from src.agentic.agents.portfolio.manager import PortfolioManager
        return PortfolioManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["PortfolioManager"]
