---
name: mean-reversion-strategy
description: Use this skill to analyze stocks using trend mean reversion strategy. Identifies overbought/oversold conditions and generates entry/exit signals based on statistical deviation from the mean.
license: MIT
compatibility: Requires market data access and pandas/numpy for calculations
metadata:
  author: agentic-trader
  version: "1.0"
  strategy_type: mean_reversion
allowed-tools: bash
---

# mean-reversion-strategy

## Overview

This skill implements a comprehensive mean reversion trading strategy that identifies when a stock price has deviated significantly from its historical mean and is likely to revert. It combines multiple technical indicators to generate high-confidence trading signals.

**Hierarchical Dependencies:**
This strategy is a Level 2 skill that builds upon Level 1 base indicators:
- Uses **momentum-indicators** for moving averages (SMA, EMA)
- Uses **volatility-indicators** concepts for Bollinger Bands calculation
- Uses **volume-indicators** for volume trend confirmation
- Can combine with **candlestick-patterns** for entry/exit confirmation

## Strategy Concept

Mean reversion assumes that prices tend to return to their average over time. When a stock price moves too far from its mean (either above or below), it becomes a candidate for mean reversion:
- **Oversold** (price below mean by >2 std dev): Potential buy signal
- **Overbought** (price above mean by >2 std dev): Potential sell signal

The strategy combines:
1. **Statistical Analysis**: Z-score, standard deviation, percentile ranking
2. **Moving Averages**: SMA-20, SMA-50, EMA-20 from momentum indicators
3. **Bollinger Bands**: 20-period SMA ± 2 standard deviations
4. **Support/Resistance**: Recent high/low price levels

## Instructions

### 1. Run the Mean Reversion Analysis

Use the bash tool to execute the mean reversion script:

```bash
python src/agents/quant/skills/mean-reversion-strategy/mean_reversion.py --symbol AAPL --lookback 60 --threshold 2.0
```

**Parameters:**
- `--symbol`: Stock ticker symbol (required)
- `--lookback`: Number of bars to use for calculation (default: 60)
- `--threshold`: Z-score threshold for signals (default: 2.0)
  - Values > threshold = overbought (sell signal)
  - Values < -threshold = oversold (buy signal)
- `--ma-period`: Moving average period (default: 20)
- `--format`: Output format: 'json' or 'text' (default: 'json')

### 2. Interpret the Output

The script returns a JSON object with:

```json
{
  "symbol": "AAPL",
  "timestamp": "2026-02-22T17:00:00",
  "current_price": 150.25,
  "statistics": {
    "mean": 148.50,
    "std_dev": 2.35,
    "z_score": 0.74,
    "percentile": 65.2
  },
  "moving_averages": {
    "sma_20": 148.75,
    "sma_50": 147.80,
    "ema_20": 149.10
  },
  "signals": {
    "current_state": "neutral",
    "z_score_signal": "neutral",
    "ma_cross_signal": "bullish",
    "bollinger_signal": "neutral",
    "overall_signal": "hold"
  },
  "levels": {
    "upper_band": 153.20,
    "lower_band": 143.80,
    "resistance": 152.50,
    "support": 145.20
  },
  "trade_recommendation": {
    "action": "hold",
    "confidence": 0.65,
    "reason": "Price within normal range, no extreme deviation detected",
    "entry_price": null,
    "stop_loss": null,
    "take_profit": null
  }
}
```

### 3. Key Metrics Explained

**Z-Score:**
- Measures how many standard deviations the current price is from the mean
- Z > 2.0: Significantly overbought (strong sell signal)
- -2.0 < Z < 2.0: Normal range (neutral)
- Z < -2.0: Significantly oversold (strong buy signal)

**Moving Average Signals:**
- Price > SMA: Uptrend (bullish)
- Price < SMA: Downtrend (bearish)
- SMA_20 crosses SMA_50: Trend change

**Bollinger Bands:**
- Price near upper band: Overbought
- Price near lower band: Oversold
- Bands contracting: Low volatility (potential breakout)
- Bands expanding: High volatility

### 4. Signal Interpretation

**Overall Signals:**
- `strong_buy`: Z-score < -2.0 AND price near lower Bollinger Band
- `buy`: Z-score < -1.5 OR price below SMA and oversold
- `hold`: Z-score between -1.5 and 1.5
- `sell`: Z-score > 1.5 OR price above SMA and overbought
- `strong_sell`: Z-score > 2.0 AND price near upper Bollinger Band

### 5. Example Usage

**Query:** "Run mean reversion strategy on AAPL"

**Agent Response:**
1. Execute: `python src/agents/quant/skills/mean-reversion-strategy/mean_reversion.py --symbol AAPL --lookback 60`
2. Parse the JSON output
3. Provide interpretation: "AAPL is currently trading at $150.25, which is 0.74 standard deviations above the 60-day mean of $148.50. The Z-score indicates neutral conditions with no extreme deviation. Overall signal: HOLD."

## Notes

- Works best in sideways/range-bound markets
- Less effective in strong trending markets
- Should be combined with other indicators for confirmation
- Default threshold of 2.0 is conservative; adjust based on market volatility
- Requires sufficient historical data (minimum lookback period)
