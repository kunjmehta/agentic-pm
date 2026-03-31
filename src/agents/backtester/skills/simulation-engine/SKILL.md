---
name: simulation-engine
description: Simulate trading days by replaying bars and executing strategy signals chronologically. Handles entry/exit logic, position tracking, P&L calculation.
license: MIT
metadata:
  author: agentic-trader
  version: "1.0"
  category: backtesting
allowed-tools: bash
---

# simulation-engine

## Overview

Core simulation logic that replays historical bars chronologically and executes trades based on strategy signals. This skill provides the computational engine for running "What If" scenarios on historical market data.

## When to Use

- Replay a single trading day with 1-minute bars
- Execute trades based on strategy signals (mean-reversion, momentum, etc.)
- Track positions, cash, and equity throughout the day
- Calculate P&L for each trade
- Generate end-of-day summary

## Workflow

### 1. Initialize Simulation State

```python
def initialize_simulation(initial_capital: float, symbol: str) -> dict:
    """Set up initial state for simulation.

    Returns:
        state = {
            "cash": initial_capital,
            "positions": {},  # {symbol: quantity}
            "equity": initial_capital,
            "trades": [],
            "current_bar": None
        }
    """
```

### 2. Replay Bars Chronologically

Iterate through 1-minute bars from 9:30 AM to 4:00 PM ET in order:

```python
for bar in bars:
    # Update current bar
    state["current_bar"] = bar

    # Check if strategy generates signal
    signal = check_strategy_signal(bar, state)

    if signal:
        # Execute trade
        execute_trade(signal, bar, state)

    # Update mark-to-market equity
    update_equity(bar, state)
```

### 3. Check Strategy Signals

At each bar, evaluate whether strategy conditions are met:

```python
def check_strategy_signal(bar, state, strategy_params) -> Optional[dict]:
    """Check if strategy generates entry/exit signal.

    Returns:
        signal = {
            "action": "buy" | "sell" | "hold",
            "quantity": int,
            "reason": str,
            "indicators": {...}  # Current indicator values
        }
    """
    # Example for mean-reversion:
    # - If z_score < -2.0: BUY signal
    # - If z_score > 2.0 or holding and reached take_profit: SELL signal
```

### 4. Execute Trades

Simulate trade execution with realistic assumptions:

```python
def execute_trade(signal, bar, state) -> dict:
    """Execute a simulated trade.

    Args:
        signal: Trade signal from strategy
        bar: Current market bar (OHLCV)
        state: Current simulation state

    Returns:
        trade = {
            "entry_time": bar.timestamp,
            "entry_price": execution_price,
            "quantity": signal.quantity,
            "side": "long" | "short",
            "entry_signal": signal.indicators
        }
    """
    # Execution logic:
    # - Entry: Use bar.close (or bar.close * 1.0005 for slippage)
    # - Exit: Use bar.close (or bar.close * 0.9995 for slippage)
    # - Update cash: cash -= (price * quantity)
    # - Update positions: positions[symbol] += quantity
    # - Record trade in state.trades
```

### 5. Update Portfolio State

After each bar, update mark-to-market values:

```python
def update_equity(bar, state):
    """Calculate current equity value.

    equity = cash + sum(position_value for each position)
    position_value = quantity * current_price
    """
    total_position_value = 0
    for symbol, quantity in state["positions"].items():
        total_position_value += quantity * bar.close

    state["equity"] = state["cash"] + total_position_value
```

### 6. Calculate End-of-Day Metrics

At market close (4:00 PM ET), summarize the day:

```python
def calculate_eod_summary(state, initial_capital) -> dict:
    """Generate end-of-day summary.

    Returns:
        summary = {
            "trades_executed": len(state.trades),
            "eod_equity": state.equity,
            "daily_pnl": state.equity - initial_capital,
            "daily_return_pct": ((state.equity - initial_capital) / initial_capital) * 100,
            "final_cash": state.cash,
            "open_positions": len(state.positions),
            "position_details": state.positions
        }
    """
```

## Simulation Parameters

### Execution Costs

- **Slippage**: 0.05% (5 basis points)
  - Buy: execution_price = bar.close * 1.0005
  - Sell: execution_price = bar.close * 0.9995
- **Commission**: $0 (Alpaca is commission-free)

### Position Sizing

Strategy parameters should define position size:
- Fixed quantity (e.g., 100 shares)
- Percentage of portfolio (e.g., 10% of equity)
- Kelly Criterion sizing

### Exit Logic

Trades can exit for multiple reasons:
- **Take Profit**: Price reaches target level
- **Stop Loss**: Price hits stop level
- **Signal Reversal**: Strategy generates opposite signal
- **End of Day (EOD)**: Close all positions at 4:00 PM ET

## Example: Single-Day Simulation

```python
# Input
symbol = "AAPL"
date = "2024-01-15"
initial_capital = 100000.0
strategy = "mean-reversion"
bars = fetch_historical_bars("AAPL", "2024-01-15", "2024-01-15", "1Min")

# Simulation
state = initialize_simulation(initial_capital, symbol)

for bar in bars:
    signal = check_strategy_signal(bar, state, strategy_params={"z_threshold": 2.0, "window": 20})

    if signal and signal.action == "buy":
        execute_trade(signal, bar, state)
    elif signal and signal.action == "sell":
        close_position(symbol, bar, state)

    update_equity(bar, state)

# Output
eod_summary = calculate_eod_summary(state, initial_capital)

# Result
{
    "trades_executed": 3,
    "eod_equity": 100250.00,
    "daily_pnl": 250.00,
    "daily_return_pct": 0.25,
    "final_cash": 85000.00,
    "open_positions": 1,
    "position_details": {"AAPL": 100}
}
```

## Integration with Tools

This skill uses the following tools:
- `fetch_historical_bars_for_backtest()` - Get 1-min bars for the day
- `save_backtest_run_to_db()` - Save simulation results

## Notes

- Simulations run in **historical order** - no lookahead bias
- All trades use **close prices** from bars (realistic execution)
- **Slippage** accounts for market impact
- **End-of-day positions** can be carried forward to next day (for multi-day backtests)
- Simulations are **deterministic** - same inputs always produce same outputs
