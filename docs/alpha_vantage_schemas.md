# Alpha Vantage API Schemas

This document tracks the Alpha Vantage API response schemas and their mapping to database schemas for the Data Layer (DAO) implementation.

## Overview

All Alpha Vantage functions now return DataFrames with:
- **Snake_case column names** for SQL compatibility
- **Symbol column** added to all DataFrames for easy database insertion
- **Full_data column** (JSON) to preserve complete API response
- **Type conversions** (strings → datetime, numeric) for SQL insertion

---

## 1. Company Overview (OVERVIEW)

### API Endpoint
```
GET https://www.alphavantage.co/query?function=OVERVIEW&symbol=AAPL
```

### API Response Schema
```json
{
  "Symbol": "AAPL",
  "Name": "Apple Inc",
  "Description": "...",
  "Sector": "Technology",
  "Industry": "Consumer Electronics",
  "MarketCapitalization": "3000000000000",
  "PERatio": "28.5",
  "DividendYield": "0.005",
  "ProfitMargin": "0.25",
  "EPS": "6.13",
  "Beta": "1.2",
  ...
}
```

### Function Return Type
- **Type**: `Dict[str, str]`
- **Function**: `fetch_company_overview(symbol: str)`
- Returns raw dictionary with all fields (no DataFrame conversion)

### Database Schema Mapping
```sql
CREATE TABLE fundamentals (
    symbol VARCHAR PRIMARY KEY,
    name VARCHAR,
    description TEXT,
    sector VARCHAR,
    industry VARCHAR,
    market_cap BIGINT,              -- MarketCapitalization
    pe_ratio DOUBLE,                -- PERatio
    dividend_yield DOUBLE,          -- DividendYield
    profit_margin DOUBLE,           -- ProfitMargin
    eps DOUBLE,                     -- EPS
    beta DOUBLE,                    -- Beta
    full_data JSON,                 -- Complete API response
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 2. Dividend History (DIVIDENDS)

### API Endpoint
```
GET https://www.alphavantage.co/query?function=DIVIDENDS&symbol=AAPL
```

### API Response Schema
```json
{
  "symbol": "AAPL",
  "data": [
    {
      "ex_dividend_date": "2024-02-09",
      "declaration_date": "2024-02-01",
      "record_date": "2024-02-08",
      "payment_date": "2024-02-16",
      "amount": "0.24"
    }
  ]
}
```

### Function Return Schema
- **Type**: `pd.DataFrame`
- **Function**: `fetch_dividend_history(symbol: str)`

**DataFrame Columns:**
```python
{
    "symbol": str,                  # Added
    "ex_dividend_date": datetime,   # Converted from string
    "declaration_date": datetime,   # Converted from string
    "record_date": datetime,        # Converted from string
    "payment_date": datetime,       # Converted from string
    "amount": float                 # Converted from string
}
```

### Database Schema Mapping
```sql
CREATE TABLE dividend_history (
    symbol VARCHAR NOT NULL,
    ex_dividend_date DATE NOT NULL,
    declaration_date DATE,
    record_date DATE,
    payment_date DATE,
    amount DOUBLE,
    PRIMARY KEY (symbol, ex_dividend_date)
);
```

---

## 3. Earnings History (EARNINGS)

### API Endpoint
```
GET https://www.alphavantage.co/query?function=EARNINGS&symbol=AAPL
```

### API Response Schema
```json
{
  "symbol": "AAPL",
  "annualEarnings": [
    {
      "fiscalDateEnding": "2023-12-31",
      "reportedEPS": "6.13"
    }
  ],
  "quarterlyEarnings": [
    {
      "fiscalDateEnding": "2024-03-31",
      "reportedDate": "2024-05-02",
      "reportedEPS": "1.52",
      "estimatedEPS": "1.50",
      "surprise": "0.02",
      "surprisePercentage": "1.33"
    }
  ]
}
```

### Function Return Schema
- **Type**: `pd.DataFrame`
- **Function**: `fetch_earnings_history(symbol: str, quarterly: bool = True)`

**DataFrame Columns (Quarterly):**
```python
{
    "symbol": str,                      # Added
    "fiscalDateEnding": datetime,       # Converted from string
    "reportedDate": datetime,           # Converted from string
    "reportedEPS": float,               # Converted from string
    "estimatedEPS": float,              # Converted from string
    "surprise": float,                  # Converted from string
    "surprisePercentage": float         # Converted from string
}
```

**DataFrame Columns (Annual):**
```python
{
    "symbol": str,                      # Added
    "fiscalDateEnding": datetime,       # Converted from string
    "reportedEPS": float                # Converted from string
}
```

### Database Schema Mapping
```sql
CREATE TABLE earnings_history (
    symbol VARCHAR NOT NULL,
    fiscal_date_ending DATE NOT NULL,
    reported_date DATE,                 -- Quarterly only
    reported_eps DOUBLE,
    estimated_eps DOUBLE,               -- Quarterly only
    surprise DOUBLE,                    -- Quarterly only
    surprise_percentage DOUBLE,         -- Quarterly only
    PRIMARY KEY (symbol, fiscal_date_ending)
);
```

---

## 4. Income Statement (INCOME_STATEMENT)

### API Endpoint
```
GET https://www.alphavantage.co/query?function=INCOME_STATEMENT&symbol=AAPL
```

### API Response Schema
```json
{
  "symbol": "AAPL",
  "annualReports": [
    {
      "fiscalDateEnding": "2023-12-31",
      "reportedCurrency": "USD",
      "totalRevenue": "383000000000",
      "grossProfit": "170000000000",
      "costOfRevenue": "213000000000",
      "operatingIncome": "114000000000",
      "netIncome": "97000000000",
      "ebitda": "129000000000",
      "eps": "6.13",
      "researchAndDevelopment": "29000000000",
      "sellingGeneralAndAdministrative": "27000000000",
      "interestExpense": "3000000000",
      "incomeTaxExpense": "17000000000"
    }
  ],
  "quarterlyReports": [ /* Similar structure */ ]
}
```

### Function Return Schema
- **Type**: `pd.DataFrame`
- **Function**: `fetch_income_statement(symbol: str, quarterly: bool = False)`

**DataFrame Columns:**
```python
{
    "symbol": str,                      # Added
    "fiscal_date_ending": datetime,     # Converted from fiscalDateEnding
    "total_revenue": float,             # Converted from totalRevenue
    "gross_profit": float,              # Converted from grossProfit
    "operating_income": float,          # Converted from operatingIncome
    "net_income": float,                # Converted from netIncome
    "eps": float,                       # Converted from string
    "full_data": dict                   # Complete API response as JSON
}
```

### Database Schema Mapping
```sql
CREATE TABLE income_statements (
    symbol VARCHAR NOT NULL,
    fiscal_date_ending DATE NOT NULL,
    total_revenue BIGINT,
    gross_profit BIGINT,
    operating_income BIGINT,
    net_income BIGINT,
    eps DOUBLE,
    full_data JSON,                     -- Complete API response
    PRIMARY KEY (symbol, fiscal_date_ending)
);
```

---

## 5. Balance Sheet (BALANCE_SHEET)

### API Endpoint
```
GET https://www.alphavantage.co/query?function=BALANCE_SHEET&symbol=AAPL
```

### API Response Schema
```json
{
  "symbol": "AAPL",
  "annualReports": [
    {
      "fiscalDateEnding": "2023-12-31",
      "reportedCurrency": "USD",
      "totalAssets": "350000000000",
      "totalCurrentAssets": "150000000000",
      "totalNonCurrentAssets": "200000000000",
      "totalLiabilities": "250000000000",
      "totalCurrentLiabilities": "120000000000",
      "totalNonCurrentLiabilities": "130000000000",
      "totalShareholderEquity": "100000000000",
      "retainedEarnings": "50000000000",
      "commonStock": "70000000000"
    }
  ],
  "quarterlyReports": [ /* Similar structure */ ]
}
```

### Function Return Schema
- **Type**: `pd.DataFrame`
- **Function**: `fetch_balance_sheet(symbol: str, quarterly: bool = False)`

**DataFrame Columns:**
```python
{
    "symbol": str,                          # Added
    "fiscal_date_ending": datetime,         # Converted from fiscalDateEnding
    "total_assets": float,                  # Converted from totalAssets
    "total_liabilities": float,             # Converted from totalLiabilities
    "total_shareholder_equity": float,      # Converted from totalShareholderEquity
    "full_data": dict                       # Complete API response as JSON
}
```

### Database Schema Mapping
```sql
CREATE TABLE balance_sheets (
    symbol VARCHAR NOT NULL,
    fiscal_date_ending DATE NOT NULL,
    total_assets BIGINT,
    total_liabilities BIGINT,
    total_shareholder_equity BIGINT,
    full_data JSON,                         -- Complete API response
    PRIMARY KEY (symbol, fiscal_date_ending)
);
```

---

## 6. Cash Flow Statement (CASH_FLOW)

### API Endpoint
```
GET https://www.alphavantage.co/query?function=CASH_FLOW&symbol=AAPL
```

### API Response Schema
```json
{
  "symbol": "AAPL",
  "annualReports": [
    {
      "fiscalDateEnding": "2023-12-31",
      "reportedCurrency": "USD",
      "operatingCashflow": "110000000000",
      "capitalExpenditures": "-11000000000",
      "freeCashflow": "99000000000",
      "cashflowFromInvestment": "-5000000000",
      "cashflowFromFinancing": "-90000000000",
      "dividendPayout": "-15000000000"
    }
  ],
  "quarterlyReports": [ /* Similar structure */ ]
}
```

### Function Return Schema
- **Type**: `pd.DataFrame`
- **Function**: `fetch_cash_flow(symbol: str, quarterly: bool = False)`

**DataFrame Columns:**
```python
{
    "symbol": str,                      # Added
    "fiscal_date_ending": datetime,     # Converted from fiscalDateEnding
    "operating_cashflow": float,        # Converted from operatingCashflow
    "capital_expenditures": float,      # Converted from capitalExpenditures
    "free_cashflow": float,             # Converted from freeCashflow
    "full_data": dict                   # Complete API response as JSON
}
```

### Database Schema Mapping
```sql
CREATE TABLE cash_flows (
    symbol VARCHAR NOT NULL,
    fiscal_date_ending DATE NOT NULL,
    operating_cashflow BIGINT,
    capital_expenditures BIGINT,
    free_cashflow BIGINT,
    full_data JSON,                     -- Complete API response
    PRIMARY KEY (symbol, fiscal_date_ending)
);
```

---

## Type Conversions Summary

All functions perform the following conversions for SQL compatibility:

### Date Fields
- **API**: `"YYYY-MM-DD"` (string)
- **DataFrame**: `datetime` (pandas datetime64)
- **SQL**: `DATE` or `TIMESTAMP`

### Numeric Fields
- **API**: `"123456789"` (string)
- **DataFrame**: `float` or `int` (pd.to_numeric with errors='coerce')
- **SQL**: `BIGINT` or `DOUBLE`

### JSON Fields
- **API**: Nested objects
- **DataFrame**: `dict` (full_data column)
- **SQL**: `JSON` column type (DuckDB native)

---

## DAO Integration Notes

For the Data Access Layer (DAO) implementation:

1. **DataFrame → SQL**: All DataFrames are ready for `df.to_sql()` insertion
   - Column names already in snake_case
   - All types converted to SQL-compatible formats
   - Symbol column included for composite keys

2. **JSON Storage**: Use `full_data` column to preserve complete API responses
   - Enables future schema migrations without data loss
   - Allows ad-hoc queries on additional fields

3. **Duplicate Handling**: Use `INSERT OR REPLACE` or `INSERT ... ON CONFLICT`
   - Primary keys: `(symbol, fiscal_date_ending)` or `(symbol, ex_dividend_date)`
   - Prevents duplicate records on re-fetch

4. **Bulk Insert**: Use `dao.bulk_insert(table, df)` for efficient batch operations
   - DataFrames already sorted by date (descending)
   - Ready for time-series queries

---

## Testing

All schema implementations have comprehensive unit tests:
- `tests/test_skills/test_alpha_vantage_skills.py` (14 tests)
- Validates DataFrame structure, column names, and type conversions
- Tests both annual and quarterly data where applicable

---

## Version History

- **2024-02-17**: Initial schema documentation
  - Updated all functions to use snake_case columns
  - Added symbol column to all DataFrames
  - Added full_data JSON column for complete API responses
  - Implemented type conversions for SQL compatibility
