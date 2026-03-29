"""Portfolio Health Check Skill - Validate portfolio against risk parameters."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import argparse
from datetime import datetime
from typing import Dict

from src.common.dao import PortfolioDAO
from src.common.utils import get_logger

logger = get_logger(__name__)


def check_portfolio_health_core(portfolio_status: Dict, positions_data: Dict) -> Dict:
    """Check portfolio health against risk parameters.

    Args:
        portfolio_status: Portfolio status dict from get_portfolio_status
        positions_data: Positions summary dict from get_positions_summary

    Returns:
        Dict with health status and any violations
    """
    # Get risk parameters from DAO
    dao = PortfolioDAO()
    risk_params = dao.get_risk_parameters()
    dao.close()

    # Extract limits with defaults
    position_limit_percent = risk_params.get("position_limit_percent", {}).get("value", 0.1)
    daily_loss_limit = risk_params.get("daily_loss_limit", {}).get("value", 0.05)
    max_position_size = risk_params.get("max_position_size", {}).get("value", 1000)

    violations = []
    warnings = []

    # Check position concentration
    equity = portfolio_status.get("equity", 0)
    if equity > 0:
        for pos in positions_data.get("positions", []):
            position_percent = abs(pos["market_value"]) / equity
            if position_percent > position_limit_percent:
                violations.append({
                    "rule": "position_limit_percent",
                    "symbol": pos["symbol"],
                    "current": position_percent,
                    "limit": position_limit_percent,
                    "message": f"{pos['symbol']} represents {position_percent*100:.1f}% of portfolio (limit: {position_limit_percent*100:.1f}%)"
                })

            # Check position size
            if abs(pos["qty"]) > max_position_size:
                warnings.append({
                    "rule": "max_position_size",
                    "symbol": pos["symbol"],
                    "current": abs(pos["qty"]),
                    "limit": max_position_size,
                    "message": f"{pos['symbol']} position size {abs(pos['qty'])} exceeds limit {max_position_size}"
                })

    # Check cash reserves
    cash_percent = portfolio_status.get("cash", 0) / equity if equity > 0 else 0
    if cash_percent < 0.05:
        warnings.append({
            "rule": "cash_reserve",
            "current": cash_percent,
            "message": f"Low cash reserves: {cash_percent*100:.1f}%"
        })

    # Determine health status
    if violations:
        health_status = "unhealthy"
    elif warnings:
        health_status = "warning"
    else:
        health_status = "healthy"

    return {
        "health_status": health_status,
        "violations": violations,
        "warnings": warnings,
        "checks_performed": ["position_concentration", "position_size", "cash_reserves"],
        "risk_parameters_used": {
            "position_limit_percent": position_limit_percent,
            "max_position_size": max_position_size,
            "daily_loss_limit": daily_loss_limit
        },
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check portfolio health")
    args = parser.parse_args()

    try:
        # Import here to avoid circular dependency
        from src.agentic.agents.portfolio.skills.portfoliostatus.status import (
            get_portfolio_status_core,
            get_positions_summary_core
        )

        portfolio_status = get_portfolio_status_core()
        positions_data = get_positions_summary_core()
        result = check_portfolio_health_core(portfolio_status, positions_data)

        print(json.dumps(result, indent=2, default=str))

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        print(json.dumps({"health_status": "error", "error": str(e)}))
        sys.exit(1)
