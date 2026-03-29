---
name: volume-indicators
description: "Calculate OBV and volume flow to assess buying/selling pressure and confirm trends. USE WHEN: user mentions OBV, volume flow, accumulation, distribution, volume trend, or volume confirmation. NOT FOR: price-based indicators (MACD/RSI/Bollinger) or candlestick patterns."
license: MIT
metadata:
  author: agentic-trader
  version: "1.0"
  indicators: ["OBV", "Volume Flow"]
allowed-tools: bash
---

# volume-indicators

## Overview
Calculates On-Balance Volume (OBV) and analyzes volume trends to assess accumulation/distribution patterns.

## When to Use

✅ USE this skill when:
- "What's the volume trend for AAPL?"
- "Is there volume confirmation for this breakout?"
- "Show OBV for TSLA"
- "Is NVDA being accumulated or distributed?"
- "Is volume above average on MSFT?"
- User needs volume divergence analysis

## When NOT to Use

❌ DO NOT use this skill when:
- Precomputed indicators are available → use `get_precomputed_indicators` first (already includes OBV)
- User asks about MACD/RSI → use `momentum-indicators`
- User asks about Bollinger Bands → use `volatility-indicators`
- User asks about candle shapes or patterns → use `candlestick-patterns`

## Quick Responses

| User says | Command |
|---|---|
| "Volume trend for AAPL" | `python src/agentic/agents/quant/skills/volume-indicators/volume.py --symbol AAPL --lookback 60` |
| "OBV on TSLA" | `python src/agentic/agents/quant/skills/volume-indicators/volume.py --symbol TSLA --lookback 60` |
| "Volume confirmation on MSFT breakout" | `python src/agentic/agents/quant/skills/volume-indicators/volume.py --symbol MSFT --lookback 30` |
| "Is NVDA being accumulated?" | `python src/agentic/agents/quant/skills/volume-indicators/volume.py --symbol NVDA --lookback 60` |

## Calculation

```bash
python src/agentic/agents/quant/skills/volume-indicators/volume.py --symbol AAPL --lookback 60
```

## Output Format

```json
{
  "obv": 12500000,
  "volume_trend": "increasing",
  "avg_volume_10d": 8500000,
  "current_vs_avg": 1.18
}
```

## Interpretation

### OBV (On-Balance Volume)
- **Rising OBV**: Accumulation, buying pressure confirms uptrend
- **Falling OBV**: Distribution, selling pressure confirms downtrend
- **OBV diverges from price**: Warning — price up + OBV down = weak uptrend

### Volume Trend
- **Increasing**: Growing interest, trend has conviction
- **Decreasing**: Waning interest, trend weakening

### Volume Confirmation
- **Breakout + high volume**: Legitimate breakout
- **Breakout + low volume**: False breakout risk

## Requirements
- Minimum 2 bars for OBV calculation
- Minimum 10 bars for trend analysis
- Returns None for insufficient data
