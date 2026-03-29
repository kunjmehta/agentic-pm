---
name: candlestick-patterns
description: "Detect candlestick patterns (engulfing, doji, hammer) for reversal and continuation signals. USE WHEN: user mentions candle, doji, hammer, engulfing, hanging man, reversal pattern, or candlestick. NOT FOR: computing MACD/RSI, Bollinger Bands, or volume analysis."
license: MIT
metadata:
  author: agentic-trader
  version: "1.0"
  patterns: ["Bullish Engulfing", "Bearish Engulfing", "Doji", "Hammer", "Hanging Man"]
allowed-tools: bash
---

# candlestick-patterns

## Overview
Analyzes recent candlestick bars to detect reversal and continuation patterns including engulfing, doji, hammer, and hanging man.

## When to Use

✅ USE this skill when:
- "Are there any candlestick patterns on AAPL?"
- "Is there a doji or hammer forming?"
- "Show me engulfing patterns on TSLA"
- "Detect reversal signals via candles for NVDA"
- "Check last candle for MSFT — is it bullish?"
- User wants entry/exit confirmation via candle shape

## When NOT to Use

❌ DO NOT use this skill when:
- User asks about MACD, RSI, or momentum → use `momentum-indicators`
- User asks about Bollinger Bands or volatility → use `volatility-indicators`
- User asks about OBV or volume flow → use `volume-indicators`
- User wants a full strategy signal → combine with other indicators after running this

## Quick Responses

| User says | Command |
|---|---|
| "Candlestick patterns on AAPL" | `python src/agentic/agents/quant/skills/candlestick-patterns/candles.py --symbol AAPL --lookback 10` |
| "Any doji or hammer on TSLA?" | `python src/agentic/agents/quant/skills/candlestick-patterns/candles.py --symbol TSLA --lookback 10` |
| "Engulfing pattern on NVDA" | `python src/agentic/agents/quant/skills/candlestick-patterns/candles.py --symbol NVDA --lookback 10` |
| "Last candle type for MSFT" | `python src/agentic/agents/quant/skills/candlestick-patterns/candles.py --symbol MSFT --lookback 5` |

## Calculation

```bash
python src/agentic/agents/quant/skills/candlestick-patterns/candles.py --symbol AAPL --lookback 10
```

## Output Format

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
- Current candle fully engulfs previous bearish candle
- **Signal**: Potential bullish reversal — stronger with high volume

### Bearish Engulfing
- Current bearish candle fully engulfs previous bullish candle
- **Signal**: Potential bearish reversal — stronger at resistance levels

### Doji
- Very small body (< 10% of total range)
- **Signal**: Indecision — doji after uptrend = bearish, after downtrend = bullish

### Hammer
- Long lower shadow (> 2x body), small upper shadow
- **Signal**: Bullish reversal after downtrend

### Body Percentage
- **> 70%**: Strong conviction in direction
- **< 30%**: Weak conviction, possible indecision

## Requirements
- Minimum 2 bars for pattern detection
- Patterns should be confirmed with volume and other indicators
