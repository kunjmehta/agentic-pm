"""Intent classifier node for the semi-auto multi-agent system.

Single-pass LLM classification using structured output (QueryIntent).
Returns a rich intent object capturing agent routing, ticker, dates, timeframe,
strategy, initial capital, and order subtype.

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
from src.server.agents import get_llm

logger = get_logger(__name__)


# ── Structured intent model ───────────────────────────────────────────────────


class QueryIntent(BaseModel):
    """Rich structured intent extracted from the user query.

    Attributes:
        agents: Which agent(s) should handle this query.
        intent: High-level routing intent for the graph.
        bt_workflow: Backtest sub-workflow type (only when intent includes backtest).
        ticker: Primary stock ticker extracted from query (e.g. "AAPL").
        secondary_tickers: Additional tickers when query involves multiple symbols.
        company: Full company name if mentioned (e.g. "Apple Inc").
        start_date: Start of the analysis/backtest window (YYYY-MM-DD).
        end_date: End of the analysis/backtest window (YYYY-MM-DD).
        timeframe: Bar timeframe for quant/backtest (e.g. "1Min", "5Min", "1Day").
        strategy: Trading strategy name when a backtest is requested.
        initial_capital: Starting capital for backtest if mentioned.
        order_subtype: Specific order operation for order intent.
        confidence: Classification confidence 0–1.
    """

    agents: List[Literal["portfolio", "quant", "backtester", "order"]] = Field(
        description=(
            "Which agents should handle this query. Pick ALL that apply:\n"
            "  ['portfolio']              — pure status/health/holdings/risk (no trade decision).\n"
            "  ['quant']                  — technical indicators/signals only, no buy/sell decision.\n"
            "  ['backtester']             — historical strategy simulation only.\n"
            "  ['order']                  — place/cancel/close/fetch orders, no analysis needed.\n"
            "  ['portfolio','quant']      — buy/sell/hold decision on a stock (need context + signals).\n"
            "  ['quant','order']          — analyse signal AND execute it.\n"
            "  ['portfolio','quant','order'] — full decision + execute.\n"
            "  ['quant','backtester']     — technical analysis + backtest.\n"
            "  ['portfolio','quant','backtester'] — comprehensive review.\n"
            "  ['portfolio','quant','backtester','order'] — full pipeline with execution."
        )
    )
    intent: Literal["portfolio", "quant", "backtest", "full_analysis", "order"] = Field(
        description=(
            "High-level routing intent — pick exactly one:\n"
            "  'portfolio'    — ONLY pure portfolio status: 'what are my holdings', "
            "'show positions', 'portfolio health'. NO trade decisions.\n"
            "  'quant'        — technical indicator/signal analysis WITHOUT a trade decision: "
            "'analyse AAPL RSI', 'show MACD for TSLA', 'check Bollinger bands'.\n"
            "  'backtest'     — historical strategy simulation: "
            "'backtest mean-reversion on AAPL', 'simulate momentum strategy'.\n"
            "  'full_analysis'— ANY buy/sell/hold decision on a stock: "
            "'should I buy VZ', 'is AAPL a good buy', 'recommend a trade for NVDA', "
            "'should I add to my Amazon position', 'is now a good time to enter TSLA', "
            "'full analysis of MSFT', 'comprehensive review'.\n"
            "  'order'        — explicit order command (NO analysis needed): "
            "'buy 50 AAPL at market', 'sell 10 TSLA', 'cancel all orders', "
            "'close my NVDA position', 'scale MSFT to 8%', 'show my open orders', "
            "'place a limit buy of GOOGL at $175', 'cancel order <uuid>'.\n"
            "  Do NOT use for buy/sell/hold decisions. "
            "'quant' — for technical indicator/signal analysis on a stock "
            "  when no buy/sell decision is asked ('analyse AAPL RSI'). "
            "'backtest' — for historical strategy simulation. "
            "'full_analysis' — for ANY buy/sell/hold decision on a stock "
            "  ('should I buy VZ', 'is AAPL a good buy', 'should I sell MSFT today', "
            "  'is now a good time to buy Tesla', 'recommend a trade for NVDA'). "
            "  Also use for: 'full analysis of X', 'comprehensive review', "
            "  queries combining portfolio context + quant signals."
        )
    )
    bt_workflow: Optional[Literal["A", "B", "C"]] = Field(
        default=None,
        description=(
            "Backtest sub-workflow. Set ONLY when intent='backtest' or agents includes 'backtester'.\n"
            "  A = strategy performance backtest (default when backtest is mentioned).\n"
            "  B = snapshot worth ('what would X shares be worth if held since DATE').\n"
            "  C = swap/replace positions ('what if I swapped X for Y')."
        ),
    )
    ticker: Optional[str] = Field(
        default=None,
        description=(
            "Uppercase stock ticker (e.g. 'AAPL'). "
            "Infer from well-known company names: "
            "Apple→AAPL, Microsoft→MSFT, Google/Alphabet→GOOGL, Amazon→AMZN, "
            "Meta/Facebook→META, Tesla→TSLA, Nvidia→NVDA, Netflix→NFLX, "
            "Verizon→VZ, AT&T→T, JPMorgan→JPM, Goldman→GS, Bank of America→BAC, "
            "Berkshire→BRK.B, Walmart→WMT, Target→TGT, Costco→COST, "
            "Intel→INTC, AMD→AMD, Qualcomm→QCOM, Broadcom→AVGO, "
            "Salesforce→CRM, Oracle→ORCL, IBM→IBM, Disney→DIS, "
            "PayPal→PYPL, Visa→V, Mastercard→MA, Exxon→XOM, Chevron→CVX, "
            "Boeing→BA, Shopify→SHOP, Coinbase→COIN, Palantir→PLTR, Snowflake→SNOW, "
            "Uber→UBER, Airbnb→ABNB, Pfizer→PFE, Moderna→MRNA. "
            "Null if no stock mentioned."
        ),
    )
    secondary_tickers: Optional[List[str]] = Field(
        default=None,
        description=(
            "Additional uppercase tickers when query mentions multiple stocks "
            "(e.g. 'compare AAPL and MSFT' → ticker='AAPL', secondary_tickers=['MSFT']). "
            "Null when only one stock is mentioned."
        ),
    )
    company: Optional[str] = Field(
        default=None,
        description="Full company name if explicitly written out (e.g. 'Apple Inc'). Null if only ticker given.",
    )
    start_date: Optional[str] = Field(
        default=None,
        description=(
            "Start of requested window YYYY-MM-DD. "
            "Resolve relative phrases using today's date: "
            "'last month'→first day of previous month, "
            "'this week'→Monday of current week, "
            "'YTD'/'year to date'→Jan 1 of current year, "
            "'Q1'→Jan 1, 'Q2'→Apr 1, 'Q3'→Jul 1, 'Q4'→Oct 1 of the year mentioned, "
            "'past 3 months'→today minus 90 days, "
            "'past 6 months'→today minus 180 days, "
            "'past year'→today minus 365 days. "
            "Null if truly not specifiable."
        ),
    )
    end_date: Optional[str] = Field(
        default=None,
        description=(
            "End of requested window YYYY-MM-DD. "
            "Defaults to today unless the user specifies otherwise. "
            "For quarter queries: 'Q1'→Mar 31, 'Q2'→Jun 30, 'Q3'→Sep 30, 'Q4'→Dec 31. "
            "Null only when start_date is also null."
        ),
    )
    timeframe: Optional[str] = Field(
        default=None,
        description=(
            "Bar timeframe for quant analysis or backtest. "
            "Map user language → canonical string: "
            "'1-minute'/'1min'/'minute chart' → '1Min', "
            "'5-minute'/'5min' → '5Min', "
            "'15-minute'/'15min' → '15Min', "
            "'hourly'/'1-hour'/'1h' → '1Hour', "
            "'daily'/'day'/'eod'/'1d' → '1Day'. "
            "Default to '1Min' for intraday strategies, '1Day' for swing/daily strategies. "
            "Null if truly ambiguous and no default applies."
        ),
    )
    strategy: Optional[str] = Field(
        default=None,
        description=(
            "Trading strategy for backtest or signal query. One of:\n"
            "  'mean-reversion'         — z-score mean reversion (intraday).\n"
            "  'vwap-reversion'         — VWAP band reversion (intraday).\n"
            "  'opening-range-breakout' — ORB (intraday).\n"
            "  'rsi-divergence'         — RSI divergence scalp (intraday).\n"
            "  'momentum-burst'         — volume/momentum burst (intraday).\n"
            "  'golden-cross'           — 50/200 MA crossover (daily).\n"
            "  'breakout-52w'           — 52-week high breakout (daily).\n"
            "  'mean-reversion-daily'   — daily z-score mean reversion.\n"
            "  'earnings-drift'         — post-earnings drift (daily).\n"
            "  'momentum'               — generic momentum.\n"
            "  'buy-and-hold'           — passive hold.\n"
            "Default to 'mean-reversion' for workflow A if user does not specify."
        ),
    )
    initial_capital: Optional[float] = Field(
        default=None,
        description=(
            "Starting capital for backtest in USD. "
            "Extract from phrases like '$25,000', '25k', '50 thousand', '100000'. "
            "Null if not mentioned."
        ),
    )
    order_subtype: Optional[Literal["place_market", "place_limit", "cancel", "cancel_all", "close", "close_all", "scale", "fetch"]] = Field(
        default=None,
        description=(
            "Specific order operation. Set when intent='order' or agents includes 'order':\n"
            "  'place_market' — 'buy/sell N shares at market'.\n"
            "  'place_limit'  — 'buy/sell N shares at $X limit'.\n"
            "  'cancel'       — 'cancel order <id>'.\n"
            "  'cancel_all'   — 'cancel all orders'.\n"
            "  'close'        — 'close my X position'.\n"
            "  'close_all'    — 'close everything', 'liquidate all'.\n"
            "  'scale'        — 'scale X to Y%', 'resize position'.\n"
            "  'fetch'        — 'show/list my orders', 'what orders are open'."
        ),
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Classification confidence 0–1.",
    )


# ── Classifier node ───────────────────────────────────────────────────────────

_REPLAY_PATTERNS = frozenset({
    "run again", "repeat", "do it again", "same query", "redo", "run it again",
    "same as before", "repeat that", "do the same",
})

_SYSTEM_PROMPT = (
    "You are an intent classifier for an autonomous portfolio management system. "
    "Extract a structured QueryIntent from the user query. "
    "Today's date is {today}. Be precise about all fields.\n\n"

    "══════════════════════════════════════════════════════\n"
    "INTENT ROUTING — pick exactly one intent:\n"
    "══════════════════════════════════════════════════════\n"
    "'portfolio'    — ONLY 'what are my positions', 'show portfolio health', 'what is my equity'. "
    "NO trade or stock-specific decisions.\n\n"

    "'quant'        — technical indicator/signal WITHOUT a buy/sell/hold conclusion: "
    "'show RSI for AAPL', 'MACD on TSLA 5-min', 'Bollinger bands MSFT'.\n\n"

    "'backtest'     — historical strategy simulation: "
    "'backtest X on Y from A to B', 'simulate momentum strategy', "
    "'what would mean-reversion return on NVDA last quarter'.\n\n"

    "'full_analysis'— ANY buy/sell/hold/trade DECISION on a stock: "
    "'should I buy VZ', 'is AAPL a good buy now', 'recommend a trade for NVDA', "
    "'should I add to my Amazon position', 'is Tesla worth entering', "
    "'full analysis of MSFT', 'comprehensive review of my NVDA holding'.\n\n"

    "'order'        — explicit order command needing NO analysis first: "
    "'buy 50 AAPL at market', 'sell 20 TSLA', 'cancel all my orders', "
    "'close my NVDA position', 'scale MSFT to 8% of portfolio', "
    "'place limit buy GOOGL at $175', 'show my open orders', "
    "'list recent trades', 'cancel order abc-123'.\n\n"

    "══════════════════════════════════════════════════════\n"
    "TIMEFRAME RULES:\n"
    "══════════════════════════════════════════════════════\n"
    "Intraday strategies (mean-reversion, vwap-reversion, orb, rsi-divergence, momentum-burst): default '1Min'.\n"
    "Daily/swing strategies (golden-cross, breakout-52w, mean-reversion-daily, earnings-drift): default '1Day'.\n"
    "If user says '5-minute chart' → '5Min', 'hourly' → '1Hour', 'daily bars' → '1Day'.\n\n"

    "══════════════════════════════════════════════════════\n"
    "DATE RESOLUTION (today = {today}):\n"
    "══════════════════════════════════════════════════════\n"
    "'YTD'/'year to date' → start=Jan 1 current year, end=today.\n"
    "'last month' → start=1st of previous month, end=last day of previous month.\n"
    "'this week' → start=Monday of current week, end=today.\n"
    "'Q1 YYYY' → start=YYYY-01-01, end=YYYY-03-31.\n"
    "'Q2 YYYY' → start=YYYY-04-01, end=YYYY-06-30.\n"
    "'Q3 YYYY' → start=YYYY-07-01, end=YYYY-09-30.\n"
    "'Q4 YYYY' → start=YYYY-10-01, end=YYYY-12-31.\n"
    "'past 3 months' → start=today-90, end=today.\n"
    "'past 6 months' → start=today-180, end=today.\n"
    "'past year' → start=today-365, end=today.\n"
    "If no date mentioned and not a backtest, omit start_date/end_date (let downstream fill defaults).\n"
)


def classify_intent(state: dict) -> dict:
    """Classify user intent and extract structured metadata from the query.

    Two-stage: LLM structured output → keyword fallback on failure.
    Post-processes bt_workflow, dates, timeframe, and strategy defaults.

    Args:
        state: Current GraphState dict.

    Returns:
        Partial state update: intent, symbol, bt_workflow, timestamp, _query_intent.
    """
    query: str = state.get("query", "")
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    default_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    # ── Replay substitution ───────────────────────────────────────────────────
    if any(p in query.lower() for p in _REPLAY_PATTERNS):
        prior = state.get("prior_turns") or []
        if prior:
            last_query = prior[-1].get("user_query", "")
            if last_query:
                logger.info(f"[classifier] replay → substituting: '{last_query[:60]}'")
                query = last_query

    logger.info(f"[classifier] query='{query[:80]}'")

    query_intent: Optional[QueryIntent] = None
    try:
        llm = get_llm("classifier").with_structured_output(QueryIntent, method="function_calling")

        query_intent = llm.invoke([
            {"role": "system", "content": _SYSTEM_PROMPT.format(today=today)},
            {"role": "user", "content": query},
        ])
        logger.info(
            f"[classifier] LLM → intent={query_intent.intent!r} "
            f"ticker={query_intent.ticker} tf={query_intent.timeframe} "
            f"bt_wf={query_intent.bt_workflow} "
            f"start={query_intent.start_date} end={query_intent.end_date} "
            f"strategy={query_intent.strategy} capital={query_intent.initial_capital} "
            f"order_sub={query_intent.order_subtype} conf={query_intent.confidence:.2f}"
        )

    except Exception as exc:
        logger.warning(f"[classifier] LLM failed ({exc}) — using keyword fallback")
        query_intent = _keyword_fallback(query, now, today, default_start)

    # ── Post-process: bt_workflow ─────────────────────────────────────────────
    if query_intent.intent in ("backtest", "full_analysis") and query_intent.bt_workflow is None:
        if "backtester" in query_intent.agents:
            ql = query.lower()
            if any(k in ql for k in ("swap", "replace", "switch")):
                query_intent.bt_workflow = "C"
            elif any(k in ql for k in ("worth", "held", "holding", "if i had")):
                query_intent.bt_workflow = "B"
            else:
                query_intent.bt_workflow = "A"
            logger.debug(f"[classifier] bt_workflow inferred → {query_intent.bt_workflow!r}")

    # ── Post-process: date defaults (only for analysis/backtest) ──────────────
    if query_intent.intent in ("backtest", "quant", "full_analysis"):
        if query_intent.start_date is None:
            query_intent.start_date = default_start
        if query_intent.end_date is None:
            query_intent.end_date = today

    # ── Post-process: strategy default ───────────────────────────────────────
    if query_intent.bt_workflow == "A" and query_intent.strategy is None:
        query_intent.strategy = "mean-reversion"

    # ── Post-process: timeframe default ──────────────────────────────────────
    if query_intent.timeframe is None and query_intent.intent in ("quant", "backtest", "full_analysis"):
        _daily_strategies = {"golden-cross", "breakout-52w", "mean-reversion-daily", "earnings-drift"}
        if (query_intent.strategy or "") in _daily_strategies:
            query_intent.timeframe = "1Day"
        elif query_intent.intent in ("quant", "full_analysis"):
            query_intent.timeframe = "1Min"

    return {
        "intent": query_intent.intent,
        "symbol": query_intent.ticker,
        "bt_workflow": query_intent.bt_workflow,
        "timestamp": now.isoformat(),
        "_query_intent": query_intent.model_dump(),
    }


# ── Keyword fallback ──────────────────────────────────────────────────────────

_BT_KEYWORDS = frozenset({
    "backtest", "simulate", "historical", "back-test", "backtesting",
    "what if", "how would", "what would", "if i had", "past data",
    "historical performance", "strategy performance",
})
_QUANT_KEYWORDS = frozenset({
    "analyze", "analyse", "analysis", "technical", "indicator", "indicators",
    "rsi", "macd", "bollinger", "momentum", "mean reversion", "signal", "signals",
    "volatility", "z-score", "vwap", "volume", "obv", "candlestick", "pattern",
    "support", "resistance", "moving average", "ema", "sma", "bands",
})
_PORT_KEYWORDS = frozenset({
    "portfolio", "status", "positions", "health", "equity", "cash", "holdings",
    "my stocks", "my holdings", "buying power", "unrealized", "risk parameters",
})
_DECISION_KEYWORDS = frozenset({
    "should i buy", "should i sell", "should i add", "should i get", "should i invest",
    "should i hold", "should i exit", "should i take profit", "should i close",
    "good buy", "good time to buy", "good time to sell", "right time to buy",
    "is it worth buying", "worth buying", "worth getting", "worth entering",
    "recommend a trade", "trade recommendation", "entry point", "entry signal",
    "buy signal", "sell signal", "is now a good time", "good entry",
    "should i increase", "should i reduce", "should i trim",
    "full analysis", "comprehensive review", "deep dive",
})
_ORDER_KEYWORDS = frozenset({
    "buy ", "sell ", "place order", "place a ", "market order", "limit order",
    "cancel order", "cancel all", "cancel my", "close position", "close my",
    "close all", "liquidate", "scale position", "scale to", "resize",
    "list orders", "show orders", "open orders", "fetch orders", "my orders",
})
# Explicit quantity-based trade or management commands
_EXPLICIT_ORDER_RE = re.compile(
    r"\b(buy|sell)\s+\d+\s+shares?\b"
    r"|\b(buy|sell)\s+\$?\d[\d,]*\s+(worth|of)\b"
    r"|\bplace\s+(a\s+)?(market|limit)\s+order\b"
    r"|\bcancel\s+(all|order)\b"
    r"|\bclose\s+(my|all|the|entire)\b"
    r"|\bscale\s+\w+\s+to\s+\d",
    re.IGNORECASE,
)

_TICKER_STOPS = frozenset({
    # Articles / pronouns / prepositions
    "I", "A", "AN", "THE", "AND", "OR", "FOR", "IN", "ON", "AT", "TO",
    "BY", "OF", "IF", "MY", "IT", "IS", "BE", "DO", "NO", "UP", "US",
    "AS", "SO", "WE", "HE", "ME", "GO",
    # Common financial words that look like tickers
    "ETF", "RSI", "OBV", "MACD", "EMA", "SMA", "VWAP", "ATR", "ADX",
    "IPO", "YTD", "AUM", "APR", "APY",
    # Action words
    "BUY", "SELL", "HOLD", "STOP", "ADD", "GET", "SET", "RUN", "USE",
    "NOW", "NEW", "OLD", "END", "DUE", "MAX", "MIN", "ALL", "ANY",
    # Market / price words
    "USD", "NYSE", "LOW", "HIGH", "OPEN", "LAST", "CLOSE", "GOOD", "BAD",
    "NET", "PNL", "ROI", "CAP", "LOT", "EOD", "DAY", "QTY", "ASK", "BID",
    # Strategy / indicator abbreviations
    "MA", "BB", "ORB", "VIX", "PE", "EPS", "FCF", "DCF",
    # Misc
    "OK", "PM", "AM", "MR", "DR", "CEO", "CFO", "COO", "CTO",
})
_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")
_DATE_ISO_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_MONEY_RE = re.compile(r"\$?([\d,]+(?:\.\d+)?)\s*([kKmMbB]?)\s*(?:dollar|usd)?", re.IGNORECASE)
_QUARTER_RE = re.compile(r"\bq([1-4])\s*(\d{4})\b", re.IGNORECASE)
_PAST_N_RE = re.compile(r"\bpast\s+(\d+)\s+(day|week|month|year)s?\b", re.IGNORECASE)

_COMPANY_MAP: dict[str, str] = {
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "meta": "META", "facebook": "META", "tesla": "TSLA",
    "nvidia": "NVDA", "netflix": "NFLX", "verizon": "VZ", "at&t": "T",
    "jpmorgan": "JPM", "jp morgan": "JPM", "goldman": "GS", "goldman sachs": "GS",
    "bank of america": "BAC", "berkshire": "BRK.B", "walmart": "WMT",
    "target": "TGT", "costco": "COST", "intel": "INTC", "amd": "AMD",
    "qualcomm": "QCOM", "broadcom": "AVGO", "salesforce": "CRM",
    "oracle": "ORCL", "ibm": "IBM", "disney": "DIS", "comcast": "CMCSA",
    "spotify": "SPOT", "paypal": "PYPL", "visa": "V", "mastercard": "MA",
    "exxon": "XOM", "chevron": "CVX", "conocophillips": "COP",
    "johnson": "JNJ", "pfizer": "PFE", "moderna": "MRNA",
    "unitedhealth": "UNH", "cvs": "CVS", "boeing": "BA",
    "caterpillar": "CAT", "deere": "DE", "shopify": "SHOP",
    "square": "SQ", "block": "SQ", "coinbase": "COIN", "robinhood": "HOOD",
    "uber": "UBER", "lyft": "LYFT", "airbnb": "ABNB", "doordash": "DASH",
    "palantir": "PLTR", "snowflake": "SNOW", "datadog": "DDOG",
    "crowdstrike": "CRWD", "zscaler": "ZS", "okta": "OKTA",
    "arm": "ARM", "asml": "ASML", "taiwan semiconductor": "TSM", "tsmc": "TSM",
}


def _resolve_relative_dates(
    query_lower: str,
    now: datetime,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve natural language date phrases to YYYY-MM-DD strings.

    Args:
        query_lower: Downcased user query.
        now: Current UTC datetime.

    Returns:
        Tuple of (start_date, end_date), either may be None.
    """
    today_str = now.strftime("%Y-%m-%d")

    if "ytd" in query_lower or "year to date" in query_lower:
        return f"{now.year}-01-01", today_str

    qm = _QUARTER_RE.search(query_lower)
    if qm:
        q, yr = int(qm.group(1)), int(qm.group(2))
        q_starts = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}
        q_ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
        return f"{yr}-{q_starts[q]}", f"{yr}-{q_ends[q]}"

    pm = _PAST_N_RE.search(query_lower)
    if pm:
        n, unit = int(pm.group(1)), pm.group(2).lower()
        delta_map = {"day": 1, "week": 7, "month": 30, "year": 365}
        days = n * delta_map.get(unit, 1)
        return (now - timedelta(days=days)).strftime("%Y-%m-%d"), today_str

    if "last month" in query_lower:
        first_of_this = now.replace(day=1)
        last_of_prev = first_of_this - timedelta(days=1)
        first_of_prev = last_of_prev.replace(day=1)
        return first_of_prev.strftime("%Y-%m-%d"), last_of_prev.strftime("%Y-%m-%d")

    if "this week" in query_lower:
        monday = now - timedelta(days=now.weekday())
        return monday.strftime("%Y-%m-%d"), today_str

    if "last week" in query_lower:
        last_monday = now - timedelta(days=now.weekday() + 7)
        last_sunday = last_monday + timedelta(days=6)
        return last_monday.strftime("%Y-%m-%d"), last_sunday.strftime("%Y-%m-%d")

    if "this year" in query_lower:
        return f"{now.year}-01-01", today_str

    if "last year" in query_lower:
        return f"{now.year - 1}-01-01", f"{now.year - 1}-12-31"

    return None, None


def _parse_capital(query: str) -> Optional[float]:
    """Extract starting capital USD amount from a backtest query.

    Args:
        query: Raw user query.

    Returns:
        Float USD amount or None.
    """
    for m in _MONEY_RE.finditer(query):
        try:
            raw = float(m.group(1).replace(",", ""))
            suffix = m.group(2).lower()
            if suffix == "k":
                raw *= 1_000
            elif suffix == "m":
                raw *= 1_000_000
            if raw >= 100:   # ignore price references like "$5"
                return raw
        except ValueError:
            continue
    th = re.search(r"(\d+(?:\.\d+)?)\s+thousand", query, re.IGNORECASE)
    if th:
        return float(th.group(1)) * 1_000
    return None


def _infer_timeframe(query_lower: str) -> Optional[str]:
    """Infer canonical bar timeframe from free-text query.

    Args:
        query_lower: Downcased user query.

    Returns:
        Canonical timeframe string (e.g. '1Min', '1Day') or None.
    """
    _TF_MAP = [
        (re.compile(r"\b1[\s-]?min|\b1[\s-]?minute|\bminute chart\b"), "1Min"),
        (re.compile(r"\b5[\s-]?min|\b5[\s-]?minute"), "5Min"),
        (re.compile(r"\b15[\s-]?min|\b15[\s-]?minute"), "15Min"),
        (re.compile(r"\b1[\s-]?hour|\bhourly\b|\b1[\s-]?hr\b"), "1Hour"),
        (re.compile(r"\bdaily\b|\bday chart\b|\b1[\s-]?day\b|\beod\b"), "1Day"),
    ]
    for pattern, tf in _TF_MAP:
        if pattern.search(query_lower):
            return tf
    return None


def _keyword_fallback(
    query: str,
    now: datetime,
    today: str,
    default_start: str,
) -> QueryIntent:
    """Fast keyword-based classification used when LLM is unavailable.

    Args:
        query: Raw user query.
        now: Current UTC datetime.
        today: Today's date YYYY-MM-DD.
        default_start: Fallback start date YYYY-MM-DD.

    Returns:
        QueryIntent populated from heuristics.
    """
    ql = query.lower()

    has_bt = any(kw in ql for kw in _BT_KEYWORDS)
    has_quant = any(kw in ql for kw in _QUANT_KEYWORDS)
    has_port = any(kw in ql for kw in _PORT_KEYWORDS)
    has_decision = any(kw in ql for kw in _DECISION_KEYWORDS)
    has_order_kw = any(kw in ql for kw in _ORDER_KEYWORDS)
    has_explicit_order = bool(_EXPLICIT_ORDER_RE.search(query))

    # ── Intent + agents ───────────────────────────────────────────────────────
    order_subtype: Optional[str] = None
    agents: list
    if has_explicit_order or (has_order_kw and not has_decision and not has_quant):
        intent = "order"
        agents = ["order"]
        if has_port:
            agents.insert(0, "portfolio")
        if re.search(r"\bcancel\s+all\b", ql):
            order_subtype = "cancel_all"
        elif re.search(r"\bcancel\b", ql):
            order_subtype = "cancel"
        elif re.search(r"\bclose\s+all\b|\bliquidate\s+all\b|\bclose\s+everything\b", ql):
            order_subtype = "close_all"
        elif re.search(r"\bclose\b", ql):
            order_subtype = "close"
        elif re.search(r"\bscale\b|\bresize\b", ql):
            order_subtype = "scale"
        elif re.search(r"\blist\b|\bshow\b|\bfetch\b|\bmy orders\b|\bopen orders\b", ql):
            order_subtype = "fetch"
        elif re.search(r"\blimit\b", ql):
            order_subtype = "place_limit"
        else:
            order_subtype = "place_market"
    elif has_decision:
        intent = "full_analysis"
        agents = ["portfolio", "quant"]
        if has_bt:
            agents.append("backtester")
        if has_order_kw:
            agents.append("order")
    elif has_bt and has_quant:
        intent, agents = "full_analysis", ["quant", "backtester"]
    elif has_bt:
        intent, agents = "backtest", ["backtester"]
    elif has_quant:
        intent, agents = "quant", ["quant"]
    elif has_port:
        intent, agents = "portfolio", ["portfolio"]
    else:
        intent, agents = "portfolio", ["portfolio"]

    # ── Backtest workflow ─────────────────────────────────────────────────────
    bt_workflow = None
    if has_bt or "backtester" in agents:
        if any(k in ql for k in ("swap", "replace", "switch")):
            bt_workflow = "C"
        elif any(k in ql for k in ("worth", "held", "holding", "if i had")):
            bt_workflow = "B"
        else:
            bt_workflow = "A"

    # ── Ticker ────────────────────────────────────────────────────────────────
    ticker = None
    for name, sym in sorted(_COMPANY_MAP.items(), key=lambda x: -len(x[0])):
        if name in ql:
            ticker = sym
            break
    if ticker is None:
        for m in _TICKER_RE.finditer(query):
            c = m.group(1)
            if c not in _TICKER_STOPS:
                ticker = c
                break

    # ── Dates ─────────────────────────────────────────────────────────────────
    iso_dates = _DATE_ISO_RE.findall(query)
    if len(iso_dates) >= 2:
        start_date, end_date = iso_dates[0], iso_dates[1]
    elif len(iso_dates) == 1:
        start_date, end_date = iso_dates[0], today
    else:
        start_date, end_date = _resolve_relative_dates(ql, now)
        if start_date is None:
            start_date = default_start if intent in ("backtest", "quant", "full_analysis") else None
            end_date = today if start_date is not None else None

    # ── Timeframe ─────────────────────────────────────────────────────────────
    timeframe = _infer_timeframe(ql)

    # ── Strategy ─────────────────────────────────────────────────────────────
    strategy_map = [
        (("vwap",), "vwap-reversion"),
        (("opening range", "orb"), "opening-range-breakout"),
        (("rsi divergence",), "rsi-divergence"),
        (("momentum burst",), "momentum-burst"),
        (("golden cross", "golden-cross", r"50.*200", r"200.*50"), "golden-cross"),
        (("52.week", "52w", "52-week.*breakout", "breakout.*52"), "breakout-52w"),
        (("earnings drift",), "earnings-drift"),
        (("mean reversion daily", "daily mean reversion"), "mean-reversion-daily"),
        (("mean reversion", "mean-reversion", "z-score", "z score"), "mean-reversion"),
        (("momentum",), "momentum"),
        (("buy and hold", "buy-and-hold"), "buy-and-hold"),
    ]
    strategy = None
    for patterns, strat in strategy_map:
        if any(re.search(p, ql) for p in patterns):
            strategy = strat
            break
    if strategy is None and bt_workflow == "A":
        strategy = "mean-reversion"

    # ── Initial capital ───────────────────────────────────────────────────────
    initial_capital = _parse_capital(query)

    return QueryIntent(
        agents=agents,
        intent=intent,
        bt_workflow=bt_workflow,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        timeframe=timeframe,
        strategy=strategy,
        initial_capital=initial_capital,
        order_subtype=order_subtype,
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

