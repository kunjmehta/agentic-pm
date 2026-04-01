-- ============================================================================
-- Alpaca Market Data Schema for DuckDB
-- ============================================================================
-- This schema defines tables for storing market data from Alpaca API
-- All tables use snake_case column names for consistency
-- Optimized for time-series queries with composite primary keys
-- ============================================================================

-- 1. Watchlist
-- Tracks symbols being monitored
CREATE TABLE IF NOT EXISTS watchlist (
    symbol VARCHAR PRIMARY KEY,
    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active BOOLEAN DEFAULT TRUE,
    notes TEXT
);

-- Index for active symbols
CREATE INDEX IF NOT EXISTS idx_watchlist_active ON watchlist(active, added_date DESC);

-- ============================================================================

-- 2. Market Bars (OHLCV Data)
-- Stores historical bar data at various timeframes
CREATE TABLE IF NOT EXISTS market_bars (
    symbol VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    timeframe VARCHAR NOT NULL,     -- '1Min', '5Min', '15Min', '1Hour', '1Day'
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT,
    trade_count INTEGER,
    vwap DOUBLE,                    -- Volume-Weighted Average Price
    PRIMARY KEY (symbol, timestamp, timeframe)
);

-- Indexes for time-series queries
CREATE INDEX IF NOT EXISTS idx_market_bars_symbol_time
    ON market_bars(symbol, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_market_bars_timeframe_time
    ON market_bars(timeframe, timestamp DESC);

-- ============================================================================

-- 3. Live Trades (Staging Table)
-- Stores real-time trade data from WebSocket stream before archival
CREATE TABLE IF NOT EXISTS live_trades (
    symbol VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    trade_id BIGINT NOT NULL,
    price DOUBLE,
    size INTEGER,
    exchange VARCHAR(1),            -- Exchange code (P=Arca, Q=NASDAQ, V=IEX, etc.)
    conditions VARCHAR,             -- Trade conditions (@=regular, T=extended, etc.)
    tape VARCHAR(1),                -- SIP tape (A, B, or C)
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp, trade_id)
);

-- Index for archival queries (by ingestion time)
CREATE INDEX IF NOT EXISTS idx_live_trades_ingested
    ON live_trades(symbol, ingested_at DESC);

-- ============================================================================

-- 4. Historical Trades (Archival Table)
-- Stores tick-level trade data (both API-fetched and archived from live_trades)
CREATE TABLE IF NOT EXISTS historical_trades (
    symbol VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    trade_id BIGINT NOT NULL,
    price DOUBLE,
    size INTEGER,
    exchange VARCHAR(1),            -- Exchange code (P=Arca, Q=NASDAQ, V=IEX, etc.)
    conditions VARCHAR,             -- Trade conditions (@=regular, T=extended, etc.)
    tape VARCHAR(1),                -- SIP tape (A, B, or C)
    source VARCHAR(10) DEFAULT 'api',  -- 'api' (historical fetch) or 'stream' (WebSocket)
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp, trade_id)
);

-- Indexes for time-series queries
CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
    ON historical_trades(symbol, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_trades_size
    ON historical_trades(symbol, size DESC, timestamp DESC);

-- ============================================================================

-- 5. Computed Indicators
-- Stores pre-computed technical indicators from ETL pipeline
CREATE TABLE IF NOT EXISTS computed_indicators (
    symbol VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    timeframe VARCHAR NOT NULL,     -- '1Min', '1Hour', '1Day'

    -- Momentum indicators
    macd_value DOUBLE,
    macd_signal DOUBLE,
    macd_histogram DOUBLE,
    rsi DOUBLE,

    -- Volatility indicators
    bb_upper DOUBLE,               -- Bollinger Band upper
    bb_middle DOUBLE,              -- Bollinger Band middle (SMA)
    bb_lower DOUBLE,               -- Bollinger Band lower
    bb_bandwidth DOUBLE,           -- Bandwidth percentage

    -- Volume indicators
    obv BIGINT,                    -- On-Balance Volume
    volume_trend VARCHAR(20),      -- 'increasing' or 'decreasing'
    avg_volume_10d BIGINT,         -- 10-period average volume
    current_vs_avg DOUBLE,         -- Current volume / avg ratio

    -- Mean reversion indicators
    z_score DOUBLE,                -- Z-score for mean reversion
    percentile DOUBLE,             -- Percentile ranking
    vwap DOUBLE,                   -- Volume-Weighted Average Price

    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp, timeframe)
);

-- Indexes for time-series queries
CREATE INDEX IF NOT EXISTS idx_computed_indicators_time
    ON computed_indicators(symbol, timeframe, timestamp DESC);


-- ============================================================================

-- 6. Live Orders
-- Tracks broker orders submitted through the HITL approval flow or direct API.
-- Reconciliation job updates filled_at and filled_price by polling Alpaca.
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

-- ============================================================================
-- Views for Common Queries
-- ============================================================================

-- Latest bars for each symbol (1-day timeframe)
CREATE OR REPLACE VIEW latest_daily_bars AS
SELECT DISTINCT ON (symbol)
    symbol,
    timestamp,
    open,
    high,
    low,
    close,
    volume,
    vwap
FROM market_bars
WHERE timeframe = '1Day'
ORDER BY symbol, timestamp DESC;

-- Latest intraday bars (1-minute timeframe, last 24 hours)
CREATE OR REPLACE VIEW latest_intraday_bars AS
SELECT
    symbol,
    timestamp,
    open,
    high,
    low,
    close,
    volume,
    vwap
FROM market_bars
WHERE timeframe = '1Min'
  AND timestamp >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
ORDER BY symbol, timestamp DESC;

-- Active watchlist with latest price
CREATE OR REPLACE VIEW watchlist_with_price AS
SELECT
    w.symbol,
    w.added_date,
    w.notes,
    b.close as last_price,
    b.timestamp as price_time,
    b.volume as last_volume
FROM watchlist w
LEFT JOIN latest_daily_bars b ON w.symbol = b.symbol
WHERE w.active = TRUE
ORDER BY w.added_date DESC;

-- Large trades (size >= 10,000 shares)
CREATE OR REPLACE VIEW large_trades AS
SELECT
    symbol,
    timestamp,
    price,
    size,
    exchange,
    conditions,
    size * price as trade_value
FROM historical_trades
WHERE size >= 10000
ORDER BY timestamp DESC, size DESC;

-- Recent trades (combines live + recent historical)
CREATE OR REPLACE VIEW recent_trades AS
SELECT
    symbol,
    timestamp,
    trade_id,
    price,
    size,
    exchange,
    conditions,
    tape,
    'live' as source,
    ingested_at as created_at
FROM live_trades
UNION ALL
SELECT
    symbol,
    timestamp,
    trade_id,
    price,
    size,
    exchange,
    conditions,
    tape,
    source,
    archived_at as created_at
FROM historical_trades
WHERE timestamp >= CURRENT_TIMESTAMP - INTERVAL '1 day'
ORDER BY timestamp DESC;

-- ============================================================================
-- Notes
-- ============================================================================
-- 1. Composite primary keys (symbol, timestamp, timeframe) allow multiple
--    timeframes for same timestamp
-- 2. Indexes on (symbol, timestamp DESC) optimize range queries
-- 3. VWAP stored at bar level for accuracy
-- 4. Trade conditions stored as strings for flexibility
-- 5. All timestamps are timezone-aware (stored in UTC)
-- ============================================================================
