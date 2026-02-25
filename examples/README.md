# Portfolio Manager - Streaming Examples

This directory contains example clients for testing the SSE streaming endpoint.

## Quick Start

### 1. Start the API Server

```bash
cd D:\Projects\agentic-trader
python src/api/main.py
```

The server will start at `http://localhost:8000`

### 2. Choose a Client

## Python Streaming Client

**Best for:** Command-line usage, automation, testing

```bash
# Single query
python examples/stream_client.py "What's my portfolio status?"

# With custom thread ID
python examples/stream_client.py "Is my portfolio healthy?" --thread my-session-123

# Run demo with multiple queries
python examples/stream_client.py demo
```

**Features:**
- Real-time token streaming
- Tool call notifications
- Execution time tracking
- Error handling

## HTML Browser Client

**Best for:** Interactive testing, visual feedback

1. Open `examples/stream_client.html` in your browser
2. Enter your query
3. Click "Send Query"
4. Watch responses stream in real-time

**Features:**
- Visual interface
- Pre-filled example queries
- Real-time response display
- Tool call badges
- Status indicators

## curl Command

**Best for:** Quick testing, shell scripts

```bash
# Basic query
curl -N -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"query": "What is my portfolio status?"}'

# With thread context
curl -N -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "query": "Should I buy AAPL?",
    "thread_id": "my-session",
    "apply_middleware": true
  }'
```

**Note:** The `-N` flag disables buffering for real-time streaming.

## SSE Event Types

The streaming endpoint sends the following event types:

### `start`
Sent at the beginning of the query
```json
{
  "type": "start",
  "query": "What's my portfolio status?",
  "thread_id": "session-123",
  "timestamp": "2026-02-25T16:30:00"
}
```

### `token`
Sent as the agent generates response text
```json
{
  "type": "token",
  "content": "Your portfolio is currently valued at "
}
```

### `tool_start`
Sent when a tool is being called
```json
{
  "type": "tool_start",
  "tool": "get_portfolio_status"
}
```

### `tool_end`
Sent when a tool completes
```json
{
  "type": "tool_end",
  "tool": "get_portfolio_status"
}
```

### `done`
Sent when the query completes successfully
```json
{
  "type": "done",
  "response": "Full response text...",
  "execution_time_ms": 5230,
  "timestamp": "2026-02-25T16:30:05",
  "thread_id": "session-123"
}
```

### `error`
Sent if an error occurs
```json
{
  "type": "error",
  "error": "Market is CLOSED. Current time: ...",
  "blocked_by": "MarketHoursGuardMiddleware"
}
```

## Example Queries

### Portfolio Management
- "What's my portfolio status?"
- "Show me my current positions with P&L"
- "Is my portfolio healthy?"
- "What's my buying power?"
- "How many positions do I have?"

### Technical Analysis
- "Should I buy AAPL? Run technical analysis."
- "Analyze TSLA using mean reversion strategy"
- "What's the RSI for MSFT?"
- "Calculate MACD for NVDA"
- "Show me Bollinger Bands for SPY"

### Multi-Turn Conversations
```bash
# Turn 1
python examples/stream_client.py "What's my buying power?" --thread multi-1

# Turn 2 (same thread for context)
python examples/stream_client.py "Can I buy 100 shares of AAPL?" --thread multi-1
```

## Troubleshooting

### Server Not Running
```
Error: Connection refused
```
**Solution:** Make sure the API server is running at `http://localhost:8000`

### Middleware Blocking
```
Error: Market is CLOSED
```
**Solution:** Either wait for market hours (Mon-Fri 9:30 AM - 4:00 PM ET) or enable backtest mode:
- Edit `src/api/main.py` line 54
- Change `backtest_mode=False` to `backtest_mode=True`
- Restart the server

### No Response Streaming
**Solution:** Make sure you're using the correct headers:
- `Content-Type: application/json`
- `Accept: text/event-stream`

## Advanced Usage

### Custom Client Implementation

```python
import requests
import json

def stream_query(query, thread_id="my-session"):
    url = "http://localhost:8000/query"
    payload = {"query": query, "thread_id": thread_id}

    response = requests.post(
        url,
        json=payload,
        headers={"Accept": "text/event-stream"},
        stream=True
    )

    for line in response.iter_lines():
        if line and line.startswith(b'data: '):
            data = json.loads(line[6:])
            event_type = data.get("type")

            if event_type == "token":
                print(data["content"], end="", flush=True)
            elif event_type == "done":
                print(f"\n\nDone in {data['execution_time_ms']}ms")

# Use it
stream_query("What's my portfolio status?")
```

### JavaScript/Node.js

```javascript
const EventSource = require('eventsource');

async function streamQuery(query, threadId = 'js-session') {
    const url = 'http://localhost:8000/query';
    const payload = { query, thread_id: threadId, apply_middleware: true };

    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                const event = JSON.parse(line.slice(6));
                if (event.type === 'token') {
                    process.stdout.write(event.content);
                }
            }
        }
    }
}

streamQuery("What's my portfolio status?");
```

## Performance Tips

1. **Keep threads alive:** Reuse the same `thread_id` for related queries to maintain context
2. **Monitor execution time:** Use the `execution_time_ms` from done events to track performance
3. **Handle tool calls:** Display tool call events to show progress during long operations
4. **Error recovery:** Implement retry logic with exponential backoff for transient errors

## Resources

- API Documentation: http://localhost:8000/docs
- Server Logs: `logs/app_YYYY-MM-DD.log`
- Error Logs: `logs/errors_YYYY-MM-DD.log`
