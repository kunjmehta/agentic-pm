---
name: momentum-indicators
description: Calculate momentum indicators (MACD and RSI) for stock analysis. Use when you need to assess price momentum, trend strength, or identify overbought/oversold conditions.
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
- Assess price momentum direction and strength
- Identify trend strength and potential reversals
- Detect overbought (RSI > 70) or oversold (RSI < 30) conditions
- Find bullish/bearish crossovers (MACD signal line)
- Confirm trend direction with histogram analysis

## Calculation

Run the calculation script with symbol and lookback period:

```bash
python src/agents/quant/skills/momentum-indicators/momentum.py --symbol AAPL --lookback 60
```

## Output Format

Returns JSON with MACD and RSI values:

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
- **Divergence**: Price vs MACD disagreement indicates potential reversal

### RSI (Relative Strength Index)
- **> 70**: Overbought territory (potential sell signal)
- **< 30**: Oversold territory (potential buy signal)
- **40-60**: Neutral range
- **50**: Midpoint - above suggests bullish, below suggests bearish

## Requirements
- Minimum 26 bars for MACD calculation (EMA 12/26, Signal 9)
- Minimum 14 bars for RSI calculation
- Returns None if insufficient data available

## Example Usage

```python
# For 30-minute analysis
result = bash("python .claude/skills/momentum-indicators/momentum.py --symbol AAPL --lookback 30")
indicators = json.loads(result)

if indicators['rsi'] and indicators['rsi'] > 70:
    print("AAPL is overbought")
elif indicators['macd']['histogram'] > 0:
    print("AAPL showing bullish momentum")
```
