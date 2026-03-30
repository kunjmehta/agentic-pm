"""Intent classifier node for the semi-auto multi-agent system.

Single-pass LLM classification using structured output (QueryIntent).
Returns a rich intent object capturing agent routing, ticker, dates, and strategy.

Sets state fields: intent, symbol, bt_workflow, timestamp, _query_intent.
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Literal, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from pydantic import BaseModel, Field

from src.common.utils import get_logger

logger = get_logger(__name__)


# ── Structured intent model ───────────────────────────────────────────────────


class QueryIntent(BaseModel):
    """Rich structured intent extracted from the user query.

    Attributes:
        agents: Which agent(s) should handle this query.
        intent: High-level routing intent for the graph.
        bt_workflow: Backtest sub-workflow type (only when intent includes backtest).
        ticker: Primary stock ticker extracted from query (e.g. "AAPL").
        company: Full company name if mentioned (e.g. "Apple Inc").
        start_date: Start of the analysis/backtest window (YYYY-MM-DD).
        end_date: End of the analysis/backtest window (YYYY-MM-DD).
        strategy: Trading strategy name when a backtest is requested.
        confidence: Classification confidence 0–1.
    """

    agents: List[Literal["portfolio", "quant", "backtester"]] = Field(
        description=(
            "Which agents should handle this query. "
            "['portfolio'] for status/health, "
            "['quant'] for technical analysis only, "
            "['backtester'] for backtesting only, "
            "['quant', 'backtester'] for combined analysis+backtest, "
            "['portfolio', 'quant', 'backtester'] for full analysis."
        )
    )
    intent: Literal["portfolio", "quant", "backtest", "full_analysis"] = Field(
        description=(
            "High-level routing intent. "
            "'portfolio'=status/holdings/health, "
            "'quant'=technical indicators/signals, "
            "'backtest'=historical simulation/strategy test, "
            "'full_analysis'=comprehensive multi-agent review."
        )
    )
    bt_workflow: Optional[Literal["A", "B", "C"]] = Field(
        default=None,
        description=(
            "Backtest sub-workflow. Only set when intent is 'backtest' or agents includes 'backtester'. "
            "A=strategy performance backtest, "
            "B=snapshot worth (what would X shares be worth), "
            "C=swap/replace positions."
        ),
    )
    ticker: Optional[str] = Field(
        default=None,
        description="Uppercase stock ticker (e.g. 'AAPL'). Infer from company name if well-known. Null if none.",
    )
    company: Optional[str] = Field(
        default=None,
        description="Full company name if explicitly mentioned (e.g. 'Apple Inc'). Null if only ticker given.",
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Start of requested window YYYY-MM-DD. Extract from query if mentioned. Null if not specified.",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="End of requested window YYYY-MM-DD. Extract from query if mentioned. Null if not specified.",
    )
    strategy: Optional[str] = Field(
        default=None,
        description=(
            "Trading strategy for backtest. "
            "One of: 'mean-reversion', 'momentum', 'buy-and-hold', 'value'. "
            "Default to 'mean-reversion' for workflow A unless user specifies otherwise."
        ),
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Classification confidence 0–1.",
    )


# ── Classifier node ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are an intent classifier for an autonomous portfolio management system. "
    "Given the user query, extract a structured QueryIntent. "
    "Be precise about dates (YYYY-MM-DD), tickers (uppercase), and strategy names. "
    "When the user mentions a company name without a ticker, extract the company name "
    "and infer the ticker if it is well-known (e.g. Apple → AAPL). "
    "Today's date is {today}."
)


def classify_intent(state: dict) -> dict:
    """Classify user intent and extract structured metadata from the query.

    Uses a single LLM call with structured output (QueryIntent).
    Falls back to keyword heuristics if the LLM call fails.

    Args:
        state: Current GraphState dict containing 'query'.

    Returns:
        Partial state update: intent, symbol, bt_workflow, timestamp,
        and _query_intent (full QueryIntent dict for downstream nodes).
    """
    query: str = state.get("query", "")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    default_start = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    logger.info(f"[classifier] query='{query[:80]}'")

    query_intent: Optional[QueryIntent] = None
    try:
        from langchain_openai import ChatOpenAI
        from src.common.utils import secrets

        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            api_key=secrets.get("openai.api_key"),
        ).with_structured_output(QueryIntent, method="function_calling")

        query_intent = llm.invoke([
            {"role": "system", "content": _SYSTEM_PROMPT.format(today=today)},
            {"role": "user", "content": query},
        ])
        logger.info(
            f"[classifier] classified → intent={query_intent.intent!r} "
            f"ticker={query_intent.ticker} bt_workflow={query_intent.bt_workflow} "
            f"start={query_intent.start_date} end={query_intent.end_date} "
            f"strategy={query_intent.strategy} conf={query_intent.confidence:.2f}"
        )

    except Exception as exc:
        logger.warning(f"[classifier] LLM failed ({exc}) — using keyword fallback")
        query_intent = _keyword_fallback(query, today, default_start)

    # Apply defaults for unspecified dates and strategy
    if query_intent.start_date is None:
        query_intent.start_date = default_start
    if query_intent.end_date is None:
        query_intent.end_date = today
    if query_intent.bt_workflow == "A" and query_intent.strategy is None:
        query_intent.strategy = "mean-reversion"

    return {
        "intent": query_intent.intent,
        "symbol": query_intent.ticker,
        "bt_workflow": query_intent.bt_workflow,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "_query_intent": query_intent.model_dump(),
    }


# ── Keyword fallback ──────────────────────────────────────────────────────────

_BT_KEYWORDS = {
    "backtest", "simulate", "historical", "strategy", "what if",
    "how would", "perform", "past data",
}
_QUANT_KEYWORDS = {
    "analyze", "analysis", "technical", "indicator", "rsi", "macd",
    "bollinger", "momentum", "mean reversion", "signal", "volatility", "z-score", "vwap",
}
_PORT_KEYWORDS = {
    "portfolio", "status", "positions", "health", "equity", "cash", "holdings",
}
_TICKER_STOPS = {
    "I", "A", "AN", "THE", "AND", "OR", "FOR", "IN", "ON", "AT", "TO",
    "BY", "OF", "IF", "MY", "IT", "IS", "BE", "DO", "NO", "UP", "US",
    "ETF", "RSI", "OBV", "MACD", "EMA", "SMA", "VWAP", "ATR", "ADX",
    "BUY", "SELL", "HOLD", "STOP", "USD", "NYSE",
}
_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _keyword_fallback(query: str, today: str, default_start: str) -> QueryIntent:
    """Fast keyword-based classification used when LLM is unavailable.

    Args:
        query: Raw user query.
        today: Today's date YYYY-MM-DD.
        default_start: Fallback start date YYYY-MM-DD.

    Returns:
        QueryIntent populated from heuristics.
    """
    ql = query.lower()
    has_bt = any(kw in ql for kw in _BT_KEYWORDS)
    has_quant = any(kw in ql for kw in _QUANT_KEYWORDS)
    has_port = any(kw in ql for kw in _PORT_KEYWORDS)

    if has_bt and has_quant:
        intent, agents = "full_analysis", ["quant", "backtester"]
    elif has_bt:
        intent, agents = "backtest", ["backtester"]
    elif has_quant:
        intent, agents = "quant", ["quant"]
    elif has_port:
        intent, agents = "portfolio", ["portfolio"]
    else:
        intent, agents = "portfolio", ["portfolio"]

    bt_workflow = None
    if has_bt:
        if any(kw in ql for kw in {"swap", "replace"}):
            bt_workflow = "C"
        elif any(kw in ql for kw in {"worth", "held", "holding"}):
            bt_workflow = "B"
        else:
            bt_workflow = "A"

    ticker = None
    for m in _TICKER_RE.finditer(query):
        c = m.group(1)
        if c not in _TICKER_STOPS:
            ticker = c
            break

    dates = _DATE_RE.findall(query)
    start_date = dates[0] if len(dates) >= 1 else default_start
    end_date = dates[1] if len(dates) >= 2 else today

    strategy = None
    if "mean" in ql and "reversion" in ql:
        strategy = "mean-reversion"
    elif "momentum" in ql:
        strategy = "momentum"
    elif "buy" in ql and "hold" in ql:
        strategy = "buy-and-hold"
    elif bt_workflow == "A":
        strategy = "mean-reversion"

    return QueryIntent(
        agents=agents,
        intent=intent,
        bt_workflow=bt_workflow,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        strategy=strategy,
        confidence=0.6,
    )


# ── Functional test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_cases = [
        ("What is my portfolio status?",                                   "portfolio",     None,   None),
        ("Analyze AAPL RSI and Bollinger bands",                           "quant",        "AAPL",  None),
        ("Backtest mean-reversion on TSLA from 2026-01-01 to 2026-01-31", "backtest",     "TSLA",  "mean-reversion"),
        ("Full analysis on MSFT including backtest",                       "full_analysis", "MSFT",  None),
        ("What would NVDA be worth if held since 2025-01-01?",             "backtest",     "NVDA",  None),
    ]

    print("=" * 70)
    print("Semi-Auto Intent Classifier Tests")
    print("=" * 70)

    passed = 0
    for query, exp_intent, exp_ticker, exp_strategy in test_cases:
        result = classify_intent({"query": query})
        qi = result.get("_query_intent", {})
        ok_intent = result["intent"] == exp_intent
        ok_ticker = (exp_ticker is None) or (qi.get("ticker") == exp_ticker)
        status = "[OK]  " if (ok_intent and ok_ticker) else "[FAIL]"
        print(f"\n{status} {query[:65]}")
        print(f"         intent={result['intent']!r:18} ticker={qi.get('ticker')!r:8} "
              f"bt_workflow={qi.get('bt_workflow')!r:4} "
              f"start={qi.get('start_date')!r} end={qi.get('end_date')!r} "
              f"strategy={qi.get('strategy')!r}")
        if ok_intent and ok_ticker:
            passed += 1

    print(f"\n{'='*70}")
    print(f"Passed {passed}/{len(test_cases)} tests")

