---
name: backtest-strategy
description: "Execute a single trading strategy backtest with bar-by-bar simulation and performance metrics. USE WHEN: user wants to backtest one specific strategy (mean-reversion, momentum, buy-and-hold) on a ticker. NOT FOR: comparing multiple strategies at once (use run_strategy_comparison tool) or portfolio snapshot/swap analysis."
license: MIT
compatibility: Requires historical market data and backtest database schema
metadata:
  author: agentic-trader
  version: "2.0"
  category: strategy-testing
allowed-tools: bash
---

# backtest-strategy

Execute a complete trading strategy backtest with bar-by-bar simulation, performance metrics, and optional database persistence.

## When to Use

✅ USE this skill when:
- "Backtest mean-reversion on AAPL from Jan to Feb 2024"
- "How would buy-and-hold perform on TSLA last month?"
- "Test momentum strategy on MSFT from 2024-01-01 to 2024-02-01"
- User specifies exactly ONE strategy for ONE ticker
- Evaluating a strategy before live deployment

## When NOT to Use

❌ DO NOT use this skill when:
- User wants to compare multiple strategies → call `run_strategy_comparison` tool instead (runs in parallel)
- User wants "what would portfolio X be worth?" → use `snapshot-worth` skill
- User wants "what if I swapped X for Y?" → use `swap-positions` skill

**Call this skill directly** — it fetches its own historical data internally from the database.

## Quick Responses

| User says | Command |
|---|---|
| "Backtest mean-reversion on AAPL Jan 2024" | `python src/agentic/agents/backtester/skills/backtest-strategy/strategy.py --ticker AAPL --start_date 2024-01-01 --end_date 2024-01-31 --strategy mean-reversion` |
| "Buy-and-hold TSLA last month" | `python src/agentic/agents/backtester/skills/backtest-strategy/strategy.py --ticker TSLA --start_date 2024-02-01 --end_date 2024-02-29 --strategy buy-and-hold` |
| "Momentum strategy MSFT, save results" | `python src/agentic/agents/backtester/skills/backtest-strategy/strategy.py --ticker MSFT --start_date 2024-01-01 --end_date 2024-02-01 --strategy momentum --save_to_db` |

## Execution

```bash
python src/agentic/agents/backtester/skills/backtest-strategy/strategy.py \
  --ticker AAPL \
  --start_date 2024-01-01 \
  --end_date 2024-01-31 \
  --strategy mean-reversion \
  --initial_capital 100000
```

Add `--save_to_db` to persist results. Capture stdout as JSON.

## Parameters

| Parameter | Default | Options |
|---|---|---|
| `--ticker` | required | Any ticker symbol |
| `--start_date` | required | YYYY-MM-DD |
| `--end_date` | required | YYYY-MM-DD |
| `--strategy` | `buy-and-hold` | `buy-and-hold`, `mean-reversion`, `momentum` |
| `--initial_capital` | 100000 | Any float |
| `--save_to_db` | false | flag |

## Output Format

Success:
```json
{
  "run_id": "abc-123",
  "status": "completed",
  "strategy": "mean-reversion",
  "symbol": "AAPL",
  "metrics": {
    "total_return_pct": 8.5,
    "sharpe_ratio": 1.42,
    "max_drawdown_pct": -3.2,
    "win_rate": 0.65,
    "profit_factor": 1.8,
    "total_trades": 23
  },
  "summary": "...",
  "recommendation": "CONSIDER for live trading with careful position sizing"
}
```

Error:
```json
{
  "status": "failed",
  "error": "No historical data available for AAPL",
  "suggestion": "Ingest market data for this symbol first"
}
```

## Performance Metric Thresholds

| Metric | Poor | Good | Excellent |
|---|---|---|---|
| Sharpe Ratio | < 1.0 | 1.0–2.0 | > 2.0 |
| Max Drawdown | > -20% | -5% to -10% | 0 to -5% |
| Win Rate | < 50% | 50–60% | > 60% |
| Profit Factor | < 1.0 | 1.5–2.0 | > 2.0 |

## Requirements
- Historical market data for ticker in date range
- At least 390 bars (1 full trading day at 1-minute resolution)
- Valid date range (end_date > start_date)
