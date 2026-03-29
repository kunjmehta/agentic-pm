"""Intent classifier node for the deterministic LangGraph agent.

Tier 1: keyword/regex matching (fast, deterministic).
Tier 2: LLM structured-output (only for ambiguous queries).

Sets state fields: intent, symbol, bt_workflow.
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.common.utils import get_logger

logger = get_logger(__name__)

# ── Keyword sets ────────────────────────────────────────────────────────────

BACKTEST_KEYWORDS = {
    "backtest", "simulate", "historical", "what if", "strategy",
    "past data", "snapshot worth", "swap positions", "swap",
    "what would", "be worth", "held since", "how would",
}

# Strong primary backtest signals — override quant tie
BACKTEST_PRIMARY = {"backtest", "simulate", "what if", "swap", "snapshot worth", "what would", "be worth"}

QUANT_KEYWORDS = {
    "analyze", "analysis", "technical", "indicator", "rsi", "macd",
    "bollinger", "momentum", "mean reversion", "signal", "volatility",
    "obv", "volume", "candlestick", "pattern", "z-score", "vwap",
}

PORTFOLIO_KEYWORDS = {
    "portfolio", "status", "positions", "health", "equity", "cash",
    "buying power", "p&l", "pnl", "holdings", "concentration",
}

# Backtest sub-workflow keyword sets
BT_WORKFLOW_A = {"backtest", "simulate", "strategy", "how would", "perform", "run backtest"}
BT_WORKFLOW_B = {"snapshot worth", "what would", "be worth", "held", "holding"}
BT_WORKFLOW_C = {"swap", "swap positions", "what if i swapped", "replace"}

# Ticker extraction: 1-5 uppercase letters that are not stop words
_TICKER_PATTERN = re.compile(r"\b([A-Z]{1,5})\b")
_TICKER_STOP = {
    "I", "A", "AN", "THE", "AND", "OR", "FOR", "IN", "ON", "AT", "TO",
    "BY", "OF", "IF", "MY", "IT", "IS", "BE", "DO", "NO", "UP", "US",
    "ETF", "RSI", "OBV", "MACD", "EMA", "SMA", "VWAP", "ATR", "ADX",
    "P&L", "PNL", "YTD", "MTD", "NYSE", "ETF", "ETF", "USD", "BUY",
    "SELL", "HOLD", "STOP",
}


def _extract_ticker(query: str) -> Optional[str]:
    """Extract first plausible stock ticker from query.

    Args:
        query: Raw user query string.

    Returns:
        Uppercase ticker string or None if not found.
    """
    for match in _TICKER_PATTERN.finditer(query):
        candidate = match.group(1)
        if candidate not in _TICKER_STOP and len(candidate) >= 2:
            return candidate
    return None


def _score_intent(query_lower: str) -> dict:
    """Score query against each intent keyword set.

    Args:
        query_lower: Lowercase query string.

    Returns:
        Dict mapping intent name to keyword hit count.
    """
    scores = {"backtest": 0, "quant": 0, "portfolio": 0}

    for kw in BACKTEST_KEYWORDS:
        if kw in query_lower:
            scores["backtest"] += 1

    for kw in QUANT_KEYWORDS:
        if kw in query_lower:
            scores["quant"] += 1

    for kw in PORTFOLIO_KEYWORDS:
        if kw in query_lower:
            scores["portfolio"] += 1

    return scores


def _classify_bt_workflow(query_lower: str) -> str:
    """Determine backtester sub-workflow A, B, or C.

    Args:
        query_lower: Lowercase query string.

    Returns:
        "A", "B", or "C" — defaults to "A" (strategy backtest).
    """
    c_score = sum(1 for kw in BT_WORKFLOW_C if kw in query_lower)
    b_score = sum(1 for kw in BT_WORKFLOW_B if kw in query_lower)

    if c_score > 0:
        return "C"
    if b_score > 0:
        return "B"
    return "A"


def _llm_classify(query: str) -> dict:
    """Tier 2: LLM structured-output for ambiguous queries.

    Args:
        query: Original user query string.

    Returns:
        Dict with keys: intent, symbol, bt_workflow, confidence.
    """
    try:
        from langchain_openai import ChatOpenAI
        from pydantic import BaseModel, Field as PydanticField

        class IntentClassification(BaseModel):
            """Structured output for intent classification."""

            intent: str = PydanticField(
                description=(
                    "One of: 'portfolio', 'quant', 'backtest', 'full_analysis'. "
                    "Use 'portfolio' for status/health queries, 'quant' for technical "
                    "analysis, 'backtest' for historical simulation, "
                    "'full_analysis' for comprehensive review."
                )
            )
            bt_workflow: Optional[str] = PydanticField(
                default=None,
                description=(
                    "Only set when intent=='backtest'. "
                    "'A'=strategy backtest, 'B'=snapshot worth, 'C'=swap positions."
                ),
            )
            symbol: Optional[str] = PydanticField(
                default=None,
                description="Stock ticker extracted from query, e.g. 'AAPL'. Null if none.",
            )
            confidence: float = PydanticField(
                description="Classification confidence between 0 and 1."
            )

        from src.common.utils import secrets
        llm = ChatOpenAI(
            model="gpt-5-mini",
            temperature=0,
            api_key=secrets.get("openai.api_key"),
        ).with_structured_output(IntentClassification)
        system = (
            "You are an intent classifier for a portfolio management system. "
            "Classify the user query and extract relevant fields."
        )
        result = llm.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ])
        return {
            "intent": result.intent,
            "bt_workflow": result.bt_workflow,
            "symbol": result.symbol,
            "confidence": result.confidence,
        }
    except Exception as exc:
        logger.warning(f"LLM classifier fallback due to: {exc}")
        return {"intent": "portfolio", "bt_workflow": None, "symbol": None, "confidence": 0.0}


def classify_intent(state: dict) -> dict:
    """Classify user intent and extract metadata from the query.

    Tier 1 (keyword) runs first; Tier 2 (LLM) only fires when
    the keyword scores are tied or zero.

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update with intent, symbol, bt_workflow keys.
    """
    query: str = state.get("query", "")
    query_lower = query.lower()

    logger.info(f"[classify_intent] query='{query[:80]}'")

    # ── Tier 1: keyword scoring ─────────────────────────────────────────────
    scores = _score_intent(query_lower)
    logger.debug(f"[classify_intent] scores={scores}")

    max_score = max(scores.values())
    top_intents = [k for k, v in scores.items() if v == max_score]

    intent: Optional[str] = None
    bt_workflow: Optional[str] = None
    symbol: Optional[str] = _extract_ticker(query)  # ticker extraction is tier-1 always

    # Check for explicit "full analysis" pattern
    if "full" in query_lower and "analysis" in query_lower:
        intent = "full_analysis"

    elif max_score > 0 and len(top_intents) == 1:
        # Unambiguous tier-1 hit
        intent = top_intents[0]

    elif max_score > 0 and len(top_intents) == 2:
        if "quant" in top_intents and "backtest" in top_intents:
            # Check if a primary backtest keyword is present — if so, treat as backtest
            has_primary_bt = any(kw in query_lower for kw in BACKTEST_PRIMARY)
            intent = "backtest" if has_primary_bt else "full_analysis"
        elif "quant" in top_intents and "portfolio" in top_intents:
            intent = "full_analysis"
        else:
            # Fall through to tier 2
            pass

    elif max_score > 0 and len(top_intents) == 3:
        # All three scored equally → full analysis
        intent = "full_analysis"

    if intent is None:
        # ── Tier 2: LLM fallback ────────────────────────────────────────────
        logger.info("[classify_intent] ambiguous → calling LLM tier 2")
        llm_result = _llm_classify(query)
        intent = llm_result["intent"]
        bt_workflow = llm_result.get("bt_workflow")
        if llm_result.get("symbol"):
            symbol = llm_result["symbol"]
        logger.info(f"[classify_intent] LLM classified as '{intent}' (conf={llm_result.get('confidence', '?')})")
    else:
        logger.info(f"[classify_intent] tier-1 classified as '{intent}'")

    # Determine backtest sub-workflow if needed
    if intent in ("backtest", "full_analysis") and bt_workflow is None:
        bt_workflow = _classify_bt_workflow(query_lower)
        logger.info(f"[classify_intent] bt_workflow='{bt_workflow}'")

    return {
        "intent": intent,
        "symbol": symbol,
        "bt_workflow": bt_workflow,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    """Functional test covering all four intent categories."""
    test_cases = [
        ("What is my portfolio status?", "portfolio", None),
        ("Analyze AAPL for buy signal", "quant", "AAPL"),
        ("Backtest mean-reversion on TSLA from 2026-01-01 to 2026-01-31", "backtest", "TSLA"),
        ("Full analysis on MSFT", "full_analysis", "MSFT"),
        ("What would my Jan 15 portfolio be worth today?", "backtest", None),
        ("What if I swapped AAPL for NVDA?", "backtest", "NVDA"),
    ]

    print("=" * 60)
    print("Intent Classifier Functional Tests")
    print("=" * 60)

    passed = 0
    for query, expected_intent, expected_symbol in test_cases:
        result = classify_intent({"query": query})
        got_intent = result["intent"]
        got_symbol = result.get("symbol")
        got_bt = result.get("bt_workflow")

        status = "[OK]" if got_intent == expected_intent else "[FAIL]"
        print(f"\n{status} Query: {query[:60]}")
        print(f"       Expected intent={expected_intent}, got={got_intent}")
        if expected_symbol:
            sym_ok = "[OK]" if got_symbol == expected_symbol else "[WARN]"
            print(f"       {sym_ok} Expected symbol={expected_symbol}, got={got_symbol}")
        if got_bt:
            print(f"       bt_workflow={got_bt}")

        if got_intent == expected_intent:
            passed += 1

    print(f"\n{'='*60}")
    print(f"Passed {passed}/{len(test_cases)} tests")
