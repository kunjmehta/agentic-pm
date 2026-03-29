---
name: delegation
description: "Delegate technical analysis to Quant Analyst or strategy backtesting to Backtester agent. USE WHEN: user requests indicators, buy/sell signals (quant), or backtest/simulation (backtester). NOT FOR: portfolio data or health checks — handle those directly."
license: MIT
metadata:
  author: agentic-trader
  version: "1.0"
allowed-tools: bash
---

# agent-delegation

Delegate specialized tasks to the Quant Analyst agent (technical analysis) or Backtester agent (historical simulation).

## When to Use

✅ USE this skill when delegating to Quant Analyst:
- "Analyze AAPL for a buy signal"
- "What are the RSI and MACD for TSLA?"
- "Run mean reversion strategy on NVDA"
- "Should I buy MSFT? (technical view)"

✅ USE this skill when delegating to Backtester:
- "Backtest mean-reversion on AAPL Jan 2024" (after data verified)
- "Compare strategies on TSLA"
- "What would my portfolio be worth if I held from Jan 15?"

## When NOT to Use

❌ DO NOT use this skill when:
- User asks about portfolio values or positions → call `get_portfolio_status` / `get_positions_summary` tools directly
- User asks about risk or health → call `check_portfolio_health` tool directly
- Data is not yet fetched before backtesting → run `datamanagement` skill first

## Quick Responses

| User says | Command |
|---|---|
| "Analyze AAPL for buy signal" | `python src/agentic/agents/portfolio/skills/delegation/delegation.py --agent quant --query "Analyze AAPL for buy signal"` |
| "Run mean reversion on TSLA" | `python src/agentic/agents/portfolio/skills/delegation/delegation.py --agent quant --query "Run mean reversion strategy on TSLA"` |
| "Backtest momentum on AAPL Jan 2024" | `python src/agentic/agents/portfolio/skills/delegation/delegation.py --agent backtester --query "Backtest momentum on AAPL from 2024-01-01 to 2024-01-31"` |

## Important Rules
- Always check/fetch data BEFORE delegating to backtester
- Pass `thread_id` for conversation continuity
- Do NOT delegate to Quant for data fetching — handle data via `datamanagement` skill
