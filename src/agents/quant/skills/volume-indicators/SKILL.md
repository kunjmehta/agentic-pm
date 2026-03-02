---
name: volume-indicators
description: Calculate On-Balance Volume (OBV) and volume flow analysis. Use when you need to assess buying/selling pressure, confirm trends, or detect divergences.
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
- Assess buying vs selling pressure
- Confirm price trends with volume
- Detect divergences (price up, volume down = weak trend)
- Identify accumulation (OBV rising) or distribution (OBV falling) phases
- Validate breakouts with volume confirmation

## Calculation

Run the calculation script:

```bash
python src/agents/quant/skills/volume-indicators/volume.py --symbol AAPL --lookback 60
```

## Output Format

Returns JSON with OBV value, trend, and average volume:

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
- **Rising OBV**: Accumulation, buying pressure
- **Falling OBV**: Distribution, selling pressure
- **OBV confirms price**: Healthy trend
- **OBV diverges from price**: Warning sign
  - Price up, OBV down: Weak uptrend, potential reversal
  - Price down, OBV up: Weak downtrend, potential bounce

### Volume Trend
- **Increasing**: Growing interest, trend strength
- **Decreasing**: Waning interest, trend weakening
- **Higher than average**: Conviction in current move
- **Lower than average**: Lack of conviction

### Volume Confirmation
- **Breakout + high volume**: Legitimate breakout
- **Breakout + low volume**: False breakout risk

## Requirements
- Minimum 2 bars for OBV calculation
- Minimum 10 bars for trend analysis
- Returns None for insufficient data

## Example Usage

```python
result = bash("python .claude/skills/volume-indicators/volume.py --symbol AAPL --lookback 60")
volume_data = json.loads(result)

if volume_data['volume_trend'] == 'increasing' and volume_data['current_vs_avg'] > 1.5:
    print("Strong volume confirmation - significant interest")
```
