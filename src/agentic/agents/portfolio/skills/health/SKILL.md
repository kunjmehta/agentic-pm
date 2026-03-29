---
name: health
description: "Validate portfolio against risk limits (concentration, position size, cash reserve). USE WHEN: user asks about risk, health, violations, or before making trade recommendations. NOT FOR: just viewing portfolio data (use portfoliostatus) or technical analysis."
license: MIT
metadata:
  author: agentic-trader
  version: "1.0"
allowed-tools: bash
---

# portfolio-health

Validate current portfolio state against configured risk limits. Returns health status (`healthy` / `warning` / `unhealthy`) with specific violations and warnings.

## When to Use

✅ USE this skill when:
- "Is my portfolio healthy?"
- "Are there any risk violations?"
- "Is it safe to trade?"
- "Check my risk limits"
- Before making any trade recommendation (always run health check first)
- After significant market moves

## When NOT to Use

❌ DO NOT use this skill when:
- User just wants portfolio values or position details → use `portfoliostatus` skill
- User asks for technical analysis → delegate to Quant Analyst
- User asks to backtest → delegate to Backtester

## Quick Responses

| User says | Command |
|---|---|
| "Is my portfolio healthy?" | `python src/agentic/agents/portfolio/skills/health/health.py` |
| "Any risk violations?" | `python src/agentic/agents/portfolio/skills/health/health.py` |
| "Safe to trade?" | `python src/agentic/agents/portfolio/skills/health/health.py` |

## Output Format

```json
{
  "health_status": "warning",
  "violations": [],
  "warnings": [
    {"check": "position_concentration", "symbol": "AAPL", "value": 0.12, "limit": 0.10, "message": "AAPL at 12% exceeds 10% limit"}
  ],
  "checks_performed": ["position_concentration", "position_size_limits", "cash_reserves"],
  "risk_parameters_used": {"position_limit_percent": 0.1, "max_position_size": 1500}
}
```

## Risk Limits (Defaults)

| Check | Default Limit |
|---|---|
| Position concentration | 10% max per position |
| Position size | 1,500 shares max |
| Cash reserve | 5% minimum |
| Daily loss limit | 5% (enforced by middleware) |
