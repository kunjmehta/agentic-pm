"""Response models for backtest endpoints (BacktestDAO)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BacktestRunsResponse(BaseModel):
    """Response for GET /v1/backtest/runs.

    Attributes:
        runs: List of backtest run summary dicts.
        count: Number of runs.
    """

    runs: List[Any] = Field(default_factory=list)
    count: int


class BacktestRunResponse(BaseModel):
    """Response for GET /v1/backtest/runs/{run_id}.

    Attributes:
        run_id: Run identifier.
        run: Run detail dict, or ``None`` if not found.
    """

    run_id: str
    run: Optional[Dict[str, Any]] = None


class BacktestTradesResponse(BaseModel):
    """Response for GET /v1/backtest/runs/{run_id}/trades.

    Attributes:
        run_id: Run identifier.
        trades: Trade rows for the run.
        count: Number of trade rows.
    """

    run_id: str
    trades: List[Any] = Field(default_factory=list)
    count: int


class BacktestPerformanceResponse(BaseModel):
    """Response for GET /v1/backtest/runs/{run_id}/performance.

    Attributes:
        run_id: Run identifier.
        performance: Daily performance rows.
        count: Number of rows.
    """

    run_id: str
    performance: List[Any] = Field(default_factory=list)
    count: int
