---
name: volatility-indicators
description: "Calculate Bollinger Bands to assess volatility, breakouts, and support/resistance. USE WHEN: user mentions Bollinger Bands, ATR, volatility, bandwidth, squeeze, breakout bands. NOT FOR: momentum (MACD/RSI), volume analysis, or candlestick patterns."
license: MIT
metadata:
  author: agentic-trader
  version: "1.0"
  indicators: ["Bollinger Bands"]
allowed-tools: bash
---

# volatility-indicators

## Overview
Calculates Bollinger Bands: 20-period Simple Moving Average (SMA) with ±2 standard deviation bands.

## When to Use

✅ USE this skill when:
- "Show me Bollinger Bands for AAPL"
- "Is TSLA near the upper/lower band?"
- "Is there a volatility squeeze on MSFT?"
- "Detect breakout conditions for NVDA"
- "Assess price volatility"
- User needs custom band width or period

## When NOT to Use

❌ DO NOT use this skill when:
- Precomputed indicators are available → use `get_precomputed_indicators` first (already includes Bollinger Bands)
- User asks about MACD or RSI → use `momentum-indicators`
- User asks about OBV or volume → use `volume-indicators`
- User asks about candle patterns → use `candlestick-patterns`

## Quick Responses

| User says | Command |
|---|---|
| "Bollinger Bands for AAPL" | `python src/agentic/agents/quant/skills/volatility-indicators/volatility.py --symbol AAPL --lookback 60` |
| "Is TSLA near the upper band?" | `python src/agentic/agents/quant/skills/volatility-indicators/volatility.py --symbol TSLA --lookback 60` |
| "Volatility squeeze on MSFT" | `python src/agentic/agents/quant/skills/volatility-indicators/volatility.py --symbol MSFT --lookback 30` |
| "NVDA breakout potential" | `python src/agentic/agents/quant/skills/volatility-indicators/volatility.py --symbol NVDA --lookback 60` |

## Calculation

```bash
python src/agentic/agents/quant/skills/volatility-indicators/volatility.py --symbol AAPL --lookback 60
```

## Output Format

```json
{
  "upper": 151.2,
  "middle": 150.0,
  "lower": 148.8,
  "bandwidth": 1.6
}
```

## Interpretation

### Band Position
- **Price near upper band**: Overbought, potential resistance
- **Price near lower band**: Oversold, potential support

### Bandwidth Analysis
- **Narrow bandwidth (< 2%)**: Low volatility, squeeze — breakout pending
- **Wide bandwidth (> 4%)**: High volatility, trending strongly

### Trading Signals
- **Bounce off lower band**: Potential buy signal
- **Break above upper band**: Strong bullish breakout
- **Break below lower band**: Strong bearish breakdown

## Requirements
- Minimum 20 bars for calculation
- Returns None if insufficient data
