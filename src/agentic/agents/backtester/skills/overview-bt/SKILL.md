---
name: overview-bt
description: "Edge-case fallback reference for backtester workflows. USE WHEN: the query does not match any row in the INSTANT WORKFLOW SELECTION table in AGENTS.MD. NOT FOR: standard backtest/snapshot/swap/compare requests — route those directly using the table."
license: MIT
compatibility: Required for all backtester operations
metadata:
  author: agentic-trader
  version: "1.1"
  category: decision-guide
  priority: fallback
allowed-tools: none
---

# overview-bt

Reference guide for backtester workflows. Consult this only when the user's request does not match Workflow A, B, C, or D in AGENTS.MD.

## When to Use

✅ USE this skill when:
- The request is unusual or ambiguous and does not fit the standard table in AGENTS.MD
- You need to verify available tools and their exact capabilities
- Edge case: user combines multiple workflows in one request

## When NOT to Use

❌ DO NOT read this skill before every request.
- "Backtest X on Y" → Workflow A — start immediately with `backtest-strategy` skill
- "What would portfolio be worth?" → Workflow B — start with `snapshot-worth` skill
- "Swap X for Y" → Workflow C — start with `swap-positions` skill
- "Compare strategies" → Workflow D — call `run_strategy_comparison` tool

## Quick Decision Tree

| Request matches | Go to |
|---|---|
| "Backtest", "simulate", "test strategy" | **Workflow A** — `backtest-strategy` skill |
| "Worth", "historical value", "hold until" | **Workflow B** — `snapshot-worth` skill |
| "Swap", "what if I had", "replace X with Y" | **Workflow C** — `swap-positions` skill |
| "Compare strategies", "which is better", "all strategies" | **Workflow D** — `run_strategy_comparison` tool |
| None of the above | Read this skill for guidance |

## Available Tools

| Tool | Purpose |
|---|---|
| `run_strategy_comparison` | Parallel multi-strategy comparison (Workflow D) |
| `fetch_historical_bars_for_backtest` | Check if market data exists |
| `save_backtest_run_to_db` | Persist backtest result |
| `fetch_backtest_run` | Retrieve saved backtest |
| `fetch_backtest_trades` | Trade-level drill-down |
| `fetch_backtest_performance_history` | Equity curve / daily snapshots |

## Available Skills

| Skill | Workflow | Script |
|---|---|---|
| `backtest-strategy` | A | `backtest-strategy/strategy.py` |
| `snapshot-worth` | B | `snapshot-worth/worth.py` |
| `swap-positions` | C | `swap-positions/swap.py` |
| `save-eod-snapshot` | Manual save | `save-eod-snapshot/snapshot.py` |

## Common Mistakes

| Mistake | Correct Action |
|---|---|
| Reading this skill before every request | Use AGENTS.MD selection table first |
| Calling `fetch_historical_bars_for_backtest` before Workflow A | Skip it — `backtest-strategy` fetches data internally |
| Calling same tool twice | Each tool called once; use the result |
| Continuing after workflow result | STOP immediately after presenting results |

## Defaults
- Strategy: `mean-reversion` if not specified
- Capital: `$100,000` if not specified
- Date range: last 30 days if not specified
