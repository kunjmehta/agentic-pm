"""Structured intent model for the classifier node.

Extracted from classifier.py to live in models/ alongside other LLM output types.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


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
