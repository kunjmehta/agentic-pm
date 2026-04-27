-- ============================================================================
-- Analysis Schema for DuckDB (analysis.duckdb)
-- ============================================================================
-- Stores all ETL-computed outputs:
--   1. analyst_summaries       — LLM-generated EOD summaries per symbol
--   2. strategy_results        — per-strategy signal results with indicators
-- ============================================================================

-- 1. Analyst EOD Summaries
-- Only end-of-day comprehensive summaries are persisted; intraday summaries
-- live on disk under data/summaries/.
CREATE TABLE IF NOT EXISTS analyst_summaries (
    symbol VARCHAR NOT NULL,
    date_only DATE NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    indicators JSON,
    summary_text TEXT NOT NULL,
    signals JSON,
    thought_trace TEXT,
    model_used VARCHAR,
    token_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, date_only)
);

CREATE INDEX IF NOT EXISTS idx_analyst_eod_symbol_date
    ON analyst_summaries(symbol, DATE(timestamp) DESC);

CREATE INDEX IF NOT EXISTS idx_analyst_eod_recent
    ON analyst_summaries(created_at DESC);

-- ============================================================================

-- 2. Strategy Results
-- Captures per-strategy signals, recommendations, and agent reasoning.
CREATE SEQUENCE IF NOT EXISTS strategy_results_id_seq START 1;

CREATE TABLE IF NOT EXISTS strategy_results (
    id INTEGER PRIMARY KEY DEFAULT nextval('strategy_results_id_seq'),
    symbol VARCHAR NOT NULL,
    strategy_name VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,

    current_price DECIMAL(10, 2) NOT NULL,
    timeframe VARCHAR,

    statistics JSON,
    indicators JSON,

    current_state VARCHAR,
    signals JSON,

    action VARCHAR NOT NULL,
    confidence DECIMAL(3, 2),
    reason TEXT,
    entry_price DECIMAL(10, 2),
    stop_loss DECIMAL(10, 2),
    take_profit DECIMAL(10, 2),

    support_level DECIMAL(10, 2),
    resistance_level DECIMAL(10, 2),

    thought_trace TEXT,
    model_used VARCHAR,
    parameters JSON,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_strategy_symbol_name
    ON strategy_results(symbol, strategy_name, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_recent
    ON strategy_results(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_actionable
    ON strategy_results(action, confidence DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_performance
    ON strategy_results(strategy_name, timestamp DESC);
