---
name: snapshot-worth
description: "Calculate what a historical portfolio snapshot would be worth at a future date (buy-and-hold forward valuation). USE WHEN: user asks what portfolio would be worth if held unchanged from a past date. NOT FOR: simulating trades (use backtest-strategy), swapping positions (use swap-positions), or comparing strategies (use run_strategy_comparison)."
license: MIT
compatibility: Requires portfolio_snapshots table with positions_json column
metadata:
  author: agentic-trader
  version: "1.0"
  category: portfolio-analysis
allowed-tools: bash
---

# snapshot-worth

Calculate what a historical portfolio snapshot would be worth at a future date, assuming all positions are held unchanged.

## When to Use

✅ USE this skill when:
- "What would my Jan 15 portfolio be worth today?"
- "If I had held my positions from Feb 1, what's the return?"
- "Calculate the opportunity cost of selling AAPL last month"
- "What's the current value of my portfolio from 2024-01-01?"
- User wants pure buy-and-hold forward valuation from an existing snapshot

## When NOT to Use

❌ DO NOT use this skill when:
- User wants to simulate actual trading decisions → use `backtest-strategy` skill
- User wants to swap/replace positions → use `swap-positions` skill
- No portfolio snapshot exists for that date → inform user and suggest saving one first
- User wants to compare multiple strategies → use `run_strategy_comparison` tool

## Quick Responses

| User says | Command |
|---|---|
| "Jan 15 portfolio worth today" | `python src/agentic/agents/backtester/skills/snapshot-worth/worth.py --snapshot_date 2024-01-15 --end_date 2024-03-25` |
| "Portfolio from Feb 1 worth at Feb 28" | `python src/agentic/agents/backtester/skills/snapshot-worth/worth.py --snapshot_date 2024-02-01 --end_date 2024-02-28` |

## Execution

```bash
python src/agentic/agents/backtester/skills/snapshot-worth/worth.py \
  --snapshot_date 2024-01-15 \
  --end_date 2024-02-15
```

## Output Format

Success:
```json
{
  "snapshot_date": "2024-01-15",
  "end_date": "2024-02-15",
  "initial_worth": 105000.00,
  "final_worth": 108500.00,
  "return_pct": 3.33,
  "return_dollars": 3500.00,
  "positions_at_end": {
    "AAPL": {"quantity": 100, "unrealized_pnl": 1500.0, "unrealized_pnl_pct": 10.0}
  }
}
```

Error:
```json
{
  "error": "No portfolio snapshot found near 2024-01-15",
  "suggestion": "Create a portfolio snapshot first or try a different date"
}
```

## Requirements
- Portfolio snapshot must exist in `portfolio_snapshots` table with `positions_json`
- `end_date` must be after `snapshot_date`
- Historical market data available for position symbols

## Notes
- Finds closest snapshot before `snapshot_date` (within 7 days)
- No trading simulation — pure buy-and-hold calculation
- Cash balance remains unchanged
