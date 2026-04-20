"""ETL (Extract, Transform, Load) package for technical indicators and strategy signals.

This package provides tools for pre-computing technical indicators and strategy
signals, storing them in the database for fast retrieval by the quant agent.

All formulas are sourced from the quant skill singletons in
``src.server.skills.quant``, ensuring a single source of truth shared with
the function registry and backtester.

Modules:
    pipeline: ETL orchestrator for batch processing of indicators and strategy signals
"""

from src.common.etl.pipeline import IndicatorsETL

__all__ = ["IndicatorsETL"]
