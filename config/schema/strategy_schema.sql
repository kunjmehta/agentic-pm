-- Trading Strategy Results Table
-- Stores results from strategy executions (mean-reversion, etc.)
-- Captures signals, recommendations, and agent reasoning

CREATE SEQUENCE IF NOT EXISTS strategy_results_id_seq START 1;

CREATE TABLE IF NOT EXISTS strategy_results (
    id INTEGER PRIMARY KEY DEFAULT nextval('strategy_results_id_seq'),
    symbol VARCHAR NOT NULL,
    strategy_name VARCHAR NOT NULL,  -- e.g., 'mean-reversion', 'momentum-breakout'
    timestamp TIMESTAMP NOT NULL,

    -- Market data snapshot
    current_price DECIMAL(10, 2) NOT NULL,
    timeframe VARCHAR,  -- e.g., '1Day', '1Hour', '1Min'

    -- Statistical measures (JSON for flexibility)
    statistics JSON,  -- {mean, std_dev, z_score, percentile, etc.}
    indicators JSON,  -- {sma_20, sma_50, ema_20, bollinger_bands, etc.}

    -- Signals and state
    current_state VARCHAR,  -- e.g., 'oversold', 'overbought', 'neutral'
    signals JSON,  -- {z_score_signal, ma_cross_signal, bollinger_signal, overall_signal}

    -- Trading recommendation
    action VARCHAR NOT NULL,  -- 'buy', 'sell', 'hold'
    confidence DECIMAL(3, 2),  -- 0.0 to 1.0
    reason TEXT,  -- Human-readable explanation
    entry_price DECIMAL(10, 2),
    stop_loss DECIMAL(10, 2),
    take_profit DECIMAL(10, 2),

    -- Support/Resistance levels
    support_level DECIMAL(10, 2),
    resistance_level DECIMAL(10, 2),

    -- Agent metadata
    thought_trace TEXT,  -- Agent's reasoning process
    model_used VARCHAR,  -- LLM model identifier
    parameters JSON,  -- Strategy parameters used (lookback, threshold, etc.)

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookups by symbol and strategy
CREATE INDEX IF NOT EXISTS idx_strategy_symbol_name
    ON strategy_results(symbol, strategy_name, timestamp DESC);

-- Index for recent signals
CREATE INDEX IF NOT EXISTS idx_strategy_recent
    ON strategy_results(created_at DESC);

-- Index for actionable signals (buy/sell with high confidence)
-- Note: DuckDB doesn't support partial indexes, so no WHERE clause
CREATE INDEX IF NOT EXISTS idx_strategy_actionable
    ON strategy_results(action, confidence DESC);

-- Index for strategy performance analysis
CREATE INDEX IF NOT EXISTS idx_strategy_performance
    ON strategy_results(strategy_name, timestamp DESC);
