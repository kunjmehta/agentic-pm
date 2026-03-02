---
name: backtest-orchestration
description: Orchestrate full backtest workflow from user query to final report. Handles parameter extraction, multi-day simulation, and result presentation.
license: MIT
metadata:
  author: agentic-trader
  version: "1.0"
  category: workflow
allowed-tools: bash
---

# backtest-orchestration

## Overview

High-level workflow that coordinates backtest execution from natural language queries like "backtest mean-reversion strategy on AAPL from Jan 2024". This skill acts as the conductor, using simulation-engine for execution and performance-metrics for analysis.

## When to Use

- User requests a backtest via natural language
- Need to execute multi-day or multi-week simulations
- Coordinating between fetching data, running simulations, calculating metrics, and saving results
- Translating vague queries into specific backtest parameters

## Workflow Steps

### Step 1: Parse User Query

Extract backtest parameters from natural language:

```python
def parse_backtest_query(query: str) -> dict:
    """Extract parameters from natural language query.

    Examples:
        "Backtest mean-reversion on AAPL from Jan 2024"
        → strategy=mean-reversion, symbol=AAPL, start=2024-01-01, end=2024-01-31

        "Test momentum strategy last week"
        → strategy=momentum, symbol=AAPL (default), start=7 days ago, end=today

        "How would this strategy have performed in February?"
        → strategy=(from context), symbol=AAPL, start=2024-02-01, end=2024-02-29

    Returns:
        {
            "strategy_name": str,
            "symbol": str,
            "start_date": str (ISO format),
            "end_date": str (ISO format),
            "initial_capital": float,
            "parameters": dict (strategy-specific)
        }
    """
```

**Default Values**:
- `symbol`: "AAPL" (if not specified)
- `initial_capital`: 100000.0 ($100k)
- `start_date`: 30 days ago (if "last month" mentioned)
- `end_date`: today (if not specified)
- `strategy_name`: Extract from query or use "mean-reversion" as default

**Extraction Patterns**:
- **Strategy**: Look for keywords (mean-reversion, momentum, value, breakout)
- **Symbol**: CAPS ticker symbols (AAPL, MSFT, TSLA)
- **Date Range**:
  - "from X to Y"
  - "in January 2024"
  - "last week/month"
  - "Q1 2024"

---

### Step 2: Validate Parameters

```python
def validate_backtest_params(params: dict) -> tuple[bool, str]:
    """Validate backtest parameters.

    Checks:
        - Date range is historical (no future dates)
        - Start date < end date
        - Symbol is valid
        - Initial capital > 0
        - Strategy name is recognized

    Returns:
        (is_valid, error_message)
    """
```

**Validation Rules**:
- Start date must be in the past
- End date must be <= today
- Date range must be >= 1 day
- Initial capital must be > 0
- Symbol must be in watchlist or valid ticker
- Strategy must exist in available strategies

---

### Step 3: Fetch Historical Data

Use tools to retrieve market data:

```python
def fetch_data_for_backtest(symbol: str, start_date: str, end_date: str) -> dict:
    """Fetch historical bars using tools.

    Returns:
        {
            "bars": list of OHLCV dicts,
            "total_bars": int,
            "date_range": str,
            "has_gaps": bool
        }
    """
    # Use fetch_historical_bars_for_backtest tool
    result = fetch_historical_bars_for_backtest(symbol, start_date, end_date, "1Min")

    # Check for data quality
    if len(result['bars']) == 0:
        raise ValueError(f"No historical data available for {symbol}")

    # Check for gaps (missing trading days)
    detect_data_gaps(result['bars'])

    return result
```

**Data Quality Checks**:
- Ensure sufficient data (at least 1 full trading day)
- Detect missing bars or gaps
- Validate OHLCV integrity (no negative prices, volume >= 0)

---

### Step 4: Get Strategy Signals (Optional)

Check if strategy signals are pre-calculated in database:

```python
def get_strategy_signals(symbol: str, strategy_name: str, start_date: str, end_date: str) -> Optional[list]:
    """Fetch pre-calculated strategy signals if available.

    Returns:
        List of signal dicts or None if not available
    """
    # Query StrategyDAO for signals
    # If not available, simulation-engine will calculate on-the-fly
```

---

### Step 5: Run Simulation

Execute simulation using simulation-engine skill:

```python
def run_backtest_simulation(params: dict, bars_data: dict) -> dict:
    """Execute backtest simulation.

    For single-day:
        - Run simulation-engine once

    For multi-day:
        - Loop through days
        - Run simulation-engine for each day
        - Compound results (carry forward positions and capital)

    Returns:
        {
            "run_id": str,
            "trades": list,
            "daily_performance": list,
            "final_equity": float
        }
    """
```

**Multi-Day Simulation Logic**:
```python
initial_capital = params['initial_capital']
current_capital = initial_capital
all_trades = []
daily_snapshots = []

# Group bars by day
bars_by_day = group_bars_by_date(bars_data['bars'])

for date, day_bars in bars_by_day.items():
    # Run simulation for this day
    day_result = simulate_day(
        bars=day_bars,
        initial_capital=current_capital,
        strategy=params['strategy_name'],
        strategy_params=params['parameters']
    )

    # Accumulate results
    all_trades.extend(day_result['trades'])
    daily_snapshots.append({
        "date": date,
        "equity": day_result['eod_equity'],
        "pnl": day_result['daily_pnl'],
        "return_pct": day_result['daily_return_pct']
    })

    # Update capital for next day (compounding)
    current_capital = day_result['eod_equity']

return {
    "trades": all_trades,
    "daily_performance": daily_snapshots,
    "final_equity": current_capital
}
```

---

### Step 6: Calculate Performance Metrics

Use performance-metrics skill to calculate all metrics:

```python
def calculate_backtest_metrics(simulation_results: dict, initial_capital: float) -> dict:
    """Calculate comprehensive performance metrics.

    Uses performance-metrics skill functions:
        - calculate_sharpe_ratio()
        - calculate_max_drawdown()
        - calculate_win_rate()
        - calculate_profit_factor()

    Returns:
        {
            "sharpe_ratio": float,
            "max_drawdown_pct": float,
            "win_rate": float,
            "profit_factor": float,
            "total_return_pct": float,
            ...
        }
    """
```

---

### Step 7: Save Results

Persist backtest results to database:

```python
def save_backtest_to_db(params: dict, simulation_results: dict, metrics: dict) -> str:
    """Save backtest run to database using tools.

    Saves:
        - Run metadata (save_backtest_run_to_db)
        - Individual trades (to backtest_trades table)
        - Daily performance (to backtest_performance table)
        - Final metrics (update backtest_runs table)

    Returns:
        run_id: UUID for the backtest run
    """
```

---

### Step 8: Generate Report

Format results as JSON for Portfolio Manager:

```python
def generate_backtest_report(params: dict, metrics: dict, run_id: str) -> dict:
    """Format backtest results for output.

    Returns:
        {
            "run_id": str,
            "status": "completed",
            "strategy": str,
            "symbol": str,
            "period": {"start": str, "end": str},
            "performance": {
                "total_return_pct": float,
                "sharpe_ratio": float,
                "max_drawdown_pct": float,
                "win_rate": float,
                "profit_factor": float,
                "total_trades": int,
                "winning_trades": int,
                "losing_trades": int
            },
            "summary": str (human-readable interpretation),
            "recommendation": str
        }
    """
```

**Summary Generation**:
```python
summary = f"{params['strategy_name']} strategy on {params['symbol']} "
summary += f"achieved {metrics['total_return_pct']:.1f}% return "
summary += f"over {days} days with Sharpe ratio {metrics['sharpe_ratio']:.2f}. "
summary += f"Win rate: {metrics['win_rate']*100:.0f}%. "
summary += f"Maximum drawdown: {metrics['max_drawdown_pct']:.1f}%."
```

**Recommendation Logic**:
```python
if metrics['sharpe_ratio'] > 2.0 and metrics['max_drawdown_pct'] > -10:
    recommendation = "STRONG CANDIDATE for live trading (excellent risk-adjusted returns)"
elif metrics['sharpe_ratio'] > 1.0 and metrics['max_drawdown_pct'] > -15:
    recommendation = "CONSIDER for live trading with careful monitoring"
elif metrics['total_return_pct'] > 0:
    recommendation = "PROFITABLE but high risk - improve drawdown control"
else:
    recommendation = "NOT RECOMMENDED - strategy shows negative returns"
```

---

## Complete Workflow Example

```python
# User query
query = "Backtest mean-reversion strategy on AAPL from January to February 2024"

# Step 1: Parse
params = parse_backtest_query(query)
# → {
#     "strategy_name": "mean-reversion",
#     "symbol": "AAPL",
#     "start_date": "2024-01-01",
#     "end_date": "2024-02-29",
#     "initial_capital": 100000.0,
#     "parameters": {"window": 20, "z_threshold": 2.0}
#   }

# Step 2: Validate
is_valid, error = validate_backtest_params(params)
# → (True, "")

# Step 3: Fetch data
bars_data = fetch_data_for_backtest(params['symbol'], params['start_date'], params['end_date'])
# → {"bars": [...], "total_bars": 7800}  # ~40 trading days * 390 bars/day

# Step 4: Get signals (optional)
signals = get_strategy_signals(params['symbol'], params['strategy_name'], ...)
# → None (calculate on-the-fly)

# Step 5: Run simulation
simulation_results = run_backtest_simulation(params, bars_data)
# → {"trades": [...], "daily_performance": [...], "final_equity": 108500.0}

# Step 6: Calculate metrics
metrics = calculate_backtest_metrics(simulation_results, params['initial_capital'])
# → {"sharpe_ratio": 1.42, "max_drawdown_pct": -3.2, "win_rate": 0.65, ...}

# Step 7: Save results
run_id = save_backtest_to_db(params, simulation_results, metrics)
# → "abc-123-def-456"

# Step 8: Generate report
report = generate_backtest_report(params, metrics, run_id)
# → {
#     "run_id": "abc-123-def-456",
#     "status": "completed",
#     "strategy": "mean-reversion",
#     "performance": {...},
#     "summary": "Mean-reversion strategy achieved 8.5% return...",
#     "recommendation": "CONSIDER for live trading with careful monitoring"
#   }
```

---

## Handling Natural Language Queries

### Example Queries

| Query | Interpretation |
|-------|----------------|
| "Backtest mean-reversion on AAPL" | Last 30 days, default params |
| "Test this strategy" | Use context from previous conversation |
| "How would momentum have performed last month?" | Momentum strategy, AAPL, last calendar month |
| "Run backtest from Jan to Feb 2024" | Use default strategy, AAPL, specified dates |
| "Backtest TSLA with mean-reversion" | TSLA, mean-reversion, last 30 days |

### Context Preservation

The agent maintains conversation context:
- If user says "this strategy", refer to strategy mentioned earlier
- If user says "test it", refer to previous backtest parameters
- Thread ID ensures context continuity

---

## Error Handling

### Common Errors & Resolutions

| Error | Resolution |
|-------|-----------|
| No historical data | Suggest data ingestion or different date range |
| Invalid date range | Provide valid format and constraints |
| Strategy not found | List available strategies |
| Insufficient capital | Suggest minimum capital requirements |
| Data gaps | Note missing days, proceed with available data |

---

## Integration Points

### Tools Used
- `fetch_historical_bars_for_backtest()` - Get market data
- `save_backtest_run_to_db()` - Persist results

### Skills Used
- `simulation-engine` - Execute simulations
- `performance-metrics` - Calculate metrics

### DAO Access (via Tools)
- BacktestDAO - Store/retrieve backtest runs
- AlpacaDAO - Historical bars
- StrategyDAO - Pre-calculated signals (optional)

---

## Notes

- This skill is the **entry point** for all backtest requests
- It translates **natural language → structured execution**
- Handles both **single-day and multi-day** backtests
- Provides **context-aware** query interpretation
- Generates **actionable recommendations** based on metrics
- All data access goes through **tools** (no direct DAO calls)
