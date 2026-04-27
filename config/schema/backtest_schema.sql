-- ====================================================
-- Backtest Schema
-- Phase 4: Backtester Agent
-- Post-market simulation and strategy validation
-- ====================================================

-- Sequence for backtest_runs
CREATE SEQUENCE IF NOT EXISTS backtest_runs_id_seq START 1;

-- 1. Backtest Runs (Simulation Metadata & Results)
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id VARCHAR PRIMARY KEY,  -- UUID for unique identification
    strategy_name VARCHAR NOT NULL,
    symbol VARCHAR,  -- NULL for multi-symbol runs
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    -- Initial conditions
    initial_capital DECIMAL(12, 2) NOT NULL,
    final_capital DECIMAL(12, 2),

    -- Performance metrics
    total_return_pct DECIMAL(8, 4),
    sharpe_ratio DECIMAL(8, 4),
    max_drawdown_pct DECIMAL(8, 4),
    win_rate DECIMAL(5, 4),
    profit_factor DECIMAL(8, 4),

    -- Trade statistics
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    avg_win DECIMAL(10, 2),
    avg_loss DECIMAL(10, 2),

    -- Parameters used
    strategy_parameters JSON,

    -- Execution metadata
    status VARCHAR DEFAULT 'running',  -- running, completed, failed
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Indexes for backtest_runs
CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy
    ON backtest_runs(strategy_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_symbol
    ON backtest_runs(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_status
    ON backtest_runs(status, created_at DESC);

-- ====================================================

-- Sequence for backtest_trades
CREATE SEQUENCE IF NOT EXISTS backtest_trades_id_seq START 1;

-- 2. Backtest Trades (Individual Simulated Trades)
CREATE TABLE IF NOT EXISTS backtest_trades (
    trade_id INTEGER PRIMARY KEY DEFAULT nextval('backtest_trades_id_seq'),
    run_id VARCHAR NOT NULL,

    symbol VARCHAR NOT NULL,
    entry_date DATE NOT NULL,
    entry_time TIMESTAMP NOT NULL,
    entry_price DECIMAL(10, 2) NOT NULL,

    exit_date DATE,
    exit_time TIMESTAMP,
    exit_price DECIMAL(10, 2),

    quantity INTEGER NOT NULL,
    side VARCHAR NOT NULL,  -- long, short (position direction)
    action VARCHAR DEFAULT 'buy',  -- buy, sell, short, cover (the trade action taken)

    -- P&L tracking
    pnl DECIMAL(10, 2),
    pnl_pct DECIMAL(8, 4),

    -- Trade reason
    entry_signal JSON,  -- Signal that triggered entry (indicators, values)
    exit_reason VARCHAR,  -- stop_loss, take_profit, signal_reversal, eod

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Migrate existing tables: add action column if absent
ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS action VARCHAR DEFAULT 'buy';

-- Indexes for backtest_trades
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
    ON backtest_trades(run_id, entry_time);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_symbol
    ON backtest_trades(symbol, entry_time);

-- ====================================================

-- Sequence for backtest_performance
CREATE SEQUENCE IF NOT EXISTS backtest_performance_id_seq START 1;

-- 3. Backtest Performance (Daily Portfolio Snapshots)
CREATE TABLE IF NOT EXISTS backtest_performance (
    id INTEGER PRIMARY KEY DEFAULT nextval('backtest_performance_id_seq'),
    run_id VARCHAR NOT NULL,

    date DATE NOT NULL,
    equity DECIMAL(12, 2) NOT NULL,
    cash DECIMAL(12, 2) NOT NULL,
    positions_value DECIMAL(12, 2),

    daily_pnl DECIMAL(10, 2),
    daily_return_pct DECIMAL(8, 4),
    cumulative_return_pct DECIMAL(8, 4),
    drawdown_pct DECIMAL(8, 4),

    open_positions INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, date)
);

-- Indexes for backtest_performance
CREATE INDEX IF NOT EXISTS idx_backtest_performance_run
    ON backtest_performance(run_id, date);

-- ====================================================
-- Views (Optional - For Convenience)
-- ====================================================

-- Recent backtest runs (last 50)
CREATE OR REPLACE VIEW recent_backtest_runs AS
SELECT
    run_id,
    strategy_name,
    symbol,
    start_date,
    end_date,
    total_return_pct,
    sharpe_ratio,
    max_drawdown_pct,
    win_rate,
    total_trades,
    status,
    created_at,
    completed_at
FROM backtest_runs
ORDER BY created_at DESC
LIMIT 50;

-- Best performing backtest runs
CREATE OR REPLACE VIEW top_backtest_runs AS
SELECT
    run_id,
    strategy_name,
    symbol,
    total_return_pct,
    sharpe_ratio,
    max_drawdown_pct,
    win_rate,
    total_trades,
    completed_at
FROM backtest_runs
WHERE status = 'completed'
  AND sharpe_ratio IS NOT NULL
ORDER BY sharpe_ratio DESC
LIMIT 20;

-- ====================================================
-- Comments for Documentation
-- ====================================================

COMMENT ON TABLE backtest_runs IS 'Metadata and results for each backtest simulation run';
COMMENT ON TABLE backtest_trades IS 'Individual trades executed during backtest simulations';
COMMENT ON TABLE backtest_performance IS 'Daily portfolio snapshots during backtest runs for equity curve tracking';

COMMENT ON COLUMN backtest_runs.run_id IS 'UUID identifier for the backtest run';
COMMENT ON COLUMN backtest_runs.strategy_parameters IS 'JSON object containing strategy parameters used';
COMMENT ON COLUMN backtest_runs.status IS 'Status: running, completed, or failed';

COMMENT ON COLUMN backtest_trades.action IS 'Trade action: buy (long entry), sell (long exit), short (short entry), cover (short exit)';
COMMENT ON COLUMN backtest_trades.side IS 'Position side: long or short';
COMMENT ON COLUMN backtest_trades.entry_signal IS 'JSON object with indicator values that triggered trade entry';
COMMENT ON COLUMN backtest_trades.exit_reason IS 'Reason for trade exit: stop_loss, take_profit, signal_reversal, or eod';

COMMENT ON COLUMN backtest_performance.drawdown_pct IS 'Drawdown from peak equity at this point in time';
COMMENT ON COLUMN backtest_performance.cumulative_return_pct IS 'Cumulative return from start of backtest to this date';
