-- ============================================================================
-- Orders Schema for DuckDB (portfolio.duckdb)
-- ============================================================================
-- Tracks broker orders submitted through the HITL approval flow or direct API.
-- Reconciliation job updates filled_at and filled_price by polling Alpaca.
-- ============================================================================

CREATE TABLE IF NOT EXISTS live_orders (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id INTEGER,                    -- FK to strategy_results.id (NULL for manual orders)
    symbol VARCHAR NOT NULL,
    side VARCHAR NOT NULL,                -- 'buy' | 'sell'
    qty INTEGER NOT NULL,
    order_type VARCHAR DEFAULT 'market',  -- 'market' | 'limit'
    limit_price DECIMAL(10, 4),
    broker_order_id VARCHAR,              -- Alpaca order UUID
    status VARCHAR DEFAULT 'submitted',   -- 'submitted' | 'filled' | 'cancelled' | 'rejected'
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    filled_at TIMESTAMP,
    filled_price DECIMAL(10, 4),
    realized_pnl DECIMAL(15, 4)
);

CREATE INDEX IF NOT EXISTS idx_live_orders_status
    ON live_orders(status, submitted_at DESC);

CREATE INDEX IF NOT EXISTS idx_live_orders_signal
    ON live_orders(signal_id);
