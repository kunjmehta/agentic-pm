"""Unit tests for Alpha Vantage API skills.

Tests all Alpha Vantage functions with mocked API responses.
Run with: pytest tests/test_skills/test_alpha_vantage_skills.py -v
Or standalone: python tests/test_skills/test_alpha_vantage_skills.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import pandas as pd
from unittest.mock import Mock, patch

# Import after path is set
from src.skills import alpha_vantage_skills


class TestAlphaVantageSkills:
    """Test suite for Alpha Vantage API functions."""

    @patch("src.skills.alpha_vantage_skills._make_request")
    def test_fetch_company_overview_success(self, mock_request):
        """Test successful company overview fetch."""
        # Mock API response
        mock_request.return_value = {
            "Symbol": "AAPL",
            "Name": "Apple Inc",
            "Sector": "Technology",
            "Industry": "Consumer Electronics",
            "MarketCapitalization": "3000000000000",
            "PERatio": "28.5",
            "DividendYield": "0.005",
        }

        # Execute
        result = alpha_vantage_skills.fetch_company_overview("AAPL")

        # Assert
        assert isinstance(result, dict)
        assert result["Symbol"] == "AAPL"
        assert result["Name"] == "Apple Inc"
        assert result["Sector"] == "Technology"
        mock_request.assert_called_once()

    @patch("src.skills.alpha_vantage_skills._make_request")
    def test_fetch_company_overview_error(self, mock_request):
        """Test error handling in company overview fetch."""
        mock_request.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="Failed to fetch company overview"):
            alpha_vantage_skills.fetch_company_overview("AAPL")

    @patch("src.skills.alpha_vantage_skills._make_request")
    def test_fetch_dividend_history_success(self, mock_request):
        """Test successful dividend fetch."""
        # Mock API response
        mock_request.return_value = {
            "data": [
                {
                    "ex_dividend_date": "2024-02-09",
                    "declaration_date": "2024-02-01",
                    "record_date": "2024-02-08",
                    "payment_date": "2024-02-16",
                    "amount": "0.24"
                },
                {
                    "ex_dividend_date": "2023-11-10",
                    "declaration_date": "2023-11-01",
                    "record_date": "2023-11-09",
                    "payment_date": "2023-11-16",
                    "amount": "0.24"
                }
            ]
        }

        # Execute
        result = alpha_vantage_skills.fetch_dividend_history("AAPL")

        # Assert
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert "symbol" in result.columns
        assert "ex_dividend_date" in result.columns
        assert "declaration_date" in result.columns
        assert "record_date" in result.columns
        assert "payment_date" in result.columns
        assert "amount" in result.columns
        assert result.iloc[0]["amount"] == 0.24
        assert result.iloc[0]["symbol"] == "AAPL"

    @patch("src.skills.alpha_vantage_skills._make_request")
    def test_fetch_dividend_history_empty(self, mock_request):
        """Test dividend fetch with no dividends."""
        mock_request.return_value = {"data": []}

        result = alpha_vantage_skills.fetch_dividend_history("AAPL")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    @patch("src.skills.alpha_vantage_skills._make_request")
    def test_fetch_earnings_history_success(self, mock_request):
        """Test successful earnings fetch."""
        # Mock API response
        mock_request.return_value = {
            "quarterlyEarnings": [
                {
                    "fiscalDateEnding": "2024-03-31",
                    "reportedEPS": "1.52",
                    "estimatedEPS": "1.50",
                    "surprise": "0.02",
                    "surprisePercentage": "1.33"
                },
                {
                    "fiscalDateEnding": "2023-12-31",
                    "reportedEPS": "2.18",
                    "estimatedEPS": "2.10"
                }
            ]
        }

        # Execute
        result = alpha_vantage_skills.fetch_earnings_history("AAPL")

        # Assert
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert "reportedEPS" in result.columns

    @patch("src.skills.alpha_vantage_skills._make_request")
    def test_fetch_income_statement_annual(self, mock_request):
        """Test annual income statement fetch."""
        # Mock API response
        mock_request.return_value = {
            "annualReports": [
                {
                    "fiscalDateEnding": "2023-12-31",
                    "totalRevenue": "383000000000",
                    "grossProfit": "170000000000",
                    "operatingIncome": "114000000000",
                    "netIncome": "97000000000",
                    "eps": "6.13"
                }
            ]
        }

        # Execute
        result = alpha_vantage_skills.fetch_income_statement("AAPL", quarterly=False)

        # Assert
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert "symbol" in result.columns
        assert "fiscal_date_ending" in result.columns
        assert "total_revenue" in result.columns
        assert "gross_profit" in result.columns
        assert "operating_income" in result.columns
        assert "net_income" in result.columns
        assert "eps" in result.columns
        assert "full_data" in result.columns
        assert result.iloc[0]["symbol"] == "AAPL"
        assert result.iloc[0]["total_revenue"] == 383000000000

    @patch("src.skills.alpha_vantage_skills._make_request")
    def test_fetch_income_statement_quarterly(self, mock_request):
        """Test quarterly income statement fetch."""
        # Mock API response
        mock_request.return_value = {
            "quarterlyReports": [
                {
                    "fiscalDateEnding": "2024-03-31",
                    "totalRevenue": "90000000000",
                    "netIncome": "23000000000"
                }
            ]
        }

        # Execute
        result = alpha_vantage_skills.fetch_income_statement("AAPL", quarterly=True)

        # Assert
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    @patch("src.skills.alpha_vantage_skills._make_request")
    def test_fetch_balance_sheet(self, mock_request):
        """Test balance sheet fetch."""
        # Mock API response
        mock_request.return_value = {
            "annualReports": [
                {
                    "fiscalDateEnding": "2023-12-31",
                    "totalAssets": "350000000000",
                    "totalLiabilities": "250000000000",
                    "totalShareholderEquity": "100000000000"
                }
            ]
        }

        # Execute
        result = alpha_vantage_skills.fetch_balance_sheet("AAPL")

        # Assert
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert "symbol" in result.columns
        assert "fiscal_date_ending" in result.columns
        assert "total_assets" in result.columns
        assert "total_liabilities" in result.columns
        assert "total_shareholder_equity" in result.columns
        assert "full_data" in result.columns
        assert result.iloc[0]["symbol"] == "AAPL"
        assert result.iloc[0]["total_assets"] == 350000000000

    @patch("src.skills.alpha_vantage_skills._make_request")
    def test_fetch_cash_flow(self, mock_request):
        """Test cash flow fetch."""
        # Mock API response
        mock_request.return_value = {
            "annualReports": [
                {
                    "fiscalDateEnding": "2023-12-31",
                    "operatingCashflow": "110000000000",
                    "capitalExpenditures": "-11000000000",
                    "freeCashflow": "99000000000"
                }
            ]
        }

        # Execute
        result = alpha_vantage_skills.fetch_cash_flow("AAPL")

        # Assert
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert "symbol" in result.columns
        assert "fiscal_date_ending" in result.columns
        assert "operating_cashflow" in result.columns
        assert "capital_expenditures" in result.columns
        assert "free_cashflow" in result.columns
        assert "full_data" in result.columns
        assert result.iloc[0]["symbol"] == "AAPL"
        assert result.iloc[0]["operating_cashflow"] == 110000000000

    @patch("src.skills.alpha_vantage_skills.fetch_company_overview")
    @patch("src.skills.alpha_vantage_skills.fetch_dividend_history")
    @patch("src.skills.alpha_vantage_skills.fetch_earnings_history")
    @patch("src.skills.alpha_vantage_skills.fetch_income_statement")
    @patch("src.skills.alpha_vantage_skills.fetch_balance_sheet")
    @patch("src.skills.alpha_vantage_skills.fetch_cash_flow")
    def test_fetch_all_success(
        self,
        mock_cash_flow,
        mock_balance_sheet,
        mock_income,
        mock_earnings,
        mock_dividends,
        mock_overview
    ):
        """Test fetch_all returns all data."""
        # Setup mocks with new schema
        mock_overview.return_value = {"Symbol": "AAPL", "Name": "Apple Inc"}
        mock_dividends.return_value = pd.DataFrame([{
            "symbol": "AAPL",
            "ex_dividend_date": "2024-01-01",
            "amount": 0.24
        }])
        mock_earnings.return_value = pd.DataFrame([{
            "symbol": "AAPL",
            "fiscalDateEnding": "2024-03-31"
        }])
        mock_income.return_value = pd.DataFrame([{
            "symbol": "AAPL",
            "total_revenue": 90000000000
        }])
        mock_balance_sheet.return_value = pd.DataFrame([{
            "symbol": "AAPL",
            "total_assets": 350000000000
        }])
        mock_cash_flow.return_value = pd.DataFrame([{
            "symbol": "AAPL",
            "operating_cashflow": 110000000000
        }])

        # Execute
        result = alpha_vantage_skills.fetch_all("AAPL")

        # Assert
        assert result["symbol"] == "AAPL"
        assert result["overview"] is not None
        assert result["dividends"] is not None
        assert result["earnings"] is not None
        assert result["income_statement"] is not None
        assert result["balance_sheet"] is not None
        assert result["cash_flow"] is not None
        assert len(result["errors"]) == 0

    @patch("src.skills.alpha_vantage_skills.fetch_company_overview")
    @patch("src.skills.alpha_vantage_skills.fetch_dividend_history")
    @patch("src.skills.alpha_vantage_skills.fetch_earnings_history")
    @patch("src.skills.alpha_vantage_skills.fetch_income_statement")
    @patch("src.skills.alpha_vantage_skills.fetch_balance_sheet")
    @patch("src.skills.alpha_vantage_skills.fetch_cash_flow")
    def test_fetch_all_with_errors(
        self,
        mock_cash_flow,
        mock_balance_sheet,
        mock_income,
        mock_earnings,
        mock_dividends,
        mock_overview
    ):
        """Test fetch_all handles partial failures gracefully."""
        # Setup mocks with some failures and new schema
        mock_overview.return_value = {"Symbol": "AAPL"}
        mock_dividends.side_effect = Exception("Dividend API failed")
        mock_earnings.return_value = pd.DataFrame([{
            "symbol": "AAPL",
            "fiscalDateEnding": "2024-03-31"
        }])
        mock_income.side_effect = Exception("Income API failed")
        mock_balance_sheet.return_value = pd.DataFrame([{
            "symbol": "AAPL",
            "total_assets": 350000000000
        }])
        mock_cash_flow.return_value = pd.DataFrame([{
            "symbol": "AAPL",
            "operating_cashflow": 110000000000
        }])

        # Execute
        result = alpha_vantage_skills.fetch_all("AAPL")

        # Assert
        assert result["symbol"] == "AAPL"
        assert result["overview"] is not None
        assert result["dividends"] is None  # Failed
        assert result["earnings"] is not None
        assert result["income_statement"] is None  # Failed
        assert result["balance_sheet"] is not None
        assert result["cash_flow"] is not None
        assert "dividends" in result["errors"]
        assert "income_statement" in result["errors"]


class TestMakeRequest:
    """Test the internal _make_request function."""

    @patch("src.skills.alpha_vantage_skills.requests.get")
    def test_make_request_success(self, mock_get):
        """Test successful API request."""
        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {"Symbol": "AAPL", "Name": "Apple Inc"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Execute
        result = alpha_vantage_skills._make_request({"function": "OVERVIEW", "symbol": "AAPL"})

        # Assert
        assert result["Symbol"] == "AAPL"
        mock_get.assert_called_once()

    @patch("src.skills.alpha_vantage_skills.requests.get")
    def test_make_request_api_error(self, mock_get):
        """Test API returns error message."""
        # Mock error response
        mock_response = Mock()
        mock_response.json.return_value = {"Error Message": "Invalid API call"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Execute and assert
        with pytest.raises(Exception, match="API Error: Invalid API call"):
            alpha_vantage_skills._make_request({"function": "OVERVIEW", "symbol": "INVALID"})

    @patch("src.skills.alpha_vantage_skills.requests.get")
    def test_make_request_rate_limit(self, mock_get):
        """Test API rate limit response."""
        # Mock rate limit response
        mock_response = Mock()
        mock_response.json.return_value = {
            "Note": "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute."
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Execute and assert
        with pytest.raises(Exception, match="API Rate Limit"):
            alpha_vantage_skills._make_request({"function": "OVERVIEW", "symbol": "AAPL"})

    @patch("src.skills.alpha_vantage_skills.requests.get")
    def test_make_request_rate_limit_information(self, mock_get):
        """Test API rate limit response with Information key."""
        # Mock rate limit response with Information key
        mock_response = Mock()
        mock_response.json.return_value = {
            "Information": "Thank you for using Alpha Vantage! Please consider spreading out your free API requests more sparingly (1 request per second)."
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Execute and assert
        with pytest.raises(Exception, match="API Rate Limit"):
            alpha_vantage_skills._make_request({"function": "OVERVIEW", "symbol": "AAPL"})


def run_standalone_tests():
    """Run tests without pytest for standalone execution."""
    print("=" * 60)
    print("Running Alpha Vantage Skills Tests (Standalone Mode)")
    print("=" * 60)

    test_suite = TestAlphaVantageSkills()
    request_tests = TestMakeRequest()

    tests = [
        ("Company Overview - Success", test_suite.test_fetch_company_overview_success),
        ("Company Overview - Error", test_suite.test_fetch_company_overview_error),
        ("Dividend History - Success", test_suite.test_fetch_dividend_history_success),
        ("Dividend History - Empty", test_suite.test_fetch_dividend_history_empty),
        ("Earnings History - Success", test_suite.test_fetch_earnings_history_success),
        ("Income Statement - Annual", test_suite.test_fetch_income_statement_annual),
        ("Income Statement - Quarterly", test_suite.test_fetch_income_statement_quarterly),
        ("Balance Sheet", test_suite.test_fetch_balance_sheet),
        ("Cash Flow", test_suite.test_fetch_cash_flow),
        ("Fetch All - Success", test_suite.test_fetch_all_success),
        ("Fetch All - With Errors", test_suite.test_fetch_all_with_errors),
        ("Make Request - Success", request_tests.test_make_request_success),
        ("Make Request - API Error", request_tests.test_make_request_api_error),
        ("Make Request - Rate Limit", request_tests.test_make_request_rate_limit),
        ("Make Request - Rate Limit (Information)", request_tests.test_make_request_rate_limit_information),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            test_func()
            print(f"[OK] {test_name}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test_name}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Tests Passed: {passed}/{len(tests)}")
    print(f"Tests Failed: {failed}/{len(tests)}")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    """Run tests directly or with pytest."""
    if len(sys.argv) > 1 and sys.argv[1] == "--pytest":
        # Run with pytest
        sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
    else:
        # Run standalone
        success = run_standalone_tests()
        sys.exit(0 if success else 1)
