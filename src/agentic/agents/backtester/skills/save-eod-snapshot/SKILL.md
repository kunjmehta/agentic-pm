---
name: save-eod-snapshot
description: "Save end-of-day portfolio state (equity, cash, positions) to database for later snapshot/swap analysis. USE WHEN: user wants to record portfolio state, or before running snapshot-worth or swap-positions. NOT FOR: fetching live portfolio (use get_portfolio_status tool) or running backtests."
license: MIT
compatibility: Requires portfolio_snapshots table with positions_json column
metadata:
  author: agentic-trader
  version: "1.0"
  category: data-management
allowed-tools: bash
---

# save-eod-snapshot

Save complete portfolio state (equity, cash, positions) to the database. Snapshots saved here can later be used by `snapshot-worth` and `swap-positions` skills.

## When to Use

✅ USE this skill when:
- "Save today's portfolio snapshot"
- "Record current portfolio state before rebalancing"
- User explicitly asks to save the portfolio
- At end of trading day to enable future forward-valuation queries
- Before running swap simulations (to have a snapshot to swap from)

## When NOT to Use

❌ DO NOT use this skill when:
- User wants live current portfolio data → use `get_portfolio_status` tool
- User wants to run a backtest → use `backtest-strategy` skill
- User wants to check what a past snapshot is worth → use `snapshot-worth` skill (read, not save)

## Quick Responses

| User says | Command |
|---|---|
| "Save today's portfolio snapshot" | `python src/agentic/agents/backtester/skills/save-eod-snapshot/snapshot.py --timestamp "2026-03-25 16:00:00" --equity 125000.0 --cash 50000.0 --buying_power 150000.0 --positions '[...]'` |
| "Record portfolio before rebalancing" | Same as above with current equity/cash/positions from `get_portfolio_status` |

## Execution

```bash
python src/agentic/agents/backtester/skills/save-eod-snapshot/snapshot.py \
  --timestamp "2024-01-15 16:00:00" \
  --equity 125000.0 \
  --cash 50000.0 \
  --buying_power 150000.0 \
  --positions '[{"symbol": "AAPL", "quantity": 200, "cost_basis": 150.0, "current_price": 165.0, "market_value": 33000.0, "side": "long"}]' \
  --daily_pnl 5000.0 \
  --snapshot_source manual
```

## Output Format

Success:
```json
{
  "status": "success",
  "snapshot_id": 42,
  "date": "2024-01-15",
  "positions_count": 3,
  "long_positions": 3,
  "short_positions": 0
}
```

## Requirements
- Valid ISO timestamp
- `positions` must be a JSON array of objects, each with `symbol` field
- Numeric values must be valid floats/ints

## Notes
- One snapshot per day (upsert by date) — calling twice the same day overwrites
- Source identifier (`manual`, `backtest`, `pre-rebalance`) helps track origin
