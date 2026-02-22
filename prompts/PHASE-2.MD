Phase 2: Quant Analyst DeepAgent Design
1. Agent Definition

The Quant Analyst is a Langchain `deepagent` designed to transform raw market data into actionable "Investment Intelligence." It operates on two triggers: Temporal (every 30 mins) and On-Demand (User/Portfolio Manager queries).

For Claude: Langchain documentation is available via MCP. Follow the feature -> test -> review -> approval approach

1.1 Middleware Stack

The agent utilizes a functional middleware wrapper to intercept calls:

    MarketHoursGuard: Rejects execution if NYSE_OPEN is false (unless in backtest_mode).

    TracingMiddleware: Captures internal thought blocks and tool outputs for debugging.

    Prettifier: Formats raw JSON tool outputs into human-readable Markdown before final delivery.

    Others TBD

2. Technical Indicator & Calculation Skills (SKILLS.md)

The agent is equipped with a specialized library of financial functions. These are categorized into Momentum, Value (Buffett/Graham), and Structure.
Category	Indicator	Logic / Tool Name
Momentum	MACD & RSI	calc_momentum_package (EMA 12/26, Signal 9).
Volatility	Bollinger Bands	calc_volatility_bands (20-day SMA ± 2SD).
Volume	OBV & Net Volume	calc_volume_flow (On-Balance Volume trends).
Value (Graham)	Margin of Safety	calc_graham_intrinsic_value (V=YEPS×(8.5+2g)×4.4​).
Structure	Candlestick Patterns	analyze_candle_structure (Engulfing, Doji, Spreads).

Calculate any other metrics like growth rate that are required. MACD and other technical indicators can be ignored for a certain period if enough data is not available.

3. Data Access Layer (DAO Expansion)

A new table and DAO are required to persist the Analyst's "brain" (the summaries). Add the schema, DAO class for this

4. Tools (@tool)

Functions are required for the agent to use DAO to get the data from DB. These will be predefined tools, as opposed to SKILLS.md skills that are discoverable.

Functions are also required to access the brain / summary DAO and table

5. Sample Analyst Agent Logic

The agent follows a Recursive Summary Loop:

    Read Recent 30m Data: Fetch the last n rows from market_bars.

    Calculate Indicators: Compute the RSI/MACD/Bollinger values and others

    Generate Intermediate Summary: Produce a 30-minute text/JSON snippet persisted **to disk**

    Finalize (EOD): At 4:01 PM ET, the agent reads all 30-minute summaries from the persisted file, crunches them, and saves the EOD Report to DB

    TEMPORARY:   Build a minimal FastAPI stub for Portfolio Manager now as entry point into quant agent (Later, replace by portfolio manager agent)

6. Tracing & Streaming

To ensure White-Box AI, Phase 2 implements a custom BaseCallbackHandler:

    Token-by-Token Streaming: Direct to the user's stdout, including thoughts. Also create a reusable callback handler for the future to give these to the Portfolio Manager Agent

    Thought Traces: Logs which tools were called and why.

    Result Prettification: Uses Rich (Python library) or Markdown tables for final presentation.

7. Sample code -

For deep agents

```
# pip install -qU deepagents
from deepagents import create_deep_agent

def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"

agent = create_deep_agent(
    tools=[get_weather],
    system_prompt="You are a helpful assistant",
)

# Run the agent
agent.invoke(
    {"messages": [{"role": "user", "content": "what is the weather in sf"}]}
)
```

For SKILLS.md

```
---
name: langgraph-docs
description: Use this skill for requests related to LangGraph in order to fetch relevant documentation to provide accurate, up-to-date guidance.
license: MIT
compatibility: Requires internet access for fetching documentation URLs
metadata:
  author: langchain
  version: "1.0"
allowed-tools: fetch_url
---

# langgraph-docs

## Overview

This skill explains how to access LangGraph Python documentation to help answer questions and guide implementation.

## Instructions

### 1. Fetch the documentation index

Use the fetch_url tool to read the following URL:
https://docs.langchain.com/llms.txt

This provides a structured list of all available documentation with descriptions.

### 2. Select relevant documentation

Based on the question, identify 2-4 most relevant documentation URLs from the index. Prioritize:

- Specific how-to guides for implementation questions
- Core concept pages for understanding questions
- Tutorials for end-to-end examples
- Reference docs for API details

### 3. Fetch selected documentation

Use the fetch_url tool to read the selected documentation URLs.

### 4. Provide accurate guidance

After reading the documentation, complete the user's request.
```

Links to documentation:
https://docs.langchain.com/oss/python/deepagents/overview
https://docs.langchain.com/oss/python/deepagents/skills
https://docs.langchain.com/oss/python/deepagents/backends
