---
name: momentum-indicators
description: "Calculate MACD and RSI for momentum/trend analysis. USE WHEN: user mentions momentum, MACD, RSI, trend strength, overbought, oversold, bullish crossover. NOT FOR: volatility bands, volume flow, or candlestick patterns (use those skills instead)."
license: MIT
compatibility: Requires pandas and numpy
metadata:
  author: agentic-trader
  version: "1.0"
  indicators: ["MACD", "RSI"]
allowed-tools: bash
---

# momentum-indicators

## Overview
Calculates momentum indicators for technical analysis: MACD (Moving Average Convergence Divergence) and RSI (Relative Strength Index).

## When to Use

✅ USE this skill when:
- "Analyze AAPL momentum"
- "What's the RSI on TSLA?"
- "Is NVDA overbought or oversold?"
- "Show MACD for MSFT"
- "Is there a bullish/bearish crossover?"
- "Check trend strength"
- User needs custom RSI period (e.g., `--rsi_period 10`)

## When NOT to Use

❌ DO NOT use this skill when:
- Precomputed indicators are available → use `get_precomputed_indicators` first (it already includes MACD/RSI)
- User asks about Bollinger Bands or ATR → use `volatility-indicators`
- User asks about OBV or volume flow → use `volume-indicators`
- User asks about candlestick patterns → use `candlestick-patterns`

## Quick Responses

| User says | Command |
|---|---|
| "Analyze AAPL momentum" | `python src/agentic/agents/quant/skills/momentum-indicators/momentum.py --symbol AAPL --lookback 30` |
| "RSI on TSLA with period 10" | `python src/agentic/agents/quant/skills/momentum-indicators/momentum.py --symbol TSLA --lookback 30 --rsi_period 10` |
| "MACD for MSFT last hour" | `python src/agentic/agents/quant/skills/momentum-indicators/momentum.py --symbol MSFT --lookback 60` |
| "Is NVDA overbought?" | `python src/agentic/agents/quant/skills/momentum-indicators/momentum.py --symbol NVDA --lookback 30` |

## Calculation

```bash
python src/agentic/agents/quant/skills/momentum-indicators/momentum.py --symbol AAPL --lookback 60
```

## Output Format

```json
{
  "macd": {
    "value": 0.52,
    "signal": 0.48,
    "histogram": 0.04
  },
  "rsi": 65.3
}
```

## Interpretation

### MACD (Moving Average Convergence Divergence)
- **Histogram > 0**: Bullish momentum (MACD above signal line)
- **Histogram < 0**: Bearish momentum (MACD below signal line)
- **Signal line crossover**: Trend change signal
  - MACD crosses above signal: Bullish signal
  - MACD crosses below signal: Bearish signal

### RSI (Relative Strength Index)
- **> 70**: Overbought territory (potential sell signal)
- **< 30**: Oversold territory (potential buy signal)
- **40-60**: Neutral range

## Requirements
- Minimum 26 bars for MACD calculation (EMA 12/26, Signal 9)
- Minimum 14 bars for RSI calculation
- Returns None if insufficient data available
