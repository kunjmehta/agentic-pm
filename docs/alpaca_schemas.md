# Alpaca API Schemas

This document tracks the Alpaca API response schemas and their mapping to database schemas for the Data Layer (DAO) implementation.

## Overview

All Alpaca functions return DataFrames with:
- **Snake_case column names** for SQL compatibility
- **Symbol and timestamp columns** for time-series data
- **Type conversions** (timestamps → datetime, numeric) for SQL insertion
- **None handling** ("None" strings converted to actual None/NaN)

---

## 1. Historical Bars (OHLCV Data)

### API Endpoint
```python
from alpaca.data.requests import StockBarsRequest
client.get_stock_bars(StockBarsRequest(...))
```

### API Response Schema
The Alpaca SDK returns a pandas DataFrame with MultiIndex (symbol, timestamp).

**Raw DataFrame Structure:**
```
Index: MultiIndex[(symbol, timestamp)]
Columns: [open, high, low, close, volume, trade_count, vwap]
```

### Function Return Schema
- **Type**: `pd.DataFrame`
- **Function**: `fetch_historical_bars(symbol: str, start: str, end: str, timeframe: str)`

**DataFrame Columns (after reset_index):**
```python
{
    "symbol": str,              # Stock ticker
    "timestamp": datetime,      # Bar timestamp (timezone-aware)
    "open": float,              # Opening price
    "high": float,              # Highest price
    "low": float,               # Lowest price
    "close": float,             # Closing price
    "volume": int,              # Total volume
    "trade_count": int,         # Number of trades
    "vwap": float               # Volume-Weighted Average Price
}
```

**Supported Timeframes:**
- `"1Min"` - 1-minute bars
- `"5Min"` - 5-minute bars
- `"15Min"` - 15-minute bars
- `"1Hour"` - 1-hour bars
- `"1Day"` - Daily bars

### Database Schema Mapping
```sql
CREATE TABLE market_bars (
    symbol VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    timeframe VARCHAR NOT NULL,     -- '1Min', '5Min', '1Hour', '1Day'
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT,
    trade_count INTEGER,
    vwap DOUBLE,
    PRIMARY KEY (symbol, timestamp, timeframe)
);
```

---

## 2. Historical Trades

### API Endpoint
```python
from alpaca.data.requests import StockTradesRequest
client.get_stock_trades(StockTradesRequest(...))
```

### API Response Schema
The Alpaca SDK returns a pandas DataFrame with MultiIndex (symbol, timestamp).

**Raw DataFrame Structure:**
```
Index: MultiIndex[(symbol, timestamp)]
Columns: [price, size, exchange, conditions, id, tape]
```

### Function Return Schema
- **Type**: `pd.DataFrame`
- **Function**: `fetch_historical_trades(symbol: str, start: str, end: str, limit: int)`

**DataFrame Columns (after reset_index):**
```python
{
    "symbol": str,              # Stock ticker
    "timestamp": datetime,      # Trade timestamp (timezone-aware)
    "price": float,             # Trade price
    "size": int,                # Trade size (shares)
    "exchange": str,            # Exchange code (e.g., 'P', 'Q')
    "conditions": str,          # Trade conditions (e.g., '@', 'T')
    "id": int,                  # Trade ID
    "tape": str                 # SIP tape (A, B, or C)
}
```

**Trade Conditions Examples:**
- `@` - Regular trade
- `T` - Extended hours trade
- `I` - Odd lot trade
- `M` - Market center official close

**Exchange Codes:**
- `P` - NYSE Arca
- `Q` - NASDAQ
- `V` - IEX
- `K` - CBOE EDGX

### Database Schema Mapping
```sql
CREATE TABLE historical_trades (
    symbol VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    trade_id BIGINT NOT NULL,
    price DOUBLE,
    size INTEGER,
    exchange VARCHAR(1),
    conditions VARCHAR,
    tape VARCHAR(1),
    PRIMARY KEY (symbol, timestamp, trade_id)
);
```

---

## 3. Watchlist

While not directly returned by Alpaca API, this table tracks symbols being monitored.

### Database Schema
```sql
CREATE TABLE watchlist (
    symbol VARCHAR PRIMARY KEY,
    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active BOOLEAN DEFAULT TRUE,
    notes TEXT
);
```

---

## Type Conversions Summary

All functions perform the following conversions for SQL compatibility:

### Timestamp Fields
- **API**: `Timestamp` (pandas timestamp, timezone-aware)
- **DataFrame**: `datetime64[ns]` (pandas datetime)
- **SQL**: `TIMESTAMP`

### Numeric Fields
- **API**: Already numeric types from SDK
- **DataFrame**: `float64`, `int64`
- **SQL**: `DOUBLE`, `BIGINT`, `INTEGER`

### String Fields
- **API**: `str`
- **DataFrame**: `object` dtype
- **SQL**: `VARCHAR`

---

## Data Characteristics

### Bars (OHLCV)
- **Volume**: Typical range 100 - 1M+ shares per bar
- **Update Frequency**: Real-time during market hours
- **Storage Size**: ~100 bytes per bar
- **Retention**: Alpaca provides historical data based on subscription tier

### Trades
- **Volume**: Can be millions of trades per day for liquid stocks
- **Update Frequency**: Real-time tick data
- **Storage Size**: ~80 bytes per trade
- **Retention**: Limited by Alpaca subscription tier and API limits

### Storage Estimates
For a single symbol:
- **1-minute bars**: ~390 records/day × 252 days = ~98,000 records/year
- **Trades**: ~50,000-500,000 trades/day for liquid stocks

---

## DAO Integration Notes

For the Data Access Layer (DAO) implementation:

1. **DataFrame → SQL**: All DataFrames are ready for `df.to_sql()` insertion
   - Column names in snake_case
   - All types converted to SQL-compatible formats
   - Symbol and timestamp included for composite keys

2. **Time-Series Optimization**:
   - Use `(symbol, timestamp, timeframe)` composite primary key for bars
   - Use `(symbol, timestamp, trade_id)` composite primary key for trades
   - Create indexes on `(symbol, timestamp DESC)` for fast range queries

3. **Duplicate Handling**: Use `INSERT OR REPLACE` or `INSERT ... ON CONFLICT`
   - Prevents duplicate records on re-fetch
   - Allows updating existing data

4. **Bulk Insert**: Use `dao.bulk_insert(table, df)` for efficient batch operations
   - DataFrames can be large (100K+ rows)
   - Use transactions for atomicity

5. **Timeframe Storage**:
   - Store timeframe as string ('1Min', '1Hour', '1Day')
   - Allows querying specific granularities
   - Separate records for same timestamp at different timeframes

---

## Testing

All schema implementations have comprehensive unit tests:
- `tests/test_skills/test_alpaca_skills.py` (5 tests)
- Validates DataFrame structure, column names, and type conversions
- Tests both bars and trades fetching

---

## Example Queries

### Get latest bars for a symbol
```sql
SELECT * FROM market_bars
WHERE symbol = 'AAPL' AND timeframe = '1Day'
ORDER BY timestamp DESC
LIMIT 30;
```

### Get intraday high/low
```sql
SELECT
    symbol,
    DATE(timestamp) as date,
    MAX(high) as day_high,
    MIN(low) as day_low,
    SUM(volume) as total_volume
FROM market_bars
WHERE symbol = 'AAPL'
  AND timeframe = '1Min'
  AND timestamp >= CURRENT_DATE
GROUP BY symbol, DATE(timestamp);
```

### Get recent large trades
```sql
SELECT
    timestamp,
    price,
    size,
    exchange,
    conditions
FROM historical_trades
WHERE symbol = 'AAPL'
  AND size >= 10000
  AND timestamp >= CURRENT_TIMESTAMP - INTERVAL '1 hour'
ORDER BY size DESC
LIMIT 100;
```

### Calculate VWAP
```sql
SELECT
    symbol,
    SUM(vwap * volume) / SUM(volume) as daily_vwap,
    SUM(volume) as total_volume
FROM market_bars
WHERE symbol = 'AAPL'
  AND timeframe = '1Min'
  AND DATE(timestamp) = CURRENT_DATE
GROUP BY symbol;
```

---

## Version History

- **2024-02-17**: Initial schema documentation
  - Defined market_bars and historical_trades tables
  - Added watchlist table
  - Documented DataFrame schemas and type conversions
  - Added example queries and storage estimates
