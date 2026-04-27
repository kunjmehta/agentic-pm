"""Alpha Vantage API integration functions for fundamental data.

This module provides functions to fetch company fundamentals, dividends,
earnings, and financial statements from Alpha Vantage API using requests.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from typing import Dict, Optional
import pandas as pd
import requests
import time
from src.common.utils import secrets, get_logger
from src.common.dao import AlphaVantageDAO


# Initialize logger
logger = get_logger(__name__)

# Alpha Vantage API base URL
BASE_URL = "https://www.alphavantage.co/query"

# Get API key from secrets
API_KEY = secrets.get("alpha_vantage.api_key")

# Rate limiting: 1 request per 1.5 seconds
MIN_REQUEST_INTERVAL = 1.5  # seconds
_last_request_time = 0.0

logger.info("Alpha Vantage client initialized with rate limiting (1 request per 1.5s)")


def _clean_value(value):
    """Clean API values by converting 'None' strings and None to actual None.

    Args:
        value: Value from API response

    Returns:
        None if value is None or 'None' string, otherwise the original value
    """
    if value is None or value == "None" or value == "":
        return None
    return value


def _to_float(value, default=None):
    """Safely convert value to float, handling None/'None' strings.

    Args:
        value: Value to convert
        default: Default value if conversion fails

    Returns:
        Float value or default
    """
    value = _clean_value(value)
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _make_request(params: dict) -> dict:
    """Make HTTP request to Alpha Vantage API with rate limiting.

    Enforces a minimum delay of 1.5 seconds between requests to comply with
    Alpha Vantage free tier rate limits (1 request per second).

    Args:
        params: Query parameters for the API request

    Returns:
        JSON response as dictionary

    Raises:
        Exception: If API request fails
    """
    global _last_request_time

    if not API_KEY:
        error_msg = (
            "Alpha Vantage API key is not configured. "
            "Please set secret 'alpha_vantage.api_key' before making requests."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    params["apikey"] = API_KEY
    function = params.get("function", "UNKNOWN")
    symbol = params.get("symbol", "UNKNOWN")

    # Rate limiting: ensure minimum interval between requests
    current_time = time.time()
    time_since_last_request = current_time - _last_request_time

    if time_since_last_request < MIN_REQUEST_INTERVAL:
        sleep_time = MIN_REQUEST_INTERVAL - time_since_last_request
        logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f}s before request")
        time.sleep(sleep_time)

    logger.debug(f"Making Alpha Vantage API request: function={function}, symbol={symbol}")

    response = requests.get(BASE_URL, params=params, timeout=180)
    response.raise_for_status()

    data = response.json()

    # Check for API error messages
    if "Error Message" in data:
        error_msg = f"API Error: {data['Error Message']}"
        logger.error(error_msg)
        raise Exception(error_msg)

    # Check for rate limit messages (Note or Information keys)
    if "Note" in data:
        error_msg = f"API Rate Limit: {data['Note']}"
        logger.warning(error_msg)
        raise Exception(error_msg)

    if "Information" in data:
        error_msg = f"API Rate Limit: {data['Information']}"
        logger.warning(error_msg)
        raise Exception(error_msg)

    # Update last request time after successful request
    _last_request_time = time.time()

    logger.debug(f"Successfully received data from Alpha Vantage: function={function}")
    return data


def fetch_company_overview(symbol: str) -> Dict[str, str]:
    """Fetch company overview and fundamental data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")

    Returns:
        Dictionary containing company fundamentals including:
        - Name, Description, Sector, Industry
        - MarketCapitalization, PERatio, DividendYield
        - ProfitMargin, EPS, Beta, etc.

    Raises:
        Exception: If API request fails
    """
    logger.info(f"Fetching company overview for {symbol}")

    try:
        params = {
            "function": "OVERVIEW",
            "symbol": symbol
        }
        data = _make_request(params)
        logger.info(f"Successfully fetched company overview for {symbol}")

        # Automatically save to database
        try:
            dao = AlphaVantageDAO()
            dao.save_company_overview(symbol, data)
            logger.info(f"Saved company overview for {symbol} to database")
        except Exception as db_error:
            logger.warning(f"Failed to save company overview to database: {db_error}")

        return data

    except Exception as e:
        error_msg = f"Failed to fetch company overview for {symbol}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def fetch_dividend_history(symbol: str) -> pd.DataFrame:
    """Fetch historical dividend data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")

    Returns:
        DataFrame with columns: symbol, ex_dividend_date, declaration_date,
        record_date, payment_date, amount

        Schema matches Alpha Vantage DIVIDENDS response:
        {
          "symbol": str,
          "data": [
            {
              "ex_dividend_date": str,
              "declaration_date": str,
              "record_date": str,
              "payment_date": str,
              "amount": str
            }
          ]
        }

    Raises:
        Exception: If API request fails
    """
    logger.info(f"Fetching dividend history for {symbol}")

    try:
        params = {
            "function": "DIVIDENDS",
            "symbol": symbol
        }
        data = _make_request(params)

        # Extract dividend data from response
        dividend_data = data.get("data", [])

        # Convert to DataFrame with all schema fields
        dividends = []
        for record in dividend_data:
            dividends.append({
                "symbol": symbol,
                "ex_dividend_date": _clean_value(record.get("ex_dividend_date")),
                "declaration_date": _clean_value(record.get("declaration_date")),
                "record_date": _clean_value(record.get("record_date")),
                "payment_date": _clean_value(record.get("payment_date")),
                "amount": _to_float(record.get("amount")),
            })

        df = pd.DataFrame(dividends)
        if not df.empty:
            # Convert date columns to datetime, coerce errors to NaT
            df['ex_dividend_date'] = pd.to_datetime(df['ex_dividend_date'], errors='coerce')
            df['declaration_date'] = pd.to_datetime(df['declaration_date'], errors='coerce')
            df['record_date'] = pd.to_datetime(df['record_date'], errors='coerce')
            df['payment_date'] = pd.to_datetime(df['payment_date'], errors='coerce')
            df = df.sort_values('ex_dividend_date', ascending=False)

        logger.info(f"Successfully fetched {len(df)} dividend records for {symbol}")

        # Automatically save to database
        try:
            dao = AlphaVantageDAO()
            rows = dao.save_dividends(symbol, df)
            logger.info(f"Saved {rows} dividend records to database")
        except Exception as db_error:
            logger.warning(f"Failed to save dividends to database: {db_error}")

        return df

    except Exception as e:
        error_msg = f"Failed to fetch dividend history for {symbol}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def fetch_earnings_history(symbol: str, quarterly: bool = True) -> pd.DataFrame:
    """Fetch quarterly and annual earnings data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        quarterly: If True, return quarterly earnings; otherwise annual

    Returns:
        DataFrame with earnings data.

        For quarterly earnings:
        - symbol, fiscalDateEnding, reportedDate, reportedEPS, estimatedEPS,
          surprise, surprisePercentage

        For annual earnings:
        - symbol, fiscalDateEnding, reportedEPS

        Schema matches Alpha Vantage EARNINGS response:
        {
          "symbol": str,
          "annualEarnings": [
            {
              "fiscalDateEnding": str,
              "reportedEPS": str
            }
          ],
          "quarterlyEarnings": [
            {
              "fiscalDateEnding": str,
              "reportedDate": str,
              "reportedEPS": str,
              "estimatedEPS": str,
              "surprise": str,
              "surprisePercentage": str
            }
          ]
        }

    Raises:
        Exception: If API request fails
    """
    logger.info(f"Fetching earnings history for {symbol} (quarterly={quarterly})")

    try:
        params = {
            "function": "EARNINGS",
            "symbol": symbol
        }
        data = _make_request(params)

        # Choose quarterly or annual earnings
        key = "quarterlyEarnings" if quarterly else "annualEarnings"
        earnings_data = data.get(key, [])

        df = pd.DataFrame(earnings_data)

        if not df.empty:
            # Add symbol column
            df.insert(0, 'symbol', symbol)

            # Clean None/"None" values in all string columns
            for col in df.columns:
                if df[col].dtype == 'object':
                    df[col] = df[col].apply(lambda x: _clean_value(x) if isinstance(x, str) else x)

            # Convert date columns
            df['fiscalDateEnding'] = pd.to_datetime(df['fiscalDateEnding'], errors='coerce')
            if quarterly and 'reportedDate' in df.columns:
                df['reportedDate'] = pd.to_datetime(df['reportedDate'], errors='coerce')

            # Convert numeric columns
            numeric_cols = ['reportedEPS', 'estimatedEPS', 'surprise', 'surprisePercentage']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            df = df.sort_values('fiscalDateEnding', ascending=False)

        logger.info(f"Successfully fetched {len(df)} earnings records for {symbol}")

        # Automatically save to database
        try:
            dao = AlphaVantageDAO()
            rows = dao.save_earnings(symbol, df, quarterly=quarterly)
            logger.info(f"Saved {rows} earnings records to database")
        except Exception as db_error:
            logger.warning(f"Failed to save earnings to database: {db_error}")

        return df

    except Exception as e:
        error_msg = f"Failed to fetch earnings history for {symbol}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def fetch_income_statement(symbol: str, quarterly: bool = False) -> pd.DataFrame:
    """Fetch income statement (P&L) data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        quarterly: If True, fetch quarterly data; otherwise annual

    Returns:
        DataFrame with income statement data including:
        - symbol, fiscal_date_ending, total_revenue, gross_profit,
          operating_income, net_income, eps, full_data (JSON)

        Schema matches Alpha Vantage INCOME_STATEMENT response.
        Key fields extracted for SQL insertion:
        - Numeric fields converted to appropriate types
        - Full JSON stored in full_data column

    Raises:
        Exception: If API request fails
    """
    logger.info(f"Fetching income statement for {symbol} (quarterly={quarterly})")

    try:
        params = {
            "function": "INCOME_STATEMENT",
            "symbol": symbol
        }
        data = _make_request(params)

        # Choose quarterly or annual reports
        key = "quarterlyReports" if quarterly else "annualReports"
        reports = data.get(key, [])

        # Extract key fields for SQL insertion
        income_data = []
        for report in reports:
            income_data.append({
                "symbol": symbol,
                "fiscal_date_ending": _clean_value(report.get("fiscalDateEnding")),
                "total_revenue": _to_float(report.get("totalRevenue")),
                "gross_profit": _to_float(report.get("grossProfit")),
                "operating_income": _to_float(report.get("operatingIncome")),
                "net_income": _to_float(report.get("netIncome")),
                "eps": _to_float(report.get("eps")),
                "full_data": report  # Store complete JSON
            })

        df = pd.DataFrame(income_data)

        if not df.empty:
            # Convert date columns
            df['fiscal_date_ending'] = pd.to_datetime(df['fiscal_date_ending'], errors='coerce')

            df = df.sort_values('fiscal_date_ending', ascending=False)

        logger.info(f"Successfully fetched {len(df)} income statement records for {symbol}")

        # Automatically save to database
        try:
            dao = AlphaVantageDAO()
            rows = dao.save_income_statement(symbol, df, quarterly=quarterly)
            logger.info(f"Saved {rows} income statement records to database")
        except Exception as db_error:
            logger.warning(f"Failed to save income statement to database: {db_error}")

        return df

    except Exception as e:
        error_msg = f"Failed to fetch income statement for {symbol}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def fetch_balance_sheet(symbol: str, quarterly: bool = False) -> pd.DataFrame:
    """Fetch balance sheet data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        quarterly: If True, fetch quarterly data; otherwise annual

    Returns:
        DataFrame with balance sheet data including:
        - symbol, fiscal_date_ending, total_assets, total_liabilities,
          total_shareholder_equity, full_data (JSON)

        Schema matches Alpha Vantage BALANCE_SHEET response.
        Key fields extracted for SQL insertion:
        - Numeric fields converted to appropriate types
        - Full JSON stored in full_data column

    Raises:
        Exception: If API request fails
    """
    logger.info(f"Fetching balance sheet for {symbol} (quarterly={quarterly})")

    try:
        params = {
            "function": "BALANCE_SHEET",
            "symbol": symbol
        }
        data = _make_request(params)

        # Choose quarterly or annual reports
        key = "quarterlyReports" if quarterly else "annualReports"
        reports = data.get(key, [])

        # Extract key fields for SQL insertion
        balance_data = []
        for report in reports:
            balance_data.append({
                "symbol": symbol,
                "fiscal_date_ending": _clean_value(report.get("fiscalDateEnding")),
                "total_assets": _to_float(report.get("totalAssets")),
                "total_liabilities": _to_float(report.get("totalLiabilities")),
                "total_shareholder_equity": _to_float(report.get("totalShareholderEquity")),
                "full_data": report  # Store complete JSON
            })

        df = pd.DataFrame(balance_data)

        if not df.empty:
            # Convert date columns
            df['fiscal_date_ending'] = pd.to_datetime(df['fiscal_date_ending'], errors='coerce')

            df = df.sort_values('fiscal_date_ending', ascending=False)

        logger.info(f"Successfully fetched {len(df)} balance sheet records for {symbol}")

        # Automatically save to database
        try:
            dao = AlphaVantageDAO()
            rows = dao.save_balance_sheet(symbol, df, quarterly=quarterly)
            logger.info(f"Saved {rows} balance sheet records to database")
        except Exception as db_error:
            logger.warning(f"Failed to save balance sheet to database: {db_error}")

        return df

    except Exception as e:
        error_msg = f"Failed to fetch balance sheet for {symbol}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def fetch_cash_flow(symbol: str, quarterly: bool = False) -> pd.DataFrame:
    """Fetch cash flow statement data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        quarterly: If True, fetch quarterly data; otherwise annual

    Returns:
        DataFrame with cash flow data including:
        - symbol, fiscal_date_ending, operating_cashflow, capital_expenditures,
          free_cashflow, full_data (JSON)

        Schema matches Alpha Vantage CASH_FLOW response.
        Key fields extracted for SQL insertion:
        - Numeric fields converted to appropriate types
        - Full JSON stored in full_data column

    Raises:
        Exception: If API request fails
    """
    logger.info(f"Fetching cash flow for {symbol} (quarterly={quarterly})")

    try:
        params = {
            "function": "CASH_FLOW",
            "symbol": symbol
        }
        data = _make_request(params)

        # Choose quarterly or annual reports
        key = "quarterlyReports" if quarterly else "annualReports"
        reports = data.get(key, [])

        # Extract key fields for SQL insertion
        cashflow_data = []
        for report in reports:
            cashflow_data.append({
                "symbol": symbol,
                "fiscal_date_ending": _clean_value(report.get("fiscalDateEnding")),
                "operating_cashflow": _to_float(report.get("operatingCashflow")),
                "capital_expenditures": _to_float(report.get("capitalExpenditures")),
                "free_cashflow": _to_float(report.get("freeCashflow")),
                "full_data": report  # Store complete JSON
            })

        df = pd.DataFrame(cashflow_data)

        if not df.empty:
            # Convert date columns
            df['fiscal_date_ending'] = pd.to_datetime(df['fiscal_date_ending'], errors='coerce')

            df = df.sort_values('fiscal_date_ending', ascending=False)

        logger.info(f"Successfully fetched {len(df)} cash flow records for {symbol}")

        # Automatically save to database
        try:
            dao = AlphaVantageDAO()
            rows = dao.save_cash_flow(symbol, df, quarterly=quarterly)
            logger.info(f"Saved {rows} cash flow records to database")
        except Exception as db_error:
            logger.warning(f"Failed to save cash flow to database: {db_error}")

        return df

    except Exception as e:
        error_msg = f"Failed to fetch cash flow for {symbol}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def fetch_all(symbol: str, quarterly: bool = False) -> Dict:
    """Fetch all available fundamental data for a symbol.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        quarterly: If True, fetch quarterly financial statements; otherwise annual

    Returns:
        Dictionary containing:
        - overview: Company overview and fundamentals
        - dividends: Historical dividend data (DataFrame)
        - earnings: Quarterly earnings data (DataFrame)
        - income_statement: Income statement (DataFrame)
        - balance_sheet: Balance sheet (DataFrame)
        - cash_flow: Cash flow statement (DataFrame)

    Raises:
        Exception: If any API request fails

    Note:
        This makes 6 API calls. Be mindful of Alpha Vantage rate limits
        (25 calls/day for free tier, 5 calls/minute).
    """
    results = {
        "symbol": symbol,
        "overview": None,
        "dividends": None,
        "earnings": None,
        "income_statement": None,
        "balance_sheet": None,
        "cash_flow": None,
        "errors": {}
    }

    # Fetch company overview
    try:
        results["overview"] = fetch_company_overview(symbol)
    except Exception as e:
        results["errors"]["overview"] = str(e)

    # Fetch dividend history
    try:
        results["dividends"] = fetch_dividend_history(symbol)
    except Exception as e:
        results["errors"]["dividends"] = str(e)

    # Fetch earnings history
    try:
        results["earnings"] = fetch_earnings_history(symbol)
    except Exception as e:
        results["errors"]["earnings"] = str(e)

    # Fetch income statement
    try:
        results["income_statement"] = fetch_income_statement(symbol, quarterly)
    except Exception as e:
        results["errors"]["income_statement"] = str(e)

    # Fetch balance sheet
    try:
        results["balance_sheet"] = fetch_balance_sheet(symbol, quarterly)
    except Exception as e:
        results["errors"]["balance_sheet"] = str(e)

    # Fetch cash flow
    try:
        results["cash_flow"] = fetch_cash_flow(symbol, quarterly)
    except Exception as e:
        results["errors"]["cash_flow"] = str(e)

    return results


if __name__ == "__main__":
    """Test Alpha Vantage API functions."""
    print("=" * 60)
    print("Testing Alpha Vantage API Functions (using requests)")
    print("=" * 60)

    # Test parameters
    test_symbol = "AAPL"

    # Test 1: Fetch company overview
    print(f"\n1. Fetching company overview for {test_symbol}...")
    try:
        overview = fetch_company_overview(test_symbol)
        print(f"   [OK] Fetched company overview")
        print(f"   Company: {overview.get('Name', 'N/A')}")
        print(f"   Sector: {overview.get('Sector', 'N/A')}")
        print(f"   Market Cap: {overview.get('MarketCapitalization', 'N/A')}")
        print(f"   P/E Ratio: {overview.get('PERatio', 'N/A')}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    # Test 2: Fetch dividend history
    print(f"\n2. Fetching dividend history for {test_symbol}...")
    try:
        dividends = fetch_dividend_history(test_symbol)
        print(f"   [OK] Fetched {len(dividends)} dividend records")
        if not dividends.empty:
            print(f"   Recent dividends:\n{dividends.head()}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    # Test 3: Fetch earnings history
    print(f"\n3. Fetching earnings history for {test_symbol}...")
    try:
        earnings = fetch_earnings_history(test_symbol)
        print(f"   [OK] Fetched earnings data")
        if isinstance(earnings, pd.DataFrame) and not earnings.empty:
            print(f"   Shape: {earnings.shape}")
            print(f"   Recent earnings:\n{earnings.head()}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    # Test 4: Fetch income statement
    print(f"\n4. Fetching income statement for {test_symbol}...")
    try:
        income_stmt = fetch_income_statement(test_symbol)
        print(f"   [OK] Fetched income statement")
        if isinstance(income_stmt, pd.DataFrame) and not income_stmt.empty:
            print(f"   Shape: {income_stmt.shape}")
            print(f"   Columns: {list(income_stmt.columns)[:5]}...")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    # Test 5: Fetch balance sheet
    print(f"\n5. Fetching balance sheet for {test_symbol}...")
    try:
        balance_sheet = fetch_balance_sheet(test_symbol)
        print(f"   [OK] Fetched balance sheet")
        if isinstance(balance_sheet, pd.DataFrame) and not balance_sheet.empty:
            print(f"   Shape: {balance_sheet.shape}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    # Test 6: Fetch cash flow
    print(f"\n6. Fetching cash flow for {test_symbol}...")
    try:
        cash_flow = fetch_cash_flow(test_symbol)
        print(f"   [OK] Fetched cash flow")
        if isinstance(cash_flow, pd.DataFrame) and not cash_flow.empty:
            print(f"   Shape: {cash_flow.shape}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")

    print("\n" + "=" * 60)
    print("Alpha Vantage API Tests Complete")
    print("=" * 60)
    print("\nNOTE: Alpha Vantage has rate limits (25 calls/day for free tier)")
    print("If you see errors, you may need to wait before testing again.")
