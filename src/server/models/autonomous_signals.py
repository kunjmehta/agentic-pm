"""Pydantic models for autonomous signal aggregation and HITL approval.

Defines the data structures used in the periodic autonomous trading flow:
1. StrategySignal: Individual strategy signal from strategy_results table
2. AggregatedSignal: Consensus signal for a symbol from multiple strategies
3. SignalBatch: Batch of aggregated signals for periodic processing
4. PendingOrderBatch: Orders waiting for HITL approval
5. AutonomousOrderApproval: Approval/rejection request model
6. AutonomousOrderStatus: Status response for autonomous orders
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class StrategySignal(BaseModel):
    """Individual strategy signal (from strategy_results table)."""

    signal_id: int = Field(description="Primary key from strategy_results table")
    symbol: str = Field(description="Stock ticker symbol")
    strategy_name: str = Field(description="Strategy that generated this signal")
    action: str = Field(description="Trading action: 'buy' | 'sell' | 'hold'")
    confidence: float = Field(ge=0.0, le=1.0, description="Signal confidence (0-1)")
    entry_price: Optional[float] = Field(None, description="Recommended entry price")
    stop_loss: Optional[float] = Field(None, description="Stop loss price")
    take_profit: Optional[float] = Field(None, description="Take profit target")
    reason: str = Field(description="Strategy reasoning for this signal")
    timestamp: datetime = Field(description="When the signal was generated")
    indicators: Dict[str, Any] = Field(default_factory=dict, description="Technical indicators used")
    statistics: Dict[str, Any] = Field(default_factory=dict, description="Statistical measures")


class AggregatedSignal(BaseModel):
    """Aggregated signal for a single symbol from multiple strategies.

    When a ticker has 2+ strategies configured in the watchlist, signals
    are aggregated using consensus logic. For single-strategy tickers,
    the original signal is used directly (no consensus required).
    """

    symbol: str = Field(description="Stock ticker symbol")
    action: str = Field(description="Aggregated action: 'buy' | 'sell' | 'hold'")
    confidence: float = Field(ge=0.0, le=1.0, description="Aggregated confidence (0-1)")
    strategies: List[str] = Field(description="List of contributing strategy names")
    strategy_count: int = Field(description="Number of strategies that contributed")
    consensus_reached: bool = Field(
        description="True if 2+ strategies agreed (only applicable when ticker has 2+ strategies)"
    )
    entry_price: float = Field(description="Recommended entry price")
    stop_loss: float = Field(description="Stop loss price")
    take_profit: float = Field(description="Take profit target")
    reason: str = Field(description="Combined reasoning from all contributing strategies")
    timestamp: datetime = Field(description="When aggregation occurred")
    source_signals: List[StrategySignal] = Field(
        description="Original signals for audit trail"
    )


class SignalBatch(BaseModel):
    """Batch of aggregated signals for periodic processing."""

    batch_id: str = Field(description="Unique ID for this batch (timestamp-based)")
    signals: List[AggregatedSignal] = Field(description="Aggregated signals ready for PM review")
    generated_at: datetime = Field(description="When this batch was generated")
    lookback_minutes: int = Field(description="Time window for signal fetching")
    min_confidence: float = Field(description="Minimum confidence threshold applied")
    total_signals_fetched: int = Field(description="Raw signal count before aggregation")
    total_signals_aggregated: int = Field(description="Final aggregated signal count")


class PendingOrderBatch(BaseModel):
    """Pending autonomous orders waiting for HITL approval."""

    thread_id: str = Field(description="LangGraph thread ID for this batch")
    batch_id: str = Field(description="Signal batch ID")
    signals: List[AggregatedSignal] = Field(description="Signals pending approval")
    created_at: datetime = Field(description="When this batch was created")
    expires_at: datetime = Field(description="Auto-reject if not approved by this time")
    status: str = Field(
        description="Status: 'pending' | 'approved' | 'rejected' | 'expired'"
    )


class AutonomousOrderApproval(BaseModel):
    """Request/Response for order approval or rejection."""

    thread_id: str = Field(description="Thread ID of the pending order batch")
    action: str = Field(description="Action to take: 'approve' | 'reject'")
    reason: Optional[str] = Field(None, description="Rejection reason (optional)")
    approved_symbols: Optional[List[str]] = Field(
        None,
        description="Partial approval: approve only these symbols (optional)"
    )


class AutonomousOrderStatus(BaseModel):
    """Status response for autonomous order request."""

    thread_id: str = Field(description="LangGraph thread ID")
    batch_id: str = Field(description="Signal batch ID")
    status: str = Field(
        description="Status: 'pending' | 'approved' | 'rejected' | 'executing' | 'completed' | 'expired'"
    )
    signals_count: int = Field(description="Total number of signals in batch")
    approved_count: Optional[int] = Field(None, description="Number of approved signals")
    executed_count: Optional[int] = Field(None, description="Number of executed orders")
    errors: List[str] = Field(default_factory=list, description="Error messages if any")