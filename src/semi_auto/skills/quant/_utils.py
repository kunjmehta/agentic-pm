"""Shared utilities for quant skill modules.

Provides the ``_fetch_bars`` helper used by all strategy skill classes.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)


def _fetch_bars(
    symbol: str,
    timeframe: str = "1Day",
    lookback_days: int = 90,
) -> Optional[pd.DataFrame]:
    """Fetch OHLCV bars from AlpacaDAO.

    Args:
        symbol: Stock ticker.
        timeframe: AlpacaDAO canonical timeframe (e.g. ``"1Day"``, ``"1Min"``).
        lookback_days: Calendar days to look back from now.

    Returns:
        DataFrame or ``None`` if unavailable.
    """
    try:
        from src.common.dao import AlpacaDAO
        dao = AlpacaDAO()
        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        df = dao.get_bars(symbol, start=start, end=end, timeframe=timeframe)
        dao.close()
        if df is None or df.empty:
            logger.warning("[quant._utils] No bars for %s/%s", symbol, timeframe)
            return None
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("[quant._utils] Bar fetch failed for %s: %s", symbol, exc)
        return None
