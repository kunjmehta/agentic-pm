---
name: portfoliomanagement
description: "Comprehensive portfolio management reference: status, health, data management, and delegation. USE WHEN: you need a single reference for all portfolio manager capabilities. NOT FOR: direct execution — use the individual targeted skills or tools for each specific action."
license: MIT
compatibility: Requires Alpaca API, DuckDB, Portfolio Manager agent
metadata:
  author: agentic-trader
  version: "1.0"
allowed-tools: bash
---

# portfoliomanagement

Comprehensive reference for all Portfolio Manager capabilities. Use individual skills for each action; consult this file when you need a complete capability overview.

## When to Use

✅ USE this skill when:
- You need to understand the full set of portfolio manager capabilities
- Planning a multi-step workflow that spans status + health + delegation
- Onboarding or debugging — need to see all available functions

## When NOT to Use

❌ DO NOT use this skill for individual actions — use the targeted skills instead:
- Portfolio values/positions → `portfoliostatus` skill or `get_portfolio_status` / `get_positions_summary` tools
- Risk validation → `health` skill or `check_portfolio_health` tool
- Data check/fetch → `datamanagement` skill
- Technical analysis delegation → `delegation` skill or `delegate_to_quant_analyst` tool
- Backtest delegation → `delegation` skill or `delegate_to_backtester` tool

## Capability Overview

| Capability | Tool / Skill | Trigger |
|---|---|---|
| Account equity, cash, buying power | `get_portfolio_status()` | "status", "equity", "cash" |
| Position details, P&L | `get_positions_summary()` | "positions", "holdings", "P&L" |
| Risk validation | `check_portfolio_health()` | "health", "risk", "violations" |
| Technical analysis | `delegate_to_quant_analyst()` | "analyze", "RSI", "MACD", "signal" |
| Strategy backtest | `delegate_to_backtester()` | "backtest", "simulate", "compare" |
| Data check | `check_data_availability()` | "check data" |
| Data fetch | `fetch_historical_data()` | "fetch data", "download" |

## Standard Workflows

### Portfolio Status Check
```
1. get_portfolio_status() → equity, cash, buying power
2. check_portfolio_health() → risk validation
3. Respond with status and violations
```

### Technical Analysis Request
```
1. delegate_to_quant_analyst(query) → indicators + signal
2. Respond with analysis + risk context
```

### Backtest Workflow
```
1. check_data_availability(symbol, start, end) → available=true/false
2. If false: fetch_historical_data(symbol, start, end)
3. delegate_to_backtester(query) → performance metrics
4. Interpret and respond
```

## Risk Parameters (Defaults)

| Parameter | Default |
|---|---|
| Position concentration | 10% max |
| Position size | 1,500 shares max |
| Daily loss limit | 5% (middleware-enforced) |
| Cash reserve | 5% minimum |
| Max daily trades | 10 |
