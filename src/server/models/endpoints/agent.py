"""Response models for agent and HITL endpoints."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class RejectResponse(BaseModel):
    """Response for POST /v1/reject/{thread_id}.

    Attributes:
        status: Always ``"cancelled"``.
        thread_id: Thread that was cancelled.
        message: Human-readable confirmation.
        timestamp: ISO-8601 UTC timestamp.
    """

    status: str = "cancelled"
    thread_id: str
    message: str
    timestamp: str


class ConversationResponse(BaseModel):
    """Response for GET /v1/conversations/{thread_id}.

    Attributes:
        thread_id: Requested thread UUID.
        turns: Interaction turn dicts up to ``limit``.
        count: Actual number of turns returned.
    """

    thread_id: str
    turns: List[Any] = Field(default_factory=list)
    count: int


class AgentStateResponse(BaseModel):
    """Response for GET /v1/agent/state/{thread_id}.

    Attributes:
        thread_id: Requested thread UUID.
        state: LangGraph checkpoint state values (sensitive fields stripped).
    """

    thread_id: str
    state: Dict[str, Any]


class RegistryResponse(BaseModel):
    """Response for GET /v1/registry.

    Attributes:
        registry: Map of function name → parameter schema.
        count: Number of registered functions.
    """

    registry: Dict[str, Any]
    count: int
