"""Pydantic models for Backtester structured outputs."""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class BacktestMetrics(BaseModel):
    """Performance metrics from backtest simulation."""

    sharpe_ratio: float = Field(description="Sharpe ratio (risk-adjusted returns)")
    max_drawdown_pct: float = Field(description="Maximum drawdown percentage (negative)")
    win_rate: float = Field(description="Percentage of winning trades (0-1)")
    profit_factor: float = Field(description="Gross profit / gross loss ratio")
    total_return_pct: float = Field(description="Total return percentage")
    total_trades: int = Field(description="Total number of trades executed")
    winning_trades: int = Field(description="Number of winning trades")
    losing_trades: int = Field(description="Number of losing trades")
    avg_win: Optional[float] = Field(default=None, description="Average winning trade P&L")
    avg_loss: Optional[float] = Field(default=None, description="Average losing trade P&L")
    largest_win: Optional[float] = Field(default=None, description="Largest winning trade")
    largest_loss: Optional[float] = Field(default=None, description="Largest losing trade")


class DataSummary(BaseModel):
    """Summary of historical data availability."""

    symbol: str = Field(description="Stock ticker")
    start_date: str = Field(description="Data start date (ISO format)")
    end_date: str = Field(description="Data end date (ISO format)")
    timeframe: str = Field(description="Bar timeframe (e.g., 1Min, 1Hour)")
    total_bars: int = Field(description="Number of bars available")
    trading_days: int = Field(description="Number of trading days covered")
    data_complete: bool = Field(description="Whether data has no gaps")
    message: str = Field(description="Human-readable summary")


class TradeSignal(BaseModel):
    """Individual trade signal."""

    timestamp: str = Field(description="Signal timestamp (ISO format)")
    signal_type: str = Field(description="buy, sell, or hold")
    price: float = Field(description="Price at signal")
    confidence: Optional[float] = Field(default=None, description="Signal confidence (0-1)")
    reason: Optional[str] = Field(default=None, description="Signal reasoning")


class BacktestResult(BaseModel):
    """Complete backtest result with metrics and summary."""

    run_id: str = Field(description="Unique backtest run identifier")
    status: str = Field(description="completed, failed, or running")
    strategy: str = Field(description="Strategy name")
    symbol: str = Field(description="Stock ticker")
    period_start: str = Field(description="Backtest period start date")
    period_end: str = Field(description="Backtest period end date")
    initial_capital: float = Field(description="Starting capital")
    final_equity: float = Field(description="Ending equity")
    metrics: BacktestMetrics = Field(description="Performance metrics")
    summary: str = Field(description="Human-readable summary")
    recommendation: str = Field(description="Strategy recommendation")
    timestamp: str = Field(description="Completion timestamp")


class SimulationRequest(BaseModel):
    """Request for backtest simulation."""

    strategy_name: str = Field(description="Strategy to test (e.g., mean-reversion)")
    symbol: str = Field(description="Stock ticker")
    start_date: str = Field(description="Start date (YYYY-MM-DD)")
    end_date: str = Field(description="End date (YYYY-MM-DD)")
    initial_capital: float = Field(default=100000.0, description="Starting capital")
    timeframe: str = Field(default="1Min", description="Bar timeframe")


class SimulationResult(BaseModel):
    """Result from backtest simulation."""

    status: str = Field(description="success or error")
    metrics: Optional[BacktestMetrics] = Field(default=None, description="Performance metrics")
    data_summary: DataSummary = Field(description="Data coverage summary")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    message: str = Field(description="Human-readable result")
