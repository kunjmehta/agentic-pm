---
name: volatility-indicators
description: Calculate Bollinger Bands to assess price volatility and identify support/resistance levels. Use when you need to understand volatility, detect breakouts, or find overbought/oversold conditions.
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
- Measure price volatility and volatility changes
- Identify support (lower band) and resistance (upper band) levels
- Detect breakouts when price crosses bands
- Assess overbought/oversold via price position relative to bands
- Identify volatility contractions (squeeze) before major moves

## Calculation

Run the calculation script:

```bash
python src/agents/quant/skills/volatility-indicators/volatility.py --symbol AAPL --lookback 60
```

## Output Format

Returns JSON with upper, middle, lower bands and bandwidth:

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
- **Price at middle band**: Neutral, trend strength unclear

### Bandwidth Analysis
- **Narrow bandwidth (< 2%)**: Low volatility, consolidation phase, breakout pending
- **Wide bandwidth (> 4%)**: High volatility, trending strongly
- **Expanding bands**: Increasing volatility
- **Contracting bands**: Decreasing volatility (squeeze)

### Trading Signals
- **Bounce off lower band**: Potential buy signal
- **Bounce off upper band**: Potential sell signal
- **Break above upper band**: Strong bullish breakout
- **Break below lower band**: Strong bearish breakdown

## Requirements
- Minimum 20 bars for calculation
- Returns None if insufficient data

## Example Usage

```python
result = bash("python .claude/skills/volatility-indicators/volatility.py --symbol AAPL --lookback 60")
bands = json.loads(result)

if bands['bandwidth'] < 2.0:
    print("Low volatility - potential breakout coming")
```
