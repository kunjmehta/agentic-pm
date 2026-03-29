---
name: datamanagement
description: "Check or fetch historical market data for backtesting. USE WHEN: user wants to verify data availability or download data before a backtest. NOT FOR: live portfolio data (use portfoliostatus) or running the actual backtest (delegate to Backtester)."
license: MIT
metadata:
  author: agentic-trader
  version: "1.0"
allowed-tools: bash
---

# data-management

Check if historical market data exists in the database or fetch it from the Alpaca API. Essential prerequisite before delegating backtest requests.

## When to Use

✅ USE this skill when:
- "Do we have data for AAPL in January 2024?"
- "Check data availability before backtesting"
- User requests a backtest → always check/fetch data BEFORE delegating to Backtester
- "Fetch historical data for TSLA from Jan to Feb"
- "Download MSFT data for last quarter"

## When NOT to Use

❌ DO NOT use this skill when:
- User wants live account data → use `portfoliostatus` skill
- Data check already confirmed `available=true` → skip fetch, proceed to delegation
- User wants to run the actual backtest → after fetching data, delegate to Backtester

## Quick Responses

| User says | Command |
|---|---|
| "Check AAPL data Jan 2024" | `python src/agentic/agents/portfolio/skills/datamanagement/data.py --action check --symbol AAPL --start 2024-01-01 --end 2024-01-31` |
| "Fetch TSLA data Jan–Feb 2024" | `python src/agentic/agents/portfolio/skills/datamanagement/data.py --action fetch --symbol TSLA --start 2024-01-01 --end 2024-02-28` |
| "Do we have MSFT data?" | `python src/agentic/agents/portfolio/skills/datamanagement/data.py --action check --symbol MSFT --start 2024-01-01 --end 2024-03-01` |

## Output Format

Check:
```json
{
  "available": true,
  "bar_count": 7800,
  "coverage": 98.5,
  "message": "Data available for AAPL from 2024-01-01 to 2024-01-31"
}
```

Fetch:
```json
{
  "status": "success",
  "bars_fetched": 7800,
  "date_range": "2024-01-01 to 2024-01-31",
  "message": "Successfully fetched 7800 bars for AAPL"
}
```

## Workflow

1. Call with `--action check` first
2. If `available=false`, call with `--action fetch`
3. After successful fetch, delegate to Backtester
