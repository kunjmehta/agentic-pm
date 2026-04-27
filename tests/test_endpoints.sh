#!/usr/bin/env bash
BASE="http://127.0.0.1:8000"
ok=0; fail=0; skip=0

check() {
  local label=$1 method=$2 url=$3 body=$4 expected=${5:-200}
  if [ -n "$body" ]; then
    got=$(curl -s -X "$method" "$url" -H "Content-Type: application/json" -d "$body" -o /tmp/resp.txt -w "%{http_code}" --max-time 20)
  else
    got=$(curl -s -X "$method" "$url" -o /tmp/resp.txt -w "%{http_code}" --max-time 20)
  fi
  snippet=$(cat /tmp/resp.txt | head -c 120)
  if [ "$got" = "$expected" ]; then
    echo "  OK  [$got] $label"
    ok=$((ok+1))
  else
    echo " FAIL [$got] $label => $snippet"
    fail=$((fail+1))
  fi
}
skipfn() { echo " SKIP $1"; skip=$((skip+1)); }

echo "── ROOT / HEALTH ──"
check "GET  /" GET "$BASE/"
check "GET  /v1/health" GET "$BASE/v1/health"
check "GET  /v1/health/detailed" GET "$BASE/v1/health/detailed"
check "GET  /v1/registry" GET "$BASE/v1/registry"

echo "── ADMIN ──"
check "GET  /v1/admin/stats" GET "$BASE/v1/admin/stats"
check "POST /v1/admin/cleanup?dry_run=true" POST "$BASE/v1/admin/cleanup?dry_run=true"

echo "── CONFIG ──"
check "GET  /v1/config" GET "$BASE/v1/config"
check "GET  /v1/config/ui" GET "$BASE/v1/config/ui"
check "GET  /v1/config/scheduled-backtests" GET "$BASE/v1/config/scheduled-backtests"
check "GET  /v1/config/watchlist" GET "$BASE/v1/config/watchlist"
check "GET  /v1/config/graph_api" GET "$BASE/v1/config/graph_api"
check "POST /v1/config/reload" POST "$BASE/v1/config/reload"
skipfn "PUT  /v1/config/ui (modifies config)"
skipfn "PUT  /v1/config/{section} (modifies config)"
skipfn "POST /v1/config/watchlist/add (modifies watchlist)"
skipfn "DELETE /v1/config/watchlist/{sym} (modifies watchlist)"

echo "── AGENT / CONVERSATIONS ──"
check "GET  /v1/conversations/test-thread" GET "$BASE/v1/conversations/test-thread?limit=5"
check "GET  /v1/agent/state/test-thread" GET "$BASE/v1/agent/state/test-thread"
check "POST /v1/reject/nonexistent" POST "$BASE/v1/reject/nonexistent"
skipfn "POST /v1/query (LLM call)"
skipfn "POST /v1/query/stream (SSE)"
skipfn "POST /v1/approve/{id} (HITL)"
skipfn "POST /v1/approve/stream/{id} (SSE)"
check "GET  /v1/telemetry/stream/fake (SSE connect)" GET "$BASE/v1/telemetry/stream/fake-thread" "" 200

echo "── ANALYST ──"
check "GET  /v1/analyst/symbols" GET "$BASE/v1/analyst/symbols"
check "GET  /v1/analyst/AAPL/eod" GET "$BASE/v1/analyst/AAPL/eod?start=2024-01-01&end=2024-01-31"
check "GET  /v1/analyst/AAPL/eod/latest" GET "$BASE/v1/analyst/AAPL/eod/latest"
check "GET  /v1/analyst/AAPL/eod/recent" GET "$BASE/v1/analyst/AAPL/eod/recent?count=3"

echo "── BACKTEST ──"
check "GET  /v1/backtest/runs" GET "$BASE/v1/backtest/runs"
check "GET  /v1/backtest/runs?strategy_name=momentum" GET "$BASE/v1/backtest/runs?strategy_name=momentum"
check "GET  /v1/backtest/runs/fake-id" GET "$BASE/v1/backtest/runs/fake-id"
check "GET  /v1/backtest/runs/fake-id/trades" GET "$BASE/v1/backtest/runs/fake-id/trades"
check "GET  /v1/backtest/runs/fake-id/performance" GET "$BASE/v1/backtest/runs/fake-id/performance"

echo "── FUNDAMENTALS ──"
check "GET  /v1/fundamentals" GET "$BASE/v1/fundamentals"
check "GET  /v1/fundamentals/AAPL" GET "$BASE/v1/fundamentals/AAPL"
check "GET  /v1/fundamentals/AAPL/dividends" GET "$BASE/v1/fundamentals/AAPL/dividends"
check "GET  /v1/fundamentals/AAPL/earnings" GET "$BASE/v1/fundamentals/AAPL/earnings"
check "GET  /v1/fundamentals/AAPL/income" GET "$BASE/v1/fundamentals/AAPL/income"
check "GET  /v1/fundamentals/AAPL/balance-sheet" GET "$BASE/v1/fundamentals/AAPL/balance-sheet"
check "GET  /v1/fundamentals/AAPL/cash-flow" GET "$BASE/v1/fundamentals/AAPL/cash-flow"

echo "── MARKET ──"
check "GET  /v1/market/previous-close?symbols=AAPL" GET "$BASE/v1/market/previous-close?symbols=AAPL"
check "GET  /v1/market/previous-close?symbols=AAPL,MSFT" GET "$BASE/v1/market/previous-close?symbols=AAPL,MSFT"
check "GET  /v1/market/previous-close (missing param) ->422" GET "$BASE/v1/market/previous-close" "" 422

echo "── PORTFOLIO ──"
check "GET  /v1/portfolio/status" GET "$BASE/v1/portfolio/status"
check "GET  /v1/portfolio/health" GET "$BASE/v1/portfolio/health"
check "GET  /v1/portfolio/history" GET "$BASE/v1/portfolio/history"
check "GET  /v1/portfolio/history?start=2024-01-01" GET "$BASE/v1/portfolio/history?start=2024-01-01"
check "GET  /v1/portfolio/history/alpaca" GET "$BASE/v1/portfolio/history/alpaca"
check "GET  /v1/portfolio/history/alpaca?period=1W" GET "$BASE/v1/portfolio/history/alpaca?period=1W"

echo "── ORDERS ──"
check "GET  /v1/orders" GET "$BASE/v1/orders"
check "POST /v1/orders/reconcile" POST "$BASE/v1/orders/reconcile"
check "POST /v1/orders/execute bad ->422" POST "$BASE/v1/orders/execute" '{"x":1}' 422
check "POST /v1/orders/stop bad ->422" POST "$BASE/v1/orders/stop" '{}' 422
check "POST /v1/orders/stop-limit bad ->422" POST "$BASE/v1/orders/stop-limit" '{}' 422
check "POST /v1/orders/scale bad ->422" POST "$BASE/v1/orders/scale" '{}' 422
check "POST /v1/orders/signal bad ->422" POST "$BASE/v1/orders/signal" '{}' 422
skipfn "POST /v1/orders/execute (real order)"
skipfn "POST /v1/orders/stop (real order)"
skipfn "POST /v1/orders/stop-limit (real order)"
skipfn "POST /v1/orders/close/AAPL (closes position)"
skipfn "POST /v1/orders/scale (resizes position)"
skipfn "POST /v1/orders/signal (places order)"
skipfn "DELETE /v1/orders (cancels all)"
skipfn "DELETE /v1/orders/{id} (cancels order)"

echo "── STRATEGY ──"
check "GET  /v1/strategy/actionable" GET "$BASE/v1/strategy/actionable"
check "GET  /v1/strategy/actionable?min_confidence=0.8" GET "$BASE/v1/strategy/actionable?min_confidence=0.8"
check "GET  /v1/strategy/actionable?action=buy" GET "$BASE/v1/strategy/actionable?action=buy"
check "GET  /v1/strategy/registry/list" GET "$BASE/v1/strategy/registry/list"
check "GET  /v1/strategy/registry/list?category=intraday" GET "$BASE/v1/strategy/registry/list?category=intraday"
check "GET  /v1/strategy/registry/list?category=daily" GET "$BASE/v1/strategy/registry/list?category=daily"
check "GET  /v1/strategy/registry/mean-reversion" GET "$BASE/v1/strategy/registry/mean-reversion"
check "GET  /v1/strategy/registry/unknown ->404" GET "$BASE/v1/strategy/registry/unknown-xyz" "" 404
check "GET  /v1/strategy/mean-reversion/performance" GET "$BASE/v1/strategy/mean-reversion/performance"
check "GET  /v1/strategy/AAPL/mean-reversion/latest" GET "$BASE/v1/strategy/AAPL/mean-reversion/latest"
check "GET  /v1/strategy/AAPL/mean-reversion/signals" GET "$BASE/v1/strategy/AAPL/mean-reversion/signals"
BODY_MEAN='{"symbol":"AAPL","strategy_name":"mean-reversion","timeframe":"1Day","lookback_bars":60}'
check "POST /v1/strategy/signals/run (mean-reversion)" POST "$BASE/v1/strategy/signals/run" "$BODY_MEAN" 200
BODY_ALL='{"symbol":"AAPL","strategy_name":"all","timeframe":"1Day"}'
check "POST /v1/strategy/signals/run (all)" POST "$BASE/v1/strategy/signals/run" "$BODY_ALL" 200
BODY_BAD='{"symbol":"AAPL","strategy_name":"invalid","timeframe":"1Day"}'
check "POST /v1/strategy/signals/run bad strategy ->400" POST "$BASE/v1/strategy/signals/run" "$BODY_BAD" 400
check "POST /v1/strategy/signals/run missing symbol ->422" POST "$BASE/v1/strategy/signals/run" '{}' 422

echo "── INGESTION ──"
check "GET  /v1/ingestion/status" GET "$BASE/v1/ingestion/status"
check "POST /v1/ingestion/flush-cache" POST "$BASE/v1/ingestion/flush-cache?archive_older_than_minutes=120"
check "POST /v1/ingestion/trigger-etl" POST "$BASE/v1/ingestion/trigger-etl"

echo "── REDIS ──"
check "GET  /v1/redis/health" GET "$BASE/v1/redis/health"

echo "── SANDBOX (external Daytona service) ──"
skipfn "POST /v1/sandbox/create"
skipfn "GET  /v1/sandbox/{id}/status"
skipfn "POST /v1/sandbox/{id}/agent/stream"
skipfn "POST /v1/sandbox/{id}/publish"
skipfn "DELETE /v1/sandbox/{id}"

echo ""
echo "══════════════════════════════════════════════════════"
echo "  OK=$ok  FAIL=$fail  SKIP=$skip  TOTAL=$((ok+fail+skip))"
echo "══════════════════════════════════════════════════════"
