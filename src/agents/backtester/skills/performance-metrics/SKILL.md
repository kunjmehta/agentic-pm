---
name: performance-metrics
description: Calculate comprehensive performance metrics from backtest results. Includes Sharpe ratio, maximum drawdown, win rate, profit factor, and other risk-adjusted returns.
license: MIT
metadata:
  author: agentic-trader
  version: "1.0"
  category: analytics
allowed-tools: bash
---

# performance-metrics

## Overview

Pure mathematical functions to calculate performance metrics from trade and equity data. These metrics provide quantitative assessment of strategy performance and risk characteristics.

## When to Use

- After completing a backtest run with multiple trades
- To compare different strategies objectively
- To assess risk-adjusted returns
- To identify strategy weaknesses (drawdowns, losing streaks)
- Before deploying a strategy to live trading

## Metrics Calculated

### 1. Sharpe Ratio

**Definition**: Risk-adjusted return measuring excess return per unit of volatility.

**Formula**:
```
Sharpe Ratio = (Annualized Return - Risk-Free Rate) / Annualized Volatility

Where:
- Annualized Return = mean(daily_returns) * 252
- Annualized Volatility = std(daily_returns) * sqrt(252)
- Risk-Free Rate = 0.045 (4.5% annual, typical for US Treasuries)
```

**Implementation**:
```python
import pandas as pd

def calculate_sharpe_ratio(daily_returns: pd.Series, risk_free_rate: float = 0.045) -> float:
    """Calculate annualized Sharpe ratio.

    Args:
        daily_returns: Series of daily returns as decimals (e.g., 0.01 = 1%)
        risk_free_rate: Annual risk-free rate as decimal (default: 4.5%)

    Returns:
        Sharpe ratio (>1.0 = good, >2.0 = excellent, >3.0 = exceptional)
    """
    if len(daily_returns) < 2:
        return 0.0

    mean_daily_return = daily_returns.mean()
    std_daily_return = daily_returns.std()

    if std_daily_return == 0:
        return 0.0  # Avoid division by zero

    # Annualize (252 trading days per year)
    annualized_return = mean_daily_return * 252
    annualized_std = std_daily_return * (252 ** 0.5)

    sharpe = (annualized_return - risk_free_rate) / annualized_std
    return sharpe
```

**Interpretation**:
- **< 0**: Strategy loses money or underperforms risk-free rate
- **0 - 1**: Poor risk-adjusted returns
- **1 - 2**: Good risk-adjusted returns
- **> 2**: Excellent risk-adjusted returns
- **> 3**: Exceptional (rare in practice)

---

### 2. Maximum Drawdown

**Definition**: Largest peak-to-trough decline in equity.

**Formula**:
```
Max Drawdown = min((Equity - Peak Equity) / Peak Equity)
```

**Implementation**:
```python
def calculate_max_drawdown(equity_curve: pd.Series) -> float:
    """Calculate maximum peak-to-trough decline.

    Args:
        equity_curve: Series of equity values over time

    Returns:
        Maximum drawdown as negative decimal (e.g., -0.15 = -15% drawdown)
    """
    if len(equity_curve) < 2:
        return 0.0

    # Calculate running maximum (peak)
    cummax = equity_curve.cummax()

    # Calculate drawdown at each point
    drawdown = (equity_curve - cummax) / cummax

    # Return worst drawdown (most negative)
    return drawdown.min()
```

**Interpretation**:
- **0 to -5%**: Low risk
- **-5% to -10%**: Moderate risk
- **-10% to -20%**: High risk
- **> -20%**: Very high risk (significant capital loss potential)

---

### 3. Win Rate

**Definition**: Percentage of trades that are profitable.

**Formula**:
```
Win Rate = (Number of Winning Trades / Total Trades)
```

**Implementation**:
```python
def calculate_win_rate(trades_df: pd.DataFrame) -> float:
    """Calculate percentage of profitable trades.

    Args:
        trades_df: DataFrame with 'pnl' column (trade profit/loss)

    Returns:
        Win rate as decimal (e.g., 0.65 = 65% win rate)
    """
    if len(trades_df) == 0:
        return 0.0

    winning_trades = (trades_df['pnl'] > 0).sum()
    total_trades = len(trades_df)

    return winning_trades / total_trades
```

**Interpretation**:
- **< 40%**: Poor (needs high profit factor to be profitable)
- **40% - 50%**: Below average
- **50% - 60%**: Average
- **> 60%**: Good
- **> 70%**: Excellent

**Note**: Win rate alone doesn't indicate profitability - a 40% win rate with avg_win = 3 * avg_loss is profitable.

---

### 4. Profit Factor

**Definition**: Ratio of gross profit to gross loss.

**Formula**:
```
Profit Factor = Sum(Winning Trades) / Abs(Sum(Losing Trades))
```

**Implementation**:
```python
def calculate_profit_factor(trades_df: pd.DataFrame) -> float:
    """Calculate ratio of gross profit to gross loss.

    Args:
        trades_df: DataFrame with 'pnl' column

    Returns:
        Profit factor (>1.0 = profitable, >1.5 = strong, >2.0 = excellent)
    """
    if len(trades_df) == 0:
        return 0.0

    gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
    gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum())

    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0

    return gross_profit / gross_loss
```

**Interpretation**:
- **< 1.0**: Unprofitable (losing more than winning)
- **1.0 - 1.5**: Marginally profitable
- **1.5 - 2.0**: Good profitability
- **> 2.0**: Excellent profitability

---

### 5. Additional Metrics

#### Total Return %
```python
def calculate_total_return(initial_capital: float, final_capital: float) -> float:
    """Calculate total return percentage."""
    return ((final_capital - initial_capital) / initial_capital) * 100
```

#### Average Trade P&L
```python
def calculate_avg_trade(trades_df: pd.DataFrame) -> float:
    """Calculate average profit/loss per trade."""
    return trades_df['pnl'].mean()
```

#### Average Win / Average Loss Ratio
```python
def calculate_avg_win_loss_ratio(trades_df: pd.DataFrame) -> float:
    """Calculate ratio of average win to average loss."""
    winning_trades = trades_df[trades_df['pnl'] > 0]['pnl']
    losing_trades = trades_df[trades_df['pnl'] < 0]['pnl']

    if len(losing_trades) == 0:
        return float('inf')

    avg_win = winning_trades.mean()
    avg_loss = abs(losing_trades.mean())

    return avg_win / avg_loss
```

#### Recovery Factor
```python
def calculate_recovery_factor(net_profit: float, max_drawdown: float) -> float:
    """Calculate net profit divided by maximum drawdown.

    Measures how much profit is earned per unit of risk taken.
    Higher is better (>5 is excellent).
    """
    if max_drawdown == 0:
        return float('inf')

    return abs(net_profit / max_drawdown)
```

#### Maximum Consecutive Wins/Losses
```python
def calculate_max_consecutive(trades_df: pd.DataFrame, win: bool = True) -> int:
    """Calculate longest winning or losing streak."""
    if len(trades_df) == 0:
        return 0

    condition = trades_df['pnl'] > 0 if win else trades_df['pnl'] < 0
    streaks = condition.astype(int).groupby((condition != condition.shift()).cumsum()).sum()

    return streaks.max()
```

---

## Comprehensive Performance Report

Combine all metrics into a single report:

```python
def generate_performance_report(
    trades_df: pd.DataFrame,
    equity_curve: pd.Series,
    initial_capital: float,
    risk_free_rate: float = 0.045
) -> dict:
    """Generate comprehensive performance report.

    Returns:
        dict with all performance metrics
    """
    if len(trades_df) == 0:
        return {"error": "No trades to analyze"}

    # Calculate daily returns from equity curve
    daily_returns = equity_curve.pct_change().dropna()

    # Final capital
    final_capital = equity_curve.iloc[-1]

    # Metrics
    report = {
        # Returns
        "total_return_pct": calculate_total_return(initial_capital, final_capital),
        "total_return_dollars": final_capital - initial_capital,

        # Risk-Adjusted
        "sharpe_ratio": calculate_sharpe_ratio(daily_returns, risk_free_rate),
        "max_drawdown_pct": calculate_max_drawdown(equity_curve) * 100,

        # Trade Statistics
        "total_trades": len(trades_df),
        "winning_trades": (trades_df['pnl'] > 0).sum(),
        "losing_trades": (trades_df['pnl'] < 0).sum(),
        "win_rate": calculate_win_rate(trades_df),
        "profit_factor": calculate_profit_factor(trades_df),

        # Per-Trade Metrics
        "avg_trade_pnl": calculate_avg_trade(trades_df),
        "avg_win": trades_df[trades_df['pnl'] > 0]['pnl'].mean(),
        "avg_loss": trades_df[trades_df['pnl'] < 0]['pnl'].mean(),
        "avg_win_loss_ratio": calculate_avg_win_loss_ratio(trades_df),

        # Streaks
        "max_consecutive_wins": calculate_max_consecutive(trades_df, win=True),
        "max_consecutive_losses": calculate_max_consecutive(trades_df, win=False),

        # Recovery
        "recovery_factor": calculate_recovery_factor(
            final_capital - initial_capital,
            calculate_max_drawdown(equity_curve) * initial_capital
        )
    }

    return report
```

---

## Usage Example

```python
# After running backtest simulation
trades_df = fetch_backtest_trades(run_id)
performance_df = fetch_backtest_performance_history(run_id)
equity_curve = performance_df['equity']
initial_capital = 100000.0

# Generate report
report = generate_performance_report(trades_df, equity_curve, initial_capital)

# Output
{
    "total_return_pct": 8.5,
    "sharpe_ratio": 1.42,
    "max_drawdown_pct": -3.2,
    "win_rate": 0.65,
    "profit_factor": 1.8,
    "total_trades": 23,
    "winning_trades": 15,
    "losing_trades": 8,
    "avg_win_loss_ratio": 1.5,
    "recovery_factor": 6.2
}
```

---

## Integration with Agent

The agent will:
1. Fetch backtest results using tools
2. Call these calculation functions
3. Format results into JSON for Portfolio Manager
4. Provide interpretation and recommendations

## Notes

- All calculations are **pure functions** - no database access
- Metrics are **industry-standard** for strategy evaluation
- **Sharpe ratio** is the most important risk-adjusted metric
- **Max drawdown** indicates worst-case scenario risk
- Combine multiple metrics for holistic assessment (don't rely on single metric)
