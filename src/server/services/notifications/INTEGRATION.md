# Notification System Integration Guide

This document describes how to integrate notifications at all critical event points across the trading system.

## ✅ Completed Integrations

### 1. Backtest Strategy Skill
**File**: `src/server/skills/backtester/backtest_strategy.py`

**Integration Points**:
- ✅ Backtest completion (line ~250)
- ✅ Backtest failure (line ~253)

**Usage**:
```python
# On success
await notify_backtest_completed(
    backtest_id=result.get("run_id", "unknown"),
    strategy=strategy,
    symbol=ticker,
    timeframe="historical",
    sharpe_ratio=metrics.get("sharpe_ratio"),
    total_return=metrics.get("total_return_pct"),
    max_drawdown=metrics.get("max_drawdown_pct")
)

# On failure
await notify_backtest_failed(
    backtest_id="unknown",
    strategy=strategy,
    symbol=ticker,
    timeframe="historical",
    error_message=str(exc)
)
```

### 2. Backtest Scheduler
**File**: `src/server/services/backtest_scheduler.py`

**Integration Points**:
- ✅ Scheduled backtest completion (line ~156)
- ✅ Scheduled backtest failure (line ~162)

**Usage**:
```python
# On completion
await notify_backtest_completed(
    backtest_id=thread_id,
    strategy=backtest_config.get('strategy', 'unknown'),
    symbol=symbol,
    timeframe=backtest_config.get('timeframe', 'unknown')
)

# On failure
await notify_backtest_failed(
    backtest_id=thread_id,
    strategy=backtest_config.get('strategy', 'unknown'),
    symbol=symbol,
    timeframe=backtest_config.get('timeframe', 'unknown'),
    error_message=str(exc)
)
```

## 📋 Remaining Integration Points

### 3. Order Execution (Router)
**File**: `src/server/routers/orders.py`

**Integration Points**:
- Order fill confirmations (after successful order execution)
- Order rejections (when broker rejects order)

**Recommended Code**:
```python
# Add to imports
from src.server.services.notifications.helpers import (
    notify_order_filled,
    notify_order_rejected
)

# After successful order fill (in execute_order, stop, stop_limit endpoints)
if order_status == "filled":
    await notify_order_filled(
        order_id=order.id,
        symbol=order.symbol,
        side=order.side,
        qty=order.qty,
        filled_qty=order.filled_qty,
        avg_fill_price=order.avg_fill_price,
        order_type=order.order_type
    )

# After order rejection
if order_status == "rejected":
    await notify_order_rejected(
        order_id=order.id,
        symbol=order.symbol,
        side=order.side,
        qty=order.qty,
        rejection_reason=order.rejection_reason,
        order_type=order.order_type
    )
```

### 4. Agent Errors (Router)
**File**: `src/server/routers/agent.py`

**Integration Points**:
- Line ~106-110: Graph invocation errors
- Line ~349+: General agent execution errors

**Recommended Code**:
```python
# Add to imports
from src.server.services.notifications.helpers import notify_agent_error

# Wrap graph invocation in try/except
try:
    result = await graph.ainvoke(initial_state, config)
except Exception as exc:
    logger.error(f"Graph invocation failed: {exc}", exc_info=True)

    # Send notification
    await notify_agent_error(
        agent_name="portfolio_manager",  # or extract from state
        thread_id=thread_id,
        error=exc,
        node_name=None,  # Can extract from traceback if needed
        recoverable=False,
        severity=NotificationSeverity.ERROR
    )

    raise HTTPException(status_code=500, detail=str(exc))
```

### 5. Autonomous Trading Cycles
**File**: `src/server/lifespan.py`

**Integration Points**:
- Line ~249-346: `_run_periodic_signal_processing()` function
- Line ~340-342: Cycle errors

**Recommended Code**:
```python
# Add to imports at top
from src.server.services.notifications.helpers import notify_agent_error

# In exception handler (around line ~340)
except Exception as exc:
    logger.error(f"[autonomous] Error in signal processing cycle: {exc}", exc_info=True)

    # Send notification for autonomous cycle errors
    await notify_agent_error(
        agent_name="autonomous_trader",
        thread_id=f"autonomous_{int(time.time())}",
        error=exc,
        node_name="signal_processing_cycle",
        recoverable=True,  # Continue running despite errors
        severity=NotificationSeverity.ERROR
    )
```

### 6. Stream Errors
**File**: `src/server/lifespan.py`

**Integration Points**:
- Line ~215-246: `_run_live_streams()` function
- Line ~239-240: Stream errors

**Recommended Code**:
```python
# Add to imports
from src.server.services.notifications.helpers import notify_agent_error

# In exception handler (around line ~239)
except Exception as exc:
    logger.error(f"[streams] unexpected error: {exc}", exc_info=True)

    # Send notification for critical stream failures
    await notify_agent_error(
        agent_name="data_stream",
        thread_id="live_stream",
        error=exc,
        node_name="stream_loop",
        recoverable=False,  # Stream failures are critical
        severity=NotificationSeverity.CRITICAL
    )
```

### 7. Portfolio Events
**File**: `src/server/routers/portfolio.py` (or appropriate location)

**Integration Points**:
- Significant portfolio value changes
- Margin call warnings
- Drawdown thresholds
- Target achievement

**Recommended Code**:
```python
# Add to imports
from src.server.services.notifications.helpers import notify_portfolio_event

# Monitor portfolio changes
if abs(daily_pnl_pct) > 5.0:  # Example: 5% daily change
    await notify_portfolio_event(
        portfolio_value=portfolio_value,
        cash_balance=cash_balance,
        positions_count=len(positions),
        change_reason="large_daily_movement",
        daily_pnl=daily_pnl,
        daily_pnl_pct=daily_pnl_pct,
        severity=NotificationSeverity.WARNING
    )

# Drawdown threshold
if max_drawdown_pct < -10.0:  # Example: 10% drawdown
    await notify_portfolio_event(
        portfolio_value=portfolio_value,
        cash_balance=cash_balance,
        positions_count=len(positions),
        change_reason="drawdown_threshold",
        daily_pnl=daily_pnl,
        daily_pnl_pct=daily_pnl_pct,
        severity=NotificationSeverity.CRITICAL
    )
```

### 8. Redis Stream Errors
**File**: `src/server/lifespan.py`

**Integration Points**:
- Redis connection failures
- Stream consumer errors

**Recommended Code**:
```python
# Add error handling to Redis stream consumers
try:
    # Redis stream operations
    pass
except Exception as exc:
    logger.error(f"[redis] Stream error: {exc}", exc_info=True)

    await notify_agent_error(
        agent_name="redis_consumer",
        thread_id="redis_stream",
        error=exc,
        node_name="stream_consumer",
        recoverable=True,
        severity=NotificationSeverity.ERROR
    )
```

## Configuration

### Enabling Notifications

Edit `config/config.json`:

```json
{
  "notifications": {
    "enabled": true,
    "email": {
      "enabled": true,
      "api_key": "${SENDGRID_API_KEY}",
      "from_email": "trading@yourcompany.com",
      "to_emails": ["alerts@yourcompany.com"],
      "min_severity": "WARNING"
    },
    "slack": {
      "enabled": true,
      "webhook_url": "${SLACK_WEBHOOK_URL}",
      "min_severity": "ERROR"
    },
    "webhook": {
      "enabled": false,
      "url": "${WEBHOOK_URL}",
      "min_severity": "INFO"
    }
  }
}
```

### Setting Up Secrets

Add to `secret.json`:

```json
{
  "SENDGRID_API_KEY": "SG.xxx",
  "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/xxx"
}
```

Or set environment variables:
```bash
export SENDGRID_API_KEY="SG.xxx"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/xxx"
```

## Testing

### Unit Tests
```bash
pytest tests/test_notifications.py -v
```

### Integration Test
```bash
# Run a backtest and verify notifications
python -c "
import asyncio
from src.server.services.notifications.helpers import notify_backtest_completed

async def test():
    await notify_backtest_completed(
        backtest_id='test_123',
        strategy='mean_reversion',
        symbol='AAPL',
        timeframe='1Min',
        sharpe_ratio=1.85,
        total_return=12.5,
        max_drawdown=-3.2
    )

asyncio.run(test())
"
```

### Manual Test
Create `tests/manual_notification_test.py`:

```python
import asyncio
from src.server.services.notifications import get_notification_service
from src.server.services.notifications.models import BacktestEvent, NotificationSeverity
from src.common.utils import config

async def main():
    # Load config
    notification_config = config.get("notifications", default={})

    # Get service
    service = await get_notification_service(notification_config)

    # Create test event
    event = BacktestEvent(
        title="Manual Test: Backtest Completed",
        message="This is a manual test notification",
        severity=NotificationSeverity.INFO,
        backtest_id="manual_test_123",
        strategy="test_strategy",
        symbol="TEST",
        timeframe="1Min",
        status="completed",
        sharpe_ratio=1.5,
        total_return=10.0,
        max_drawdown=-2.5
    )

    # Send
    result = await service.notify(event)
    print(f"Notification sent: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Troubleshooting

### Notifications Not Sending

1. Check service is enabled: `config.json` → `notifications.enabled: true`
2. Check channel is enabled: `config.json` → `notifications.email.enabled: true`
3. Verify secrets are set: Check `secret.json` or environment variables
4. Check severity filtering: Event severity must meet channel's `min_severity`
5. Review logs: Look for `[notifications]` log entries

### SendGrid Errors

- **API key invalid**: Verify key in secret.json starts with `SG.`
- **403 Forbidden**: Check sender email is verified in SendGrid
- **Rate limiting**: Review SendGrid plan limits

### Slack Webhook Errors

- **400 Bad Request**: Check webhook URL format
- **Invalid webhook**: Regenerate webhook in Slack app settings

## Architecture Summary

```
NotificationService (Singleton)
├── EmailChannel (SendGrid)
│   ├── HTML templates
│   ├── Severity filtering
│   └── Graceful degradation
├── SlackChannel (Webhooks)
│   ├── Color-coded attachments
│   ├── Severity filtering
│   └── Graceful degradation
└── WebhookChannel (Generic HTTP)
    ├── JSON payloads
    ├── Severity filtering
    └── Graceful degradation

Event Models
├── BacktestEvent
├── OrderEvent
├── AgentErrorEvent
└── PortfolioEvent

Helper Functions
├── notify_backtest_completed()
├── notify_backtest_failed()
├── notify_order_filled()
├── notify_order_rejected()
├── notify_agent_error()
└── notify_portfolio_event()
```

## Performance Considerations

- Notifications are sent asynchronously via `asyncio.create_task()` to avoid blocking
- Channels timeout after 10 seconds by default
- Failed notifications are logged but don't crash the application
- Multiple channels receive notifications concurrently
- Service uses singleton pattern to avoid re-initialization

## Future Enhancements

1. **SMS notifications** via Twilio
2. **PagerDuty integration** for critical alerts
3. **Notification history** stored in database
4. **Rate limiting** to prevent notification spam
5. **Notification templates** with variable substitution
6. **Notification preferences** per user
7. **Digest mode** (batch notifications hourly/daily)
8. **Mobile push notifications**
