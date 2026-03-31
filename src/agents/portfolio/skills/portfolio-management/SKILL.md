# Portfolio Management

**Description**: Comprehensive portfolio health analysis, historical performance tracking, and risk monitoring for the Portfolio Manager agent.

## Overview

This skill provides the Portfolio Manager with capabilities to:
- Monitor portfolio health against risk parameters
- Track historical performance and P&L trends
- Generate risk compliance reports
- Analyze portfolio snapshots over time
- Delegate technical analysis to Quant Analyst

## Available Functions

### 1. get_portfolio_status()

Fetches current portfolio status from Alpaca with caching.

**Returns**: JSON with:
- `equity`: Total portfolio value
- `cash`: Available cash
- `buying_power`: Margin buying power
- `long_positions`: Number of long positions
- `short_positions`: Number of short positions
- `portfolio_value`: Current portfolio value
- `cached`: Whether result is from cache

**Caching**: Results cached for 5 minutes to reduce API calls.

**Example Usage**:
```python
status = get_portfolio_status()
# Returns current account status with position counts
```

### 2. get_positions_summary()

Fetches detailed position information with P&L breakdown.

**Returns**: JSON with:
- `positions`: Array of position objects with:
  - `symbol`: Stock ticker
  - `qty`: Quantity held
  - `side`: "long" or "short"
  - `market_value`: Current market value
  - `cost_basis`: Total cost basis
  - `unrealized_pl`: Unrealized profit/loss
  - `unrealized_plpc`: P&L percentage
  - `current_price`: Current market price
  - `avg_entry_price`: Average entry price
- `count`: Total number of positions
- `total_market_value`: Sum of all position values
- `total_unrealized_pl`: Total unrealized P&L

**Caching**: Results cached for 5 minutes.

**Example Usage**:
```python
positions = get_positions_summary()
# Returns all positions with P&L details
```

### 3. check_portfolio_health()

Validates portfolio against risk parameters from database.

**Risk Checks**:
- **Position Concentration**: Each position should be < position_limit_percent (default: 10%) of portfolio
- **Position Size**: Each position should be < max_position_size (default: 1500 shares)
- **Cash Reserves**: Portfolio should maintain at least 5% cash

**Returns**: JSON with:
- `health_status`: "healthy", "warning", or "unhealthy"
- `violations`: Array of rule violations (blocks trading)
- `warnings`: Array of warnings (advisory only)
- `checks_performed`: List of checks executed
- `risk_parameters_used`: Risk limits applied

**Risk Parameters Source**: `portfolio_parameters` table in DuckDB

**Example Usage**:
```python
health = check_portfolio_health()
# Returns health status with any violations or warnings
```

### 4. delegate_to_quant_analyst()

Delegates technical analysis queries to the Quant Analyst agent.

**Use Cases**:
- Stock analysis requests
- Technical indicator calculations
- Trading strategy recommendations
- Mean reversion signals
- Momentum analysis

**Parameters**:
- `query`: Analysis query to pass to Quant Analyst
- `thread_id`: Conversation thread ID (for context preservation)

**Returns**: JSON with:
- `status`: "success" or "error"
- `response`: Quant Analyst's analysis
- `delegated_to`: "quant_analyst"
- `timestamp`: Analysis timestamp

**Graceful Degradation**: If Quant Analyst is unavailable, returns error status with fallback message.

**Example Usage**:
```python
result = delegate_to_quant_analyst(
    query="Analyze AAPL using mean reversion strategy",
    thread_id="user-123"
)
# Returns technical analysis from Quant Analyst
```

## Workflow Examples

### Daily Portfolio Check

```
1. User: "How is my portfolio doing today?"
2. Agent calls: get_portfolio_status()
3. Agent calls: check_portfolio_health()
4. Agent responds with:
   - Current equity and cash
   - Daily P&L
   - Health status
   - Any warnings or violations
```

### Position Analysis

```
1. User: "Show me my current positions"
2. Agent calls: get_positions_summary()
3. Agent responds with:
   - List of all positions
   - Individual P&L for each
   - Total unrealized P&L
   - Market value breakdown
```

### Risk Compliance Check

```
1. User: "Am I within risk limits?"
2. Agent calls: check_portfolio_health()
3. Agent checks:
   - Position concentration (< 10% per position)
   - Position sizes (< 1500 shares)
   - Cash reserves (> 5%)
4. Agent responds with violations or "All clear"
```

### Technical Analysis Request

```
1. User: "Should I buy TSLA?"
2. Agent calls: delegate_to_quant_analyst(
     query="Analyze TSLA for buy signal using technical indicators",
     thread_id=current_thread
   )
3. Quant Analyst performs:
   - RSI, MACD, Bollinger Bands analysis
   - Mean reversion check
   - Strategy recommendation
4. Agent responds with technical analysis summary
```

## Risk Parameters

Risk limits are stored in the `portfolio_parameters` table and can be updated via PortfolioDAO:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `position_limit_percent` | 0.1 (10%) | Max % of portfolio per position |
| `max_position_size` | 1500 | Max shares per position |
| `daily_loss_limit` | 0.05 (5%) | Max daily loss before halt |
| `max_daily_trades` | 10 | Max trades per day |
| `stop_loss_percent` | 0.02 (2%) | Default stop loss |

**Updating Parameters**:
```python
from src.dao import PortfolioDAO
dao = PortfolioDAO()
dao.update_risk_parameter("max_position_size", {"value": 2000, "unit": "shares"})
dao.close()
```

## Performance Tracking

All tool executions are tracked for observability:
- Execution time per tool (in milliseconds)
- Success/error status
- Cached vs fresh API calls

Tool timings are captured by `ToolTracingCallback` and can be logged to `agent_interactions` table for performance analysis.

## Caching Strategy

To reduce API calls and improve performance:
- **Portfolio status**: 5-minute TTL
- **Positions summary**: 5-minute TTL
- **Graceful degradation**: Returns stale cache on API failure

Cache benefits:
- ~90% reduction in API calls for repeated queries
- Faster response times (< 50ms for cache hits)
- Resilience during API outages

## Error Handling

All functions implement graceful degradation:
1. **API Failures**: Return cached data if available, otherwise clear error message
2. **DAO Failures**: Log warning, continue with limited functionality
3. **Quant Delegation Failures**: Return error status with recommendation to retry

## Integration with Middleware

Portfolio Manager uses these middleware components:
1. **MarketHoursGuardMiddleware**: Blocks execution outside NYSE hours (9:30 AM - 4:00 PM ET, Mon-Fri)
2. **PortfolioGuardMiddleware**: Enforces daily loss limits, blocks trading if exceeded
3. **TracingMiddleware**: Logs all tool calls and responses
4. **PrettifyMiddleware**: Formats JSON outputs for readability

## Best Practices

1. **Check Health First**: Always check portfolio health before making trading decisions
2. **Use Caching**: Repeated queries within 5 minutes use cached data
3. **Delegate Technical Analysis**: Use Quant Analyst for indicator calculations
4. **Monitor Risk Limits**: Review violations immediately
5. **Track Performance**: Analyze tool timings for optimization

## Example Session

```
User: "What's my portfolio status and should I buy more AAPL?"

Agent Process:
1. get_portfolio_status() → Equity: $105,000, Cash: $52,000
2. check_portfolio_health() → Status: healthy, no violations
3. get_positions_summary() → Currently hold 10 AAPL shares
4. delegate_to_quant_analyst(
     "Analyze AAPL for additional buy signal",
     thread_id="user-123"
   ) → Quant analysis: RSI 45, mean reversion signal: BUY

Agent Response:
"Your portfolio is healthy with $105,000 equity and $52,000 cash available.
You currently hold 10 AAPL shares. Based on technical analysis from our Quant
Analyst, AAPL shows a BUY signal with RSI at 45 (oversold territory) and
mean reversion indicators suggesting upside potential. You have sufficient
buying power and are within risk limits for additional AAPL exposure."
```

## Notes

- All functions use Skills layer for API calls (no direct API access)
- Portfolio snapshots automatically saved to database for historical tracking
- Risk parameters can be customized per trading strategy
- Thread IDs preserve conversation context across delegations
- Backtest mode bypasses all guards for testing
