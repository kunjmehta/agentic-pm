"""Portfolio skill functions re-exported for use by the semi_auto registry.

All imports from src/agentic/ are isolated in this file so the rest of
src/semi_auto/ never directly imports from src/agentic/.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

try:
    from src.agentic.agents.portfolio.skills.portfoliostatus.status import (
        get_portfolio_status_core,
        get_positions_summary_core,
    )
except Exception as _e:
    logger.warning(f"[semi_auto.skills.portfolio] status skill load failed: {_e}")
    get_portfolio_status_core = None
    get_positions_summary_core = None

try:
    from src.agentic.agents.portfolio.skills.health.health import check_portfolio_health_core
except Exception as _e:
    logger.warning(f"[semi_auto.skills.portfolio] health skill load failed: {_e}")
    check_portfolio_health_core = None

try:
    from src.agentic.agents.portfolio.skills.datamanagement.data import (
        fetch_historical_data_core,
        check_data_availability_core,
    )
except Exception as _e:
    logger.warning(f"[semi_auto.skills.portfolio] data skill load failed: {_e}")
    fetch_historical_data_core = None
    check_data_availability_core = None

__all__ = [
    "get_portfolio_status_core",
    "get_positions_summary_core",
    "check_portfolio_health_core",
    "fetch_historical_data_core",
    "check_data_availability_core",
]
