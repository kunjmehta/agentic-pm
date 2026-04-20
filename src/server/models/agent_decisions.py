"""PM decision models for order execution planning.

Extracted from pm_decision_node.py to live in models/ alongside other LLM output types.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class OrderSignal(BaseModel):
    """A single actionable order signal derived from analysis results."""

    symbol: str = Field(description="Ticker symbol, e.g. 'AAPL'")
    action: Literal["buy", "sell", "hold"] = Field(
        description="Recommended action based on analysis"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Signal confidence between 0 and 1"
    )
    suggested_qty: Optional[int] = Field(
        default=None,
        description="Optional number of shares to trade; None if sizing is deferred",
    )


class PMDecision(BaseModel):
    """PM's structured order decision after reviewing analysis results."""

    should_execute_orders: bool = Field(
        description=(
            "True only when analysis results contain a clear, high-confidence signal "
            "AND portfolio risk is acceptable. False for hold, insufficient data, or "
            "pure informational queries."
        )
    )
    order_rationale: str = Field(
        description="1-2 sentence explanation of the order decision for the user"
    )
    order_signals: List[OrderSignal] = Field(
        default_factory=list,
        description="Concrete signals to pass to order_reasoning_node. "
        "Only populated when should_execute_orders=True.",
    )
