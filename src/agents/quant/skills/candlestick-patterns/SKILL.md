---
name: candlestick-patterns
description: Detect candlestick patterns (engulfing, doji, hammer) for reversal and continuation signals. Use when you need to identify potential turning points or trend confirmations.
license: MIT
metadata:
  author: agentic-trader
  version: "1.0"
  patterns: ["Bullish Engulfing", "Bearish Engulfing", "Doji", "Hammer", "Hanging Man"]
allowed-tools: bash
---

# candlestick-patterns

## Overview
Analyzes candlestick chart patterns to detect:
- Bullish/Bearish Engulfing patterns
- Doji (indecision)
- Hammer/Hanging Man (potential reversal)
- Body/shadow spread analysis

## When to Use
- Identify potential reversal points
- Detect indecision in the market (doji)
- Confirm trend strength with body size
- Find support/resistance tests (hammer patterns)
- Validate entries/exits with pattern confirmation

## Calculation

Run the pattern detection script:

```bash
python src/agents/quant/skills/candlestick-patterns/candles.py --symbol AAPL --lookback 10
```

## Output Format

Returns JSON with detected patterns and current candle type:

```json
{
  "patterns": ["bullish_engulfing", "hammer"],
  "last_candle_type": "bullish",
  "last_body_pct": 65.5,
  "pattern_count": 2
}
```

## Interpretation

### Bullish Engulfing
- Previous candle bearish, current bullish
- Current body completely engulfs previous body
- **Signal**: Potential bullish reversal
- **Strength**: Higher volume increases reliability

### Bearish Engulfing
- Previous candle bullish, current bearish
- Current body completely engulfs previous body
- **Signal**: Potential bearish reversal
- **Strength**: At resistance levels = stronger

### Doji
- Very small body (< 10% of total range)
- **Signal**: Indecision, potential reversal
- **Context matters**: Doji after uptrend = bearish, after downtrend = bullish

### Hammer
- Long lower shadow (>2x body size)
- Small upper shadow
- **Signal**: Bullish reversal after downtrend
- **Confirmation**: Next candle closes above hammer high

### Hanging Man
- Same shape as hammer but at top of uptrend
- **Signal**: Bearish reversal warning
- **Confirmation**: Next candle closes below low

### Body Percentage
- **> 70%**: Strong conviction in direction
- **30-70%**: Moderate conviction
- **< 30%**: Weak conviction, indecision

## Requirements
- Minimum 2 bars for pattern detection
- More bars = more patterns detected
- Patterns are detected in recent lookback window

## Example Usage

```python
result = bash("python .claude/skills/candlestick-patterns/candles.py --symbol AAPL --lookback 10")
patterns = json.loads(result)

if 'bullish_engulfing' in patterns['patterns']:
    print("Bullish engulfing detected - potential buy signal")

if patterns['last_candle_type'] == 'bullish' and patterns['last_body_pct'] > 70:
    print("Strong bullish candle with conviction")
```

## Important Notes
- Patterns should be confirmed with volume and other indicators
- Context matters: same pattern means different things in different trends
- Never trade on patterns alone - use as confluence with other signals
