"""Alpha Vantage API integration functions for fundamental data.

This module provides functions to fetch company fundamentals, dividends,
earnings, and financial statements from Alpha Vantage API using requests.
"""

import json
from pathlib import Path
from typing import Dict, Optional
import pandas as pd
import requests


# Alpha Vantage API base URL
BASE_URL = "https://www.alphavantage.co/query"


# Load secrets from secret.json
def _load_secrets():
    """Load API credentials from secret.json file."""
    secret_path = Path(__file__).parent.parent.parent / "config" / "secret.json"
    if not secret_path.exists():
        raise FileNotFoundError(
            f"secret.json not found at {secret_path}. "
            "Please create it from secret.json.example"
        )
    with open(secret_path, "r") as f:
        return json.load(f)


secrets = _load_secrets()
API_KEY = secrets["alpha_vantage"]["api_key"]


def _make_request(params: dict) -> dict:
    """Make HTTP request to Alpha Vantage API.

    Args:
        params: Query parameters for the API request

    Returns:
        JSON response as dictionary

    Raises:
        Exception: If API request fails
    """
    params["apikey"] = API_KEY
    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()

    # Check for API error messages
    if "Error Message" in data:
        raise Exception(f"API Error: {data['Error Message']}")
    if "Note" in data:
        raise Exception(f"API Rate Limit: {data['Note']}")

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
    try:
        params = {
            "function": "OVERVIEW",
            "symbol": symbol
        }
        data = _make_request(params)
        return data

    except Exception as e:
        raise Exception(f"Failed to fetch company overview for {symbol}: {str(e)}")


def fetch_dividend_history(symbol: str) -> pd.DataFrame:
    """Fetch historical dividend data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")

    Returns:
        DataFrame with columns: date, dividend_amount

    Raises:
        Exception: If API request fails
    """
    try:
        params = {
            "function": "DIVIDENDS",
            "symbol": symbol
        }
        data = _make_request(params)

        # Extract dividend data from response
        dividend_data = data.get("data", [])

        dividends = []
        for record in dividend_data:
            dividends.append({
                "date": record.get("ex_dividend_date"),
                "dividend_amount": float(record.get("amount", 0)),
                "payment_date": record.get("payment_date"),
            })

        df = pd.DataFrame(dividends)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date', ascending=False)

        return df

    except Exception as e:
        raise Exception(f"Failed to fetch dividend history for {symbol}: {str(e)}")


def fetch_earnings_history(symbol: str) -> pd.DataFrame:
    """Fetch quarterly and annual earnings data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")

    Returns:
        DataFrame with earnings data including:
        - fiscalDateEnding, reportedEPS, estimatedEPS, surprise, surprisePercentage

    Raises:
        Exception: If API request fails
    """
    try:
        params = {
            "function": "EARNINGS",
            "symbol": symbol
        }
        data = _make_request(params)

        # Extract quarterly earnings
        quarterly_earnings = data.get("quarterlyEarnings", [])
        df = pd.DataFrame(quarterly_earnings)

        if not df.empty:
            df['fiscalDateEnding'] = pd.to_datetime(df['fiscalDateEnding'])
            df = df.sort_values('fiscalDateEnding', ascending=False)

        return df

    except Exception as e:
        raise Exception(f"Failed to fetch earnings history for {symbol}: {str(e)}")


def fetch_income_statement(symbol: str, quarterly: bool = False) -> pd.DataFrame:
    """Fetch income statement (P&L) data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        quarterly: If True, fetch quarterly data; otherwise annual

    Returns:
        DataFrame with income statement data including:
        - fiscalDateEnding, totalRevenue, grossProfit, netIncome, EPS, etc.

    Raises:
        Exception: If API request fails
    """
    try:
        params = {
            "function": "INCOME_STATEMENT",
            "symbol": symbol
        }
        data = _make_request(params)

        # Choose quarterly or annual reports
        key = "quarterlyReports" if quarterly else "annualReports"
        reports = data.get(key, [])
        df = pd.DataFrame(reports)

        if not df.empty:
            df['fiscalDateEnding'] = pd.to_datetime(df['fiscalDateEnding'])
            df = df.sort_values('fiscalDateEnding', ascending=False)

        return df

    except Exception as e:
        raise Exception(f"Failed to fetch income statement for {symbol}: {str(e)}")


def fetch_balance_sheet(symbol: str, quarterly: bool = False) -> pd.DataFrame:
    """Fetch balance sheet data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        quarterly: If True, fetch quarterly data; otherwise annual

    Returns:
        DataFrame with balance sheet data including:
        - fiscalDateEnding, totalAssets, totalLiabilities, totalShareholderEquity

    Raises:
        Exception: If API request fails
    """
    try:
        params = {
            "function": "BALANCE_SHEET",
            "symbol": symbol
        }
        data = _make_request(params)

        # Choose quarterly or annual reports
        key = "quarterlyReports" if quarterly else "annualReports"
        reports = data.get(key, [])
        df = pd.DataFrame(reports)

        if not df.empty:
            df['fiscalDateEnding'] = pd.to_datetime(df['fiscalDateEnding'])
            df = df.sort_values('fiscalDateEnding', ascending=False)

        return df

    except Exception as e:
        raise Exception(f"Failed to fetch balance sheet for {symbol}: {str(e)}")


def fetch_cash_flow(symbol: str, quarterly: bool = False) -> pd.DataFrame:
    """Fetch cash flow statement data.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        quarterly: If True, fetch quarterly data; otherwise annual

    Returns:
        DataFrame with cash flow data including:
        - fiscalDateEnding, operatingCashflow, capitalExpenditures, freeCashflow

    Raises:
        Exception: If API request fails
    """
    try:
        params = {
            "function": "CASH_FLOW",
            "symbol": symbol
        }
        data = _make_request(params)

        # Choose quarterly or annual reports
        key = "quarterlyReports" if quarterly else "annualReports"
        reports = data.get(key, [])
        df = pd.DataFrame(reports)

        if not df.empty:
            df['fiscalDateEnding'] = pd.to_datetime(df['fiscalDateEnding'])
            df = df.sort_values('fiscalDateEnding', ascending=False)

        return df

    except Exception as e:
        raise Exception(f"Failed to fetch cash flow for {symbol}: {str(e)}")


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
