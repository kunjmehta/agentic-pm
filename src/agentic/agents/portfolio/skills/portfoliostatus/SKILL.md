---
name: portfoliostatus
description: "Fetch current portfolio status (equity, cash, buying power) and detailed positions (P&L per holding). USE WHEN: user asks about account value, cash, positions, or how their portfolio is doing. NOT FOR: risk/health validation (use health skill) or technical analysis (delegate to quant)."
license: MIT
compatibility: Requires Alpaca API credentials
metadata:
  author: agentic-trader
  version: "1.0"
allowed-tools: bash
---

# portfoliostatus

Retrieve current portfolio status from Alpaca API — account equity, cash, buying power, and position details with P&L. Results are cached 5 minutes for performance.

## When to Use

✅ USE this skill when:
- "What's my portfolio status?"
- "How much cash do I have?"
- "What's my buying power?"
- "What's my total equity?"
- "Show all open positions with P&L"
- "How many positions do I have?"

## When NOT to Use

❌ DO NOT use this skill when:
- User asks about risk, violations, or limits → use `health` skill
- User asks for technical indicators or buy/sell signals → delegate to Quant Analyst
- User asks to backtest a strategy → delegate to Backtester

## Quick Responses

| User says | Command |
|---|---|
| "Portfolio status" | `python src/agentic/agents/portfolio/skills/portfoliostatus/status.py --action status` |
| "Show all positions" | `python src/agentic/agents/portfolio/skills/portfoliostatus/status.py --action positions` |
| "Portfolio status as table" | `python src/agentic/agents/portfolio/skills/portfoliostatus/status.py --action status --format table` |

## Output Format

Account status:
```json
{
  "equity": 100000.0,
  "cash": 50000.0,
  "buying_power": 200000.0,
  "long_positions": 3,
  "short_positions": 0,
  "portfolio_value": 100000.0,
  "last_equity": 98500.0,
  "timestamp": "2026-03-25T10:30:00"
}
```

## Notes
- Cached 5 minutes; returns stale cache if API fails
- Auto-saves snapshots to database for historical tracking
