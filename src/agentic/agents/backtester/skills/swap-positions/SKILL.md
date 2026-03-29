---
name: swap-positions
description: "Simulate instantaneous position swaps in a historical snapshot and calculate resulting portfolio worth. USE WHEN: user asks 'what if I swapped X for Y', 'what if I had owned Z instead', or wants alternate-universe portfolio analysis. NOT FOR: actual buy/sell trade simulation (use backtest-strategy) or plain forward valuation without swaps (use snapshot-worth)."
license: MIT
compatibility: Requires portfolio_snapshots table with positions_json column
metadata:
  author: agentic-trader
  version: "1.0"
  category: portfolio-analysis
allowed-tools: bash
---

# swap-positions

Simulate "what if" position swaps at a historical snapshot date and calculate the resulting portfolio worth at a future date.

**Key concept**: Swaps are instantaneous replacements, NOT trades. No cash changes hands — 50 AAPL shares become 50 TSLA shares at snapshot_date prices.

## When to Use

✅ USE this skill when:
- "What if I had swapped 50 AAPL for TSLA on Jan 15?"
- "How would my portfolio look if I owned NVDA instead of MSFT?"
- "Compare original portfolio vs swapped version"
- "What if I replaced my tech holdings with energy stocks?"
- User wants alternate-universe/what-if position analysis

## When NOT to Use

❌ DO NOT use this skill when:
- User wants to simulate actual buy/sell trades → use `backtest-strategy`
- User wants plain buy-and-hold forward valuation (no swaps) → use `snapshot-worth`
- No portfolio snapshot exists for the date
- Swap quantity exceeds shares in the snapshot

## Quick Responses

| User says | Command |
|---|---|
| "Swap 50 AAPL for TSLA on Jan 15" | `python src/agentic/agents/backtester/skills/swap-positions/swap.py --snapshot_date 2024-01-15 --end_date 2024-02-15 --tickers '{"AAPL": {"swap_to": "TSLA", "quantity": 50}}'` |
| "Replace MSFT with GOOGL (100 shares)" | `python src/agentic/agents/backtester/skills/swap-positions/swap.py --snapshot_date 2024-01-15 --end_date 2024-02-15 --tickers '{"MSFT": {"swap_to": "GOOGL", "quantity": 100}}'` |
| "Swap AAPL→NVDA and MSFT→AMZN" | `python src/agentic/agents/backtester/skills/swap-positions/swap.py --snapshot_date 2024-01-15 --end_date 2024-02-15 --tickers '{"AAPL": {"swap_to": "NVDA", "quantity": 100}, "MSFT": {"swap_to": "AMZN", "quantity": 50}}'` |

## Execution

```bash
python src/agentic/agents/backtester/skills/swap-positions/swap.py \
  --snapshot_date 2024-01-15 \
  --end_date 2024-02-15 \
  --tickers '{"AAPL": {"swap_to": "TSLA", "quantity": 50}}'
```

## Output Format

Success:
```json
{
  "snapshot_date": "2024-01-15",
  "end_date": "2024-02-15",
  "swaps_applied": [{"from": "AAPL", "to": "TSLA", "quantity": 50, "price_at_swap": 245.50}],
  "initial_worth_before_swap": 105000.00,
  "initial_worth": 105000.00,
  "final_worth": 108500.00,
  "return_pct": 3.33
}
```

Error:
```json
{
  "error": "Cannot swap 100 shares of AAPL - only 75 available in snapshot"
}
```

## Requirements
- Portfolio snapshot must exist with positions_json
- Positions to swap must exist in the snapshot
- Swap quantity must not exceed available shares
- Historical data available for both old and new symbols
