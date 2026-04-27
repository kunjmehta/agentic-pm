"""Pydantic models for LLM-generated analyst summaries."""

from typing import List, Literal
from pydantic import BaseModel, Field


class AnalystSummaryResult(BaseModel):
    """Structured output from the analyst summary LLM call.

    Produced every 10 minutes per ticker by the ETL analyst service.
    The LLM receives the past 10-minute bars, computed indicators, strategy
    signals, and the rolling day-so-far context, then fills in these fields.

    Attributes:
        summary: Narrative paragraph describing current market conditions.
        trend: Top-level directional label for the 10-minute window.
        trend_reasoning: 1-2 sentence rationale supporting the trend label.
        key_signals: Up to 4 bullet-point observations from the data.
        confidence: LLM's confidence in the trend assessment.
    """

    summary: str = Field(
        description=(
            "2-4 sentence narrative describing price action, volume, and momentum "
            "observed in the past 10 minutes for this ticker."
        )
    )
    trend: Literal["bullish", "bearish", "neutral", "volatile"] = Field(
        description=(
            "Top-level trend label for the 10-minute window. "
            "'volatile' means large moves without clear direction."
        )
    )
    trend_reasoning: str = Field(
        description=(
            "1-2 sentences explaining why this trend label was chosen, "
            "referencing specific indicators or signal patterns."
        )
    )
    key_signals: List[str] = Field(
        description=(
            "Up to 4 short bullet-point observations (e.g. 'RSI crossed 70', "
            "'Volume 2.5x above average'). Each item is a single concise sentence."
        ),
        max_length=4,
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description=(
            "Confidence in the trend assessment. 'high' when multiple signals agree, "
            "'low' when signals are mixed or data is sparse."
        )
    )


__all__ = ["AnalystSummaryResult"]
