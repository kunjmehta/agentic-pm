-- ============================================================================
-- Reports Schema for DuckDB (analysis.duckdb)
-- ============================================================================
-- Three derived tables that support the reporting endpoints:
--   1. signal_performance_tracking  — per-signal was_taken + PnL tracking
--   2. hypothetical_portfolios      — daily actual vs hypothetical comparison
--   3. strategy_performance_summary — weekly/monthly aggregated stats
-- ============================================================================

-- 1. Signal Performance Tracking
-- Inserted when a signal is approved (was_taken=true) or rejected/expired
-- (was_taken=false).  The reconciliation job closes open rows with realized PnL.
CREATE TABLE IF NOT EXISTS signal_performance_tracking (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id INTEGER NOT NULL,           -- FK to strategy_results.id
    symbol VARCHAR NOT NULL,
    strategy_name VARCHAR NOT NULL,
    signal_action VARCHAR NOT NULL,       -- 'buy' | 'sell' | 'hold'
    signal_confidence DECIMAL(5, 4),
    signal_timestamp TIMESTAMP NOT NULL,
    was_taken BOOLEAN NOT NULL DEFAULT FALSE,
    entry_price DECIMAL(10, 4),           -- NULL if not taken
    exit_price DECIMAL(10, 4),            -- NULL if not yet exited
    realized_pnl DECIMAL(15, 4),          -- NULL if not taken or not closed
    hypothetical_pnl DECIMAL(15, 4),      -- what would have happened (was_taken=false rows)
    tracking_status VARCHAR DEFAULT 'open',  -- 'open' | 'closed' | 'expired' | 'missed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    evaluated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_spt_signal_id
    ON signal_performance_tracking(signal_id);
CREATE INDEX IF NOT EXISTS idx_spt_symbol_strategy
    ON signal_performance_tracking(symbol, strategy_name, signal_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_spt_status
    ON signal_performance_tracking(tracking_status);

-- ============================================================================

-- 2. Hypothetical Portfolios
-- Daily snapshot comparing what actually happened vs all-signals-taken scenario.
-- Populated by the daily cron job at market close.
CREATE TABLE IF NOT EXISTS hypothetical_portfolios (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_date DATE NOT NULL,
    strategy_name VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    hypothetical_value DECIMAL(15, 4),
    actual_value DECIMAL(15, 4),
    signals_taken INTEGER DEFAULT 0,
    signals_missed INTEGER DEFAULT 0,
    opportunity_pnl DECIMAL(15, 4),      -- PnL left on the table (missed - taken)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, strategy_name, symbol)
);

CREATE INDEX IF NOT EXISTS idx_hypo_date_strategy
    ON hypothetical_portfolios(snapshot_date DESC, strategy_name);

-- ============================================================================

-- 3. Strategy Performance Summary
-- Aggregated stats per strategy+symbol+period, refreshed weekly.
CREATE TABLE IF NOT EXISTS strategy_performance_summary (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_name VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    total_signals INTEGER DEFAULT 0,
    signals_taken INTEGER DEFAULT 0,
    win_rate DECIMAL(5, 4),
    avg_return_per_trade DECIMAL(8, 4),
    total_pnl DECIMAL(15, 4),
    sharpe_ratio DECIMAL(8, 4),
    max_drawdown_pct DECIMAL(8, 4),
    best_trade_pnl DECIMAL(15, 4),
    worst_trade_pnl DECIMAL(15, 4),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (strategy_name, symbol, period_start)
);

CREATE INDEX IF NOT EXISTS idx_sps_strategy_symbol
    ON strategy_performance_summary(strategy_name, symbol, period_start DESC);
