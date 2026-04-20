"""Singleton LLM client registry for all agent reasoning nodes.

All reasoning nodes share pre-warmed ChatOpenAI instances keyed by role.
This avoids creating a new HTTP client on every graph invocation and enables
connection reuse across requests.
"""

import sys
from pathlib import Path
from typing import Dict

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

# Module-level singleton cache: role → ChatOpenAI instance
_llm_cache: Dict[str, object] = {}

# Roles used across the graph
_ALL_ROLES = (
    "pm",           # portfolio_node.py
    "quant",        # quant_node.py
    "backtester",   # backtester_node.py
    "pm_review",    # pm_review_node.py
    "pm_decision",  # pm_decision_node.py
    "order",        # order_node.py
    "synthesizer",  # synthesizer.py
    "classifier",   # classifier.py
)


def get_llm(role: str = "default"):
    """Return the singleton ChatOpenAI for a given role, creating it on first call.

    All roles share the same model and temperature from config; the ``role`` key
    only differentiates the cached instance so that role-specific
    ``with_structured_output()`` calls don't interfere with each other.

    Args:
        role: Agent role identifier — one of pm, quant, backtester, pm_review,
              pm_decision, order, synthesizer, classifier.

    Returns:
        Shared ``ChatOpenAI`` instance for the given role.
    """
    if role not in _llm_cache:
        from langchain_openai import ChatOpenAI
        from src.common.utils import secrets, config

        _llm_cache[role] = ChatOpenAI(
            model=config.get("graph_api.reasoning_model", "gpt-4o-mini"),
            temperature=config.get("graph_api.model_temperature", 0.0),
            api_key=secrets.get("openai.api_key"),
        )
        logger.debug(f"[agents] initialized LLM singleton for role='{role}'")
    return _llm_cache[role]


def init_all_agents() -> None:
    """Pre-warm all LLM singletons at application startup.

    Called by lifespan.py immediately after graph compilation so that the first
    request does not incur client construction overhead.
    """
    for role in _ALL_ROLES:
        get_llm(role)
    logger.info(f"[agents] {len(_ALL_ROLES)} LLM singletons initialized: {_ALL_ROLES}")
