-- ============================================================================
-- Alpha Vantage Data Schema for DuckDB
-- ============================================================================
-- This schema defines tables for storing fundamental data from Alpha Vantage API
-- All tables use snake_case column names for consistency
-- JSON columns preserve complete API responses for flexibility
-- ============================================================================

-- 1. Company Fundamentals (OVERVIEW)
-- Stores company overview and fundamental metrics
CREATE TABLE IF NOT EXISTS fundamentals (
    symbol VARCHAR PRIMARY KEY,
    name VARCHAR,
    description TEXT,
    sector VARCHAR,
    industry VARCHAR,
    market_cap BIGINT,              -- MarketCapitalization
    pe_ratio DOUBLE,                -- PERatio
    dividend_yield DOUBLE,          -- DividendYield
    profit_margin DOUBLE,           -- ProfitMargin
    eps DOUBLE,                     -- Earnings Per Share
    beta DOUBLE,                    -- Volatility measure
    full_data JSON,                 -- Complete API response
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for sector/industry queries
CREATE INDEX IF NOT EXISTS idx_fundamentals_sector ON fundamentals(sector);
CREATE INDEX IF NOT EXISTS idx_fundamentals_industry ON fundamentals(industry);

-- ============================================================================

-- 2. Dividend History (DIVIDENDS)
-- Stores historical dividend payment data
CREATE TABLE IF NOT EXISTS dividend_history (
    symbol VARCHAR NOT NULL,
    ex_dividend_date DATE NOT NULL,
    declaration_date DATE,
    record_date DATE,
    payment_date DATE,
    amount DOUBLE,
    PRIMARY KEY (symbol, ex_dividend_date)
);

-- Index for date range queries
CREATE INDEX IF NOT EXISTS idx_dividend_history_symbol_date
    ON dividend_history(symbol, ex_dividend_date DESC);

-- ============================================================================

-- 3. Earnings History (EARNINGS)
-- Stores quarterly and annual earnings data
CREATE TABLE IF NOT EXISTS earnings_history (
    symbol VARCHAR NOT NULL,
    fiscal_date_ending DATE NOT NULL,
    reported_date DATE,                 -- Quarterly only
    reported_eps DOUBLE,
    estimated_eps DOUBLE,               -- Quarterly only
    surprise DOUBLE,                    -- Quarterly only
    surprise_percentage DOUBLE,         -- Quarterly only
    is_quarterly BOOLEAN DEFAULT TRUE,  -- Distinguishes quarterly vs annual
    PRIMARY KEY (symbol, fiscal_date_ending, is_quarterly)
);

-- Index for date range queries
CREATE INDEX IF NOT EXISTS idx_earnings_history_symbol_date
    ON earnings_history(symbol, fiscal_date_ending DESC);

-- ============================================================================

-- 4. Income Statements (INCOME_STATEMENT)
-- Stores income statement (P&L) data
CREATE TABLE IF NOT EXISTS income_statements (
    symbol VARCHAR NOT NULL,
    fiscal_date_ending DATE NOT NULL,
    total_revenue BIGINT,
    gross_profit BIGINT,
    operating_income BIGINT,
    net_income BIGINT,
    eps DOUBLE,
    full_data JSON,                     -- Complete API response
    is_quarterly BOOLEAN DEFAULT FALSE, -- Distinguishes quarterly vs annual
    PRIMARY KEY (symbol, fiscal_date_ending, is_quarterly)
);

-- Index for date range queries
CREATE INDEX IF NOT EXISTS idx_income_statements_symbol_date
    ON income_statements(symbol, fiscal_date_ending DESC);

-- ============================================================================

-- 5. Balance Sheets (BALANCE_SHEET)
-- Stores balance sheet data
CREATE TABLE IF NOT EXISTS balance_sheets (
    symbol VARCHAR NOT NULL,
    fiscal_date_ending DATE NOT NULL,
    total_assets BIGINT,
    total_liabilities BIGINT,
    total_shareholder_equity BIGINT,
    full_data JSON,                     -- Complete API response
    is_quarterly BOOLEAN DEFAULT FALSE, -- Distinguishes quarterly vs annual
    PRIMARY KEY (symbol, fiscal_date_ending, is_quarterly)
);

-- Index for date range queries
CREATE INDEX IF NOT EXISTS idx_balance_sheets_symbol_date
    ON balance_sheets(symbol, fiscal_date_ending DESC);

-- ============================================================================

-- 6. Cash Flow Statements (CASH_FLOW)
-- Stores cash flow statement data
CREATE TABLE IF NOT EXISTS cash_flows (
    symbol VARCHAR NOT NULL,
    fiscal_date_ending DATE NOT NULL,
    operating_cashflow BIGINT,
    capital_expenditures BIGINT,
    free_cashflow BIGINT,
    full_data JSON,                     -- Complete API response
    is_quarterly BOOLEAN DEFAULT FALSE, -- Distinguishes quarterly vs annual
    PRIMARY KEY (symbol, fiscal_date_ending, is_quarterly)
);

-- Index for date range queries
CREATE INDEX IF NOT EXISTS idx_cash_flows_symbol_date
    ON cash_flows(symbol, fiscal_date_ending DESC);

-- Latest fundamentals per symbol (most recent row per ticker)
CREATE OR REPLACE VIEW latest_fundamentals AS
SELECT * FROM fundamentals;

-- Financial health snapshot (latest annual data)
CREATE OR REPLACE VIEW financial_health_snapshot AS
SELECT
    i.symbol,
    f.name,
    f.sector,
    i.fiscal_date_ending,
    i.total_revenue,
    i.net_income,
    i.eps as income_eps,
    b.total_assets,
    b.total_liabilities,
    b.total_shareholder_equity,
    c.operating_cashflow,
    c.free_cashflow,
    ROUND(i.net_income::DOUBLE / NULLIF(i.total_revenue, 0) * 100, 2) as profit_margin_pct,
    ROUND(b.total_liabilities::DOUBLE / NULLIF(b.total_assets, 0) * 100, 2) as debt_ratio_pct
FROM income_statements i
JOIN fundamentals f ON i.symbol = f.symbol
LEFT JOIN balance_sheets b ON i.symbol = b.symbol
    AND i.fiscal_date_ending = b.fiscal_date_ending
    AND i.is_quarterly = b.is_quarterly
LEFT JOIN cash_flows c ON i.symbol = c.symbol
    AND i.fiscal_date_ending = c.fiscal_date_ending
    AND i.is_quarterly = c.is_quarterly
WHERE i.is_quarterly = FALSE
ORDER BY i.symbol, i.fiscal_date_ending DESC;

-- ============================================================================
-- Notes
-- ============================================================================
-- 1. All financial amounts stored as BIGINT for precision
-- 2. Ratios and percentages stored as DOUBLE
-- 3. JSON columns preserve complete API response for future schema changes
-- 4. is_quarterly flag distinguishes quarterly vs annual financial statements
-- 5. Indexes on (symbol, date DESC) optimize time-series queries
-- 6. Views provide convenient access to common query patterns
-- ============================================================================
