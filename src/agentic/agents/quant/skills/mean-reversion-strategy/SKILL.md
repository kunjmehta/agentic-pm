---
name: mean-reversion-strategy
description: "Run mean reversion strategy: z-score deviation, Bollinger Bands, moving averages, entry/exit signals. USE WHEN: user mentions mean reversion, z-score, oversold reversion, overbought reversion, or wants a BUY/SELL signal based on statistical deviation. NOT FOR: raw indicator values only (use individual indicator skills) or trending/momentum strategies."
license: MIT
compatibility: Requires market data access and pandas/numpy
metadata:
  author: agentic-trader
  version: "1.0"
  strategy_type: mean_reversion
allowed-tools: bash
---

# mean-reversion-strategy

## Overview
Implements a mean reversion trading strategy: identifies when a stock price has deviated significantly from its historical mean (z-score) and generates entry/exit signals. Combines z-score, Bollinger Bands, SMA/EMA, and support/resistance levels.

Works best in **sideways/range-bound markets**. Less effective in strong trending conditions.

## When to Use

✅ USE this skill when:
- "Run mean reversion strategy on AAPL"
- "Is TSLA oversold enough to buy?"
- "Give me a z-score buy/sell signal for NVDA"
- "What's the reversion signal on MSFT?"
- "Is AAPL more than 2 standard deviations below its mean?"
- User wants a composite BUY/SELL/HOLD recommendation

## When NOT to Use

❌ DO NOT use this skill when:
- User only wants raw RSI or MACD values → use `momentum-indicators`
- User only wants Bollinger Band levels → use `volatility-indicators`
- User wants volume analysis → use `volume-indicators`
- User is asking about a trending/momentum strategy → mean reversion underperforms in strong trends
- Precomputed indicators available and user wants a quick read → use `get_precomputed_indicators` first

## Quick Responses

| User says | Command |
|---|---|
| "Mean reversion on AAPL" | `python src/agentic/agents/quant/skills/mean-reversion-strategy/mean_reversion.py --symbol AAPL --lookback 60` |
| "Z-score buy signal on TSLA" | `python src/agentic/agents/quant/skills/mean-reversion-strategy/mean_reversion.py --symbol TSLA --lookback 60` |
| "NVDA oversold? reversion threshold 1.5" | `python src/agentic/agents/quant/skills/mean-reversion-strategy/mean_reversion.py --symbol NVDA --lookback 60 --threshold 1.5` |
| "Mean reversion MSFT, last 30 bars" | `python src/agentic/agents/quant/skills/mean-reversion-strategy/mean_reversion.py --symbol MSFT --lookback 30` |

## Parameters

- `--symbol`: Stock ticker (required)
- `--lookback`: Bars of history (default: 60)
- `--threshold`: Z-score signal threshold (default: 2.0)
  - Z > threshold → overbought (sell signal)
  - Z < -threshold → oversold (buy signal)
- `--ma-period`: Moving average period (default: 20)

## Output Format

```json
{
  "symbol": "AAPL",
  "current_price": 150.25,
  "statistics": {
    "mean": 148.50,
    "std_dev": 2.35,
    "z_score": 0.74,
    "percentile": 65.2
  },
  "signals": {
    "current_state": "neutral",
    "z_score_signal": "neutral",
    "ma_cross_signal": "bullish",
    "overall_signal": "hold"
  },
  "trade_recommendation": {
    "action": "hold",
    "confidence": 0.65,
    "reason": "Price within normal range, no extreme deviation detected"
  }
}
```

## Signal Interpretation

| Overall Signal | Condition |
|---|---|
| `strong_buy` | Z-score < -2.0 AND price near lower Bollinger Band |
| `buy` | Z-score < -1.5 OR price below SMA and oversold |
| `hold` | Z-score between -1.5 and 1.5 |
| `sell` | Z-score > 1.5 OR price above SMA and overbought |
| `strong_sell` | Z-score > 2.0 AND price near upper Bollinger Band |

## Requirements
- Minimum 60 bars recommended for reliable z-score
- Default threshold of 2.0 is conservative — adjust for higher volatility stocks
