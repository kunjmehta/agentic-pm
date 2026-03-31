# Test Suite for Agentic Trader

This directory contains comprehensive tests for the agentic-trader project.

## Test Structure

```
tests/
├── conftest.py                              # Shared fixtures and configuration
├── pytest.ini                               # Pytest configuration
├── dao/
│   ├── test_strategy_dao.py                 # StrategyDAO tests
│   └── test_multi_database.py              # Multi-database separation tests (NEW)
├── data_gatherer/
│   └── test_trade_cache.py                 # TradeCache tests (NEW)
├── etl/
│   └── test_indicators_engine.py           # IndicatorsEngine tests (NEW)
├── integration/
│   ├── test_etl_pipeline.py                # ETL integration tests (NEW)
│   └── test_pagination.py                  # Pagination integration tests (NEW)
├── performance/
│   └── test_cache_throughput.py            # Cache performance tests (NEW)
├── agents/
│   ├── test_middleware.py                   # Middleware tests
│   ├── test_quant_tools.py                  # Quant tools tests
│   └── quant/
│       ├── test_analyst.py                  # Analyst agent tests
│       └── skills/
│           └── test_mean_reversion.py       # Mean reversion strategy tests
```

## Running Tests

### Run All Tests
```bash
pytest
```

### Run Specific Test File
```bash
pytest tests/dao/test_strategy_dao.py
pytest tests/agents/test_middleware.py
pytest tests/agents/test_quant_tools.py
pytest tests/agents/quant/test_analyst.py
pytest tests/agents/quant/skills/test_mean_reversion.py
```

### Run Specific Test Class
```bash
pytest tests/dao/test_strategy_dao.py::TestStrategyDAO
pytest tests/agents/test_middleware.py::TestMarketHoursGuardMiddleware
```

### Run Specific Test Method
```bash
pytest tests/dao/test_strategy_dao.py::TestStrategyDAO::test_save_strategy_result
```

### Run with Verbose Output
```bash
pytest -v
```

### Run with Coverage Report
```bash
pytest --cov=src --cov-report=html
```

### Run Tests Matching Pattern
```bash
pytest -k "vwap"                    # Run tests with "vwap" in name
pytest -k "test_save"               # Run tests starting with "test_save"
```

### Skip Slow Tests
```bash
pytest -m "not slow"
```

### Run Only Integration Tests
```bash
pytest -m integration
```

### Run Only Performance Tests
```bash
pytest -m performance
```

### Run Only Unit Tests
```bash
pytest -m unit
```

### Run Tests by Directory
```bash
pytest tests/etl/                    # ETL pipeline tests
pytest tests/data_gatherer/          # Data gathering tests
pytest tests/integration/            # Integration tests
pytest tests/performance/            # Performance tests
```

## Test Markers

Tests are marked with custom markers:

- `@pytest.mark.unit` - Unit tests (isolated component tests)
- `@pytest.mark.integration` - Integration tests requiring multiple components
- `@pytest.mark.performance` - Performance tests (may be slow, test throughput/speed)
- `@pytest.mark.slow` - Slow-running tests
- `@pytest.mark.requires_api` - Tests requiring API keys (usually skipped)

## Test Coverage

Current test coverage by module:

### Ingestion Pipeline Redesign (NEW)

#### ETL Pipeline
- ✅ `IndicatorsEngine` - Full unit test coverage
  - Momentum indicators (MACD, RSI)
  - Volatility indicators (Bollinger Bands)
  - Volume indicators (OBV, volume trend)
  - Candlestick patterns (engulfing, doji, hammer, hanging man)
  - Mean reversion (Z-score, VWAP, percentile)
  - Edge cases (empty data, insufficient data, NaN values)

#### Cache Layer
- ✅ `TradeCache` - Full unit test coverage
  - Time-based flush triggers
  - Size-based flush triggers
  - Thread safety (concurrent adds, concurrent flushes)
  - Statistics and monitoring
  - Force flush
  - Singleton pattern
  - Edge cases

#### Multi-Database Architecture
- ✅ `BaseDAO` multi-database routing
- ✅ Database isolation (writes to different files)
- ✅ DAO database assignment (AlpacaDAO → market_data.duckdb, etc.)
  - Concurrent writes to different databases
  - Schema initialization
  - Override mechanisms

#### Integration Tests
- ✅ ETL pipeline end-to-end (fetch → compute → save)
- ✅ Multi-timeframe processing
- ✅ Watchlist batch processing
- ✅ Indicator accuracy verification
- ✅ Rolling window calculations
- ✅ Pagination (chunking, rate limiting, multi-page fetching)

#### Performance Tests
- ✅ Cache throughput (single-thread: >10K trades/sec, multi-thread: >5K trades/sec)
- ✅ Memory efficiency
- ✅ Flush performance
- ✅ Sustained high-volume load
- ✅ Realistic trading day simulation

### DAO Layer
- ✅ `StrategyDAO` - 100% coverage
  - Save strategy results
  - Get latest signals
  - Get recent signals
  - Get actionable signals
  - Performance metrics

### Middleware
- ✅ `MarketHoursGuardMiddleware` - 100% coverage
- ✅ `TracingMiddleware` - 100% coverage
- ✅ `PrettifyMiddleware` - 100% coverage
- ✅ `create_middleware_stack` - 100% coverage

### Tools
- ✅ `get_market_bars` - 100% coverage
- ✅ `get_company_fundamentals` - 100% coverage
- ✅ `save_eod_summary` - 100% coverage
- ✅ `save_strategy_result_tool` - 100% coverage

### Mean Reversion Strategy
- ✅ Statistics calculation (with VWAP)
- ✅ Moving averages calculation
- ✅ Bollinger Bands calculation
- ✅ Support/resistance levels
- ✅ Signal generation
- ✅ VWAP confirmation logic
- ✅ Trade recommendations

### Analyst Agent
- ✅ Pydantic models validation
- ✅ Tool loading
- ✅ Middleware integration
- ✅ Natural language invoke
- ✅ Skill discovery

## Writing New Tests

### Test File Template

```python
"""Tests for [module name]."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from src.[module] import [class]


@pytest.fixture
def sample_data():
    """Create sample data for testing."""
    return {}


class TestClassName:
    """Test suite for ClassName."""

    def test_initialization(self):
        """Test class initializes correctly."""
        instance = ClassName()
        assert instance is not None

    def test_method_with_fixture(self, sample_data):
        """Test method using fixture."""
        result = method(sample_data)
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

## Continuous Integration

Tests are automatically run on:
- Pre-commit hooks (if configured)
- Pull request creation
- Merge to main branch

## Troubleshooting

### Import Errors
If you get import errors, ensure you're running pytest from the project root:
```bash
cd /path/to/agentic-trader
pytest
```

### Database Errors
Tests create a temporary database. If tests fail due to database locks:
```bash
# Remove test database
rm data/portfolio.duckdb
pytest
```

### Missing Dependencies
Install test dependencies:
```bash
pip install pytest pytest-cov
```

## Best Practices

1. **Isolation**: Each test should be independent and not rely on other tests
2. **Fixtures**: Use fixtures for common setup/teardown
3. **Mocking**: Mock external dependencies (APIs, databases) when appropriate
4. **Assertions**: Use clear, descriptive assertions
5. **Documentation**: Document what each test validates
6. **Fast**: Keep tests fast - use `@pytest.mark.slow` for slow tests
7. **Coverage**: Aim for >80% code coverage

## Contact

For questions about tests, see the main project README or create an issue.
