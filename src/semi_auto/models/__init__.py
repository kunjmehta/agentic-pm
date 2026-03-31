"""Pydantic models for the semi-auto multi-agent system."""

from src.semi_auto.models.task import AgentOutput, AgentReasoning, TaskItem, TaskList
from src.semi_auto.models.responses import (
    ApprovalRequest,
    ContentSection,
    ExecutionResult,
    MetricRow,
    SemiAutoQueryRequest,
    SemiAutoResponse,
    SynthesisResult,
    TaskPreviewResponse,
)
from src.semi_auto.models.skills import (
    BacktestInput,
    BacktestMetrics,
    BacktestOutput,
    CandleInput,
    CandleOutput,
    DataAvailabilityInput,
    HistoricalDataInput,
    MACDOutput,
    MeanReversionInput,
    MomentumInput,
    MomentumOutput,
    VolatilityInput,
    VolatilityOutput,
    VolumeInput,
    VolumeOutput,
)

__all__ = [
    # task models
    "TaskItem",
    "TaskList",
    "AgentOutput",
    "AgentReasoning",
    # response models
    "ExecutionResult",
    "TaskPreviewResponse",
    "ApprovalRequest",
    "SemiAutoResponse",
    "SemiAutoQueryRequest",
    # synthesis models
    "MetricRow",
    "ContentSection",
    "SynthesisResult",
    # skill input models
    "MomentumInput",
    "VolatilityInput",
    "VolumeInput",
    "CandleInput",
    "MeanReversionInput",
    "BacktestInput",
    "DataAvailabilityInput",
    "HistoricalDataInput",
    # skill output models
    "MACDOutput",
    "MomentumOutput",
    "VolatilityOutput",
    "VolumeOutput",
    "CandleOutput",
    "BacktestMetrics",
    "BacktestOutput",
]
