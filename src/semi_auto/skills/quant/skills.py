"""Quant skill functions re-exported for use by the semi_auto registry.

Quant skills live in hyphenated directories (e.g. momentum-indicators)
which cannot be imported with normal Python import syntax, so they are
loaded via importlib and re-exported here.

All imports from src/agentic/ are isolated in this file.
"""

import importlib.util
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

_QUANT_SKILLS = project_root / "src" / "agentic" / "agents" / "quant" / "skills"


def _load_skill(folder: str, filename: str):
    """Load a quant skill module from a hyphenated directory.

    Args:
        folder: Skill folder name (may contain hyphens).
        filename: Python file inside the folder.

    Returns:
        Loaded module object, or None on failure.
    """
    path = _QUANT_SKILLS / folder / filename
    module_name = f"semi_auto_quant_skill_{folder.replace('-', '_')}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        logger.warning(f"[semi_auto.skills.quant] failed to load {folder}/{filename}: {exc}")
        return None


_momentum_mod = _load_skill("momentum-indicators", "momentum.py")
_volatility_mod = _load_skill("volatility-indicators", "volatility.py")
_volume_mod = _load_skill("volume-indicators", "volume.py")
_candles_mod = _load_skill("candlestick-patterns", "candles.py")
_mr_mod = _load_skill("mean-reversion-strategy", "mean_reversion.py")

calc_momentum_package = getattr(_momentum_mod, "calc_momentum_package", None)
calc_volatility_bands = getattr(_volatility_mod, "calc_volatility_bands", None)
calc_volume_flow = getattr(_volume_mod, "calc_volume_flow", None)
analyze_candle_structure = getattr(_candles_mod, "analyze_candle_structure", None)
MeanReversionStrategy = getattr(_mr_mod, "MeanReversionStrategy", None)

__all__ = [
    "calc_momentum_package",
    "calc_volatility_bands",
    "calc_volume_flow",
    "analyze_candle_structure",
    "MeanReversionStrategy",
]
