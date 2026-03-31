"""Backtester skill functions re-exported for use by the semi_auto registry.

The backtest-strategy skill lives in a hyphenated directory and is loaded
via importlib. All imports from src/agentic/ are isolated in this file.
"""

import importlib.util
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

_BT_SKILLS = project_root / "src" / "agentic" / "agents" / "backtester" / "skills"


def _load_skill(folder: str, filename: str):
    """Load a backtester skill module from a hyphenated directory.

    Args:
        folder: Skill folder name (may contain hyphens).
        filename: Python file inside the folder.

    Returns:
        Loaded module object, or None on failure.
    """
    path = _BT_SKILLS / folder / filename
    module_name = f"semi_auto_bt_skill_{folder.replace('-', '_')}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        logger.warning(f"[semi_auto.skills.backtester] failed to load {folder}/{filename}: {exc}")
        return None


_bt_strategy_mod = _load_skill("backtest-strategy", "strategy.py")
backtest_strategy_core = getattr(_bt_strategy_mod, "backtest_strategy_core", None)

__all__ = ["backtest_strategy_core"]
