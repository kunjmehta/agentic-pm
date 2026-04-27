"""Context node for the trading multi-agent system.

Loads conversation history from PortfolioDAO before reasoning begins.
Resolves conversation_id and turn_number for multi-turn support.

Sets state fields: conversation_id, turn_number, prior_turns.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

_MAX_PRIOR_TURNS = 5


def _load_prior_turns(thread_id: str) -> List[Dict[str, Any]]:
    """Load recent interaction history for a thread from portfolio DB.

    Args:
        thread_id: Conversation thread UUID.

    Returns:
        List of interaction dicts (most recent last), empty list on failure.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        turns = dao.get_interaction_history(
            thread_id=thread_id,
            agent_name="semi_auto_pm",
            limit=_MAX_PRIOR_TURNS,
        )
        dao.close()
        logger.info(f"[context_node] loaded {len(turns)} prior turns for thread={thread_id}")
        return turns
    except Exception as exc:
        logger.warning(f"[context_node] failed to load prior turns: {exc}")
        return []


def _register_thread(thread_id: str) -> None:
    """Register thread in portfolio DB for expiry tracking.

    Args:
        thread_id: Conversation thread UUID.
    """
    try:
        from src.common.dao.portfolio_dao import PortfolioDAO
        dao = PortfolioDAO()
        dao.save_thread_id(thread_id)
        dao.close()
    except Exception as exc:
        logger.warning(f"[context_node] thread registration failed (non-critical): {exc}")


def context_node(state: dict) -> dict:
    """Load conversation context and resolve session identifiers.

    Populates:
    - conversation_id: generated if not already in state
    - turn_number: length of prior turns + 1
    - prior_turns: last N interactions from DB

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update with conversation_id, turn_number, prior_turns.
    """
    thread_id: str = state.get("thread_id", "unknown")

    # Resolve conversation_id
    conversation_id: str = state.get("conversation_id") or str(uuid.uuid4())

    # Register thread (idempotent)
    _register_thread(thread_id)

    # Load prior turns
    prior_turns = _load_prior_turns(thread_id)

    # Turn number = prior completed turns + 1
    turn_number = len(prior_turns) + 1

    logger.info(
        f"[context_node] thread={thread_id} conversation={conversation_id} "
        f"turn={turn_number} prior_turns={len(prior_turns)}"
    )

    return {
        "conversation_id": conversation_id,
        "turn_number": turn_number,
        "prior_turns": prior_turns,
    }


if __name__ == "__main__":
    """Functional test: load context for a test thread."""
    print("=" * 60)
    print("context_node Functional Test")
    print("=" * 60)

    result = context_node({
        "thread_id": "semi-auto-test-001",
        "conversation_id": None,
    })

    print(f"[OK] conversation_id generated: {result['conversation_id']}")
    print(f"[OK] turn_number: {result['turn_number']}")
    print(f"[OK] prior_turns count: {len(result['prior_turns'])}")

    assert result["conversation_id"] is not None
    assert result["turn_number"] >= 1
    assert isinstance(result["prior_turns"], list)

    # Test with existing conversation_id
    existing_conv_id = "existing-conv-001"
    result2 = context_node({
        "thread_id": "semi-auto-test-002",
        "conversation_id": existing_conv_id,
    })
    assert result2["conversation_id"] == existing_conv_id
    print(f"[OK] existing conversation_id preserved: {result2['conversation_id']}")

    print("\n[ALL OK] context_node tests passed")
