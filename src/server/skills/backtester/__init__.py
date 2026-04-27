"""Backtester skills package — one class per file.

    backtest_strategy.py  — BacktestStrategySkill (Workflow A)
    snapshot.py           — SnapshotSkill (Workflow B)
    swap_positions.py     — SwapPositionsSkill (Workflow C)
"""

from src.server.skills.backtester.backtest_strategy import (
    BacktestStrategySkill,
    backtest_skill,
    backtest_strategy_core,
)
from src.server.skills.backtester.snapshot import (
    SnapshotSkill,
    snapshot_skill,
    save_eod_snapshot_core,
    snapshot_worth_core,
)
from src.server.skills.backtester.swap_positions import (
    SwapPositionsSkill,
    swap_skill,
    swap_positions_core,
)

__all__ = [
    "BacktestStrategySkill",
    "SnapshotSkill",
    "SwapPositionsSkill",
    "backtest_skill",
    "snapshot_skill",
    "swap_skill",
    "backtest_strategy_core",
    "save_eod_snapshot_core",
    "snapshot_worth_core",
    "swap_positions_core",
]
