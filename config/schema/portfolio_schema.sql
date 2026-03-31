-- ====================================================
-- Portfolio Management Schema
-- Phase 3: Portfolio Manager Agent
-- ====================================================

-- Sequence for portfolio_snapshots
CREATE SEQUENCE IF NOT EXISTS portfolio_snapshots_id_seq START 1;

-- 1. Portfolio Snapshots (EOD State Tracking)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id INTEGER PRIMARY KEY DEFAULT nextval('portfolio_snapshots_id_seq'),
    timestamp TIMESTAMP NOT NULL,
    date_only DATE NOT NULL,

    -- Account values
    equity DECIMAL(12, 2) NOT NULL,
    cash DECIMAL(12, 2) NOT NULL,
    buying_power DECIMAL(12, 2) NOT NULL,

    -- P&L metrics
    daily_pnl DECIMAL(12, 2),
    total_pnl DECIMAL(12, 2),
    daily_pnl_percent DECIMAL(6, 4),

    -- Position counts
    long_positions INTEGER DEFAULT 0,
    short_positions INTEGER DEFAULT 0,

    -- Metadata
    snapshot_source VARCHAR DEFAULT 'alpaca',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(date_only)
);

-- Indexes for portfolio_snapshots
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_date
    ON portfolio_snapshots(date_only DESC);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_timestamp
    ON portfolio_snapshots(timestamp DESC);

-- ====================================================

-- Sequence for agent_interactions
CREATE SEQUENCE IF NOT EXISTS agent_interactions_id_seq START 1;

-- 2. Agent Interactions (Observability/Audit Log)
CREATE TABLE IF NOT EXISTS agent_interactions (
    interaction_id INTEGER PRIMARY KEY DEFAULT nextval('agent_interactions_id_seq'),
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    thread_id VARCHAR NOT NULL,

    -- Query details
    agent_name VARCHAR NOT NULL,
    user_query TEXT NOT NULL,

    -- Tool execution trace
    tool_sequence JSON,

    -- Response
    agent_response TEXT NOT NULL,

    -- Metadata
    model_used VARCHAR,
    token_count INTEGER,
    execution_time_ms INTEGER,

    -- Performance tracking (Improvement #2)
    tool_timings JSON,

    -- Agent handoffs
    delegated_to VARCHAR,
    delegation_result TEXT,

    -- Thread cleanup (Improvement #10)
    expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '30 days'),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for agent_interactions
CREATE INDEX IF NOT EXISTS idx_interactions_thread
    ON agent_interactions(thread_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_agent
    ON agent_interactions(agent_name, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_recent
    ON agent_interactions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_expires
    ON agent_interactions(expires_at);

-- ====================================================

-- 3. Portfolio Parameters (Risk Limits and Configuration)
CREATE TABLE IF NOT EXISTS portfolio_parameters (
    parameter_key VARCHAR PRIMARY KEY,
    parameter_value JSON NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for portfolio_parameters
CREATE INDEX IF NOT EXISTS idx_parameters_key
    ON portfolio_parameters(parameter_key);

-- ====================================================
-- Seed Default Risk Parameters
-- ====================================================

INSERT INTO portfolio_parameters (parameter_key, parameter_value, description)
VALUES
    ('max_position_size', '{"value": 1000, "unit": "shares"}', 'Maximum shares per position'),
    ('max_daily_trades', '{"value": 10}', 'Maximum trades allowed per day'),
    ('position_limit_percent', '{"value": 0.1}', 'Max % of portfolio in single position'),
    ('stop_loss_percent', '{"value": 0.02}', 'Default stop loss (2% of entry)'),
    ('daily_loss_limit', '{"value": 0.05}', 'Max daily portfolio loss (5%)'),
    ('risk_free_rate', '{"value": 0.045}', 'Annual risk-free rate for Sharpe calculation')
ON CONFLICT (parameter_key) DO NOTHING;

-- ====================================================
-- Views (Optional - For Convenience)
-- ====================================================

-- Latest portfolio snapshot
CREATE OR REPLACE VIEW latest_portfolio_snapshot AS
SELECT * FROM portfolio_snapshots
ORDER BY timestamp DESC
LIMIT 1;

-- Recent agent interactions (last 100)
CREATE OR REPLACE VIEW recent_agent_interactions AS
SELECT
    interaction_id,
    timestamp,
    thread_id,
    agent_name,
    SUBSTRING(user_query, 1, 100) as query_preview,
    SUBSTRING(agent_response, 1, 100) as response_preview,
    execution_time_ms,
    delegated_to
FROM agent_interactions
ORDER BY timestamp DESC
LIMIT 100;

-- Performance summary by agent
CREATE OR REPLACE VIEW agent_performance_summary AS
SELECT
    agent_name,
    COUNT(*) as total_interactions,
    AVG(execution_time_ms) as avg_execution_time_ms,
    MAX(execution_time_ms) as max_execution_time_ms,
    AVG(token_count) as avg_tokens,
    COUNT(CASE WHEN delegated_to IS NOT NULL THEN 1 END) as delegation_count
FROM agent_interactions
WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
GROUP BY agent_name;
