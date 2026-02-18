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

-- 3. Historical Trades
-- Stores tick-level trade data
CREATE TABLE IF NOT EXISTS historical_trades (
    symbol VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    trade_id BIGINT NOT NULL,
    price DOUBLE,
    size INTEGER,
    exchange VARCHAR(1),            -- Exchange code (P=Arca, Q=NASDAQ, V=IEX, etc.)
    conditions VARCHAR,             -- Trade conditions (@=regular, T=extended, etc.)
    tape VARCHAR(1),                -- SIP tape (A, B, or C)
    PRIMARY KEY (symbol, timestamp, trade_id)
);

-- Indexes for time-series queries
CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
    ON historical_trades(symbol, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_trades_size
    ON historical_trades(symbol, size DESC, timestamp DESC);

-- ============================================================================
-- Aggregate Tables for Performance
-- ============================================================================

-- Daily aggregated bars (pre-computed for performance)
CREATE TABLE IF NOT EXISTS daily_bars_agg (
    symbol VARCHAR NOT NULL,
    date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT,
    trade_count INTEGER,
    vwap DOUBLE,
    intraday_high_time TIMESTAMP,   -- Time of intraday high
    intraday_low_time TIMESTAMP,    -- Time of intraday low
    PRIMARY KEY (symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_bars_agg_date
    ON daily_bars_agg(date DESC);

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

-- Intraday summary (today's trading)
CREATE OR REPLACE VIEW intraday_summary AS
SELECT
    symbol,
    DATE(timestamp) as date,
    MIN(timestamp) as market_open_time,
    MAX(timestamp) as market_close_time,
    COUNT(*) as bar_count,
    SUM(volume) as total_volume,
    SUM(trade_count) as total_trades,
    AVG(vwap) as avg_vwap,
    FIRST_VALUE(open) OVER (PARTITION BY symbol, DATE(timestamp) ORDER BY timestamp ASC) as day_open,
    LAST_VALUE(close) OVER (PARTITION BY symbol, DATE(timestamp) ORDER BY timestamp ASC
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as day_close,
    MAX(high) as day_high,
    MIN(low) as day_low
FROM market_bars
WHERE timeframe = '1Min'
  AND DATE(timestamp) = CURRENT_DATE
GROUP BY symbol, DATE(timestamp);

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

-- Trade volume by exchange
CREATE OR REPLACE VIEW trade_volume_by_exchange AS
SELECT
    symbol,
    exchange,
    COUNT(*) as trade_count,
    SUM(size) as total_shares,
    SUM(size * price) as total_value,
    AVG(price) as avg_price,
    DATE(timestamp) as date
FROM historical_trades
WHERE DATE(timestamp) = CURRENT_DATE
GROUP BY symbol, exchange, DATE(timestamp)
ORDER BY symbol, total_shares DESC;

-- ============================================================================
-- Materialized View for Performance (Optional)
-- ============================================================================

-- Pre-compute daily statistics for fast dashboard queries
-- Note: Requires manual refresh or scheduled job
CREATE OR REPLACE VIEW daily_stats AS
SELECT
    b.symbol,
    b.date,
    b.open,
    b.high,
    b.low,
    b.close,
    b.volume,
    b.vwap,
    (b.close - LAG(b.close, 1) OVER (PARTITION BY b.symbol ORDER BY b.date)) as price_change,
    ((b.close - LAG(b.close, 1) OVER (PARTITION BY b.symbol ORDER BY b.date))
        / NULLIF(LAG(b.close, 1) OVER (PARTITION BY b.symbol ORDER BY b.date), 0) * 100) as price_change_pct,
    (b.high - b.low) as daily_range,
    ((b.high - b.low) / NULLIF(b.close, 0) * 100) as range_pct
FROM daily_bars_agg b
ORDER BY b.symbol, b.date DESC;

-- ============================================================================
-- Functions for Common Calculations
-- ============================================================================

-- Calculate intraday VWAP for a symbol
CREATE OR REPLACE VIEW vwap_intraday AS
SELECT
    symbol,
    timestamp,
    SUM(vwap * volume) OVER (
        PARTITION BY symbol, DATE(timestamp)
        ORDER BY timestamp
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) / SUM(volume) OVER (
        PARTITION BY symbol, DATE(timestamp)
        ORDER BY timestamp
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) as cumulative_vwap,
    volume,
    vwap as bar_vwap
FROM market_bars
WHERE timeframe = '1Min'
  AND DATE(timestamp) = CURRENT_DATE;

-- ============================================================================
-- Triggers for Aggregate Table Updates (if needed)
-- ============================================================================
-- Note: DuckDB doesn't support triggers, so aggregates must be updated manually
-- or via scheduled jobs. Example update query:
--
-- INSERT INTO daily_bars_agg
-- SELECT
--     symbol,
--     DATE(timestamp) as date,
--     FIRST_VALUE(open) OVER w as open,
--     MAX(high) OVER w as high,
--     MIN(low) OVER w as low,
--     LAST_VALUE(close) OVER w as close,
--     SUM(volume) OVER w as volume,
--     SUM(trade_count) OVER w as trade_count,
--     SUM(vwap * volume) OVER w / SUM(volume) OVER w as vwap,
--     FIRST_VALUE(timestamp) FILTER (WHERE high = MAX(high) OVER w) OVER w as intraday_high_time,
--     FIRST_VALUE(timestamp) FILTER (WHERE low = MIN(low) OVER w) OVER w as intraday_low_time
-- FROM market_bars
-- WHERE timeframe = '1Min'
--   AND DATE(timestamp) = CURRENT_DATE
-- WINDOW w AS (PARTITION BY symbol, DATE(timestamp))
-- ON CONFLICT (symbol, date) DO UPDATE SET
--     open = excluded.open,
--     high = excluded.high,
--     low = excluded.low,
--     close = excluded.close,
--     volume = excluded.volume,
--     trade_count = excluded.trade_count,
--     vwap = excluded.vwap,
--     intraday_high_time = excluded.intraday_high_time,
--     intraday_low_time = excluded.intraday_low_time;
-- ============================================================================

-- ============================================================================
-- Notes
-- ============================================================================
-- 1. Composite primary keys (symbol, timestamp, timeframe) allow multiple
--    timeframes for same timestamp
-- 2. Indexes on (symbol, timestamp DESC) optimize range queries
-- 3. VWAP stored at bar level for accuracy
-- 4. Trade conditions stored as strings for flexibility
-- 5. Aggregate tables reduce query time for dashboards
-- 6. Views provide convenient access to common patterns
-- 7. All timestamps are timezone-aware (stored in UTC)
-- ============================================================================
