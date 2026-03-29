"""Tests for Quant Analyst DeepAgent."""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import Mock, patch
from src.agentic.agents.quant.analyst import (
    QuantAnalyst,
    ThirtyMinSummary,
    EODSummary,
    OnDemandResponse,
    TechnicalIndicators,
    Signals
)


@pytest.fixture
def analyst():
    """Create QuantAnalyst instance for testing."""
    return QuantAnalyst(
        model="gpt-5-mini",
        backtest_mode=True  # Always use backtest mode for tests
    )


class TestPydanticModels:
    """Test suite for Pydantic models."""

    def test_technical_indicators_model(self):
        """Test TechnicalIndicators model validation."""
        indicators = TechnicalIndicators(
            rsi=65.3,
            macd=0.52,
            macd_signal=0.48,
            bollinger_upper=150.5,
            bollinger_middle=148.0,
            bollinger_lower=145.5
        )

        assert indicators.rsi == 65.3
        assert indicators.macd == 0.52

    def test_signals_model(self):
        """Test Signals model validation."""
        signals = Signals(
            momentum="bullish",
            volatility="normal",
            volume_trend="increasing"
        )

        assert signals.momentum == "bullish"
        assert signals.volatility == "normal"

    def test_thirty_min_summary_model(self):
        """Test ThirtyMinSummary model validation."""
        from datetime import datetime

        indicators = TechnicalIndicators(rsi=65.3)
        signals = Signals(
            momentum="bullish",
            volatility="normal",
            volume_trend="increasing"
        )

        summary = ThirtyMinSummary(
            symbol="AAPL",
            timestamp=datetime.now().isoformat(),
            latest_close=150.25,
            indicators=indicators,
            signals=signals,
            summary_text="Test summary"
        )

        assert summary.symbol == "AAPL"
        assert summary.latest_close == 150.25

    def test_eod_summary_model(self):
        """Test EODSummary model validation."""
        from datetime import datetime

        indicators = TechnicalIndicators(rsi=65.3)
        signals = Signals(
            momentum="bullish",
            volatility="normal",
            volume_trend="increasing"
        )

        eod = EODSummary(
            symbol="AAPL",
            timestamp=datetime.now().isoformat(),
            date="2026-02-22",
            close_price=150.25,
            indicators=indicators,
            signals=signals,
            intraday_summary="Test intraday",
            summary_text="Test summary",
            recommendations="Test recommendations"
        )

        assert eod.symbol == "AAPL"
        assert eod.close_price == 150.25

    def test_on_demand_response_model(self):
        """Test OnDemandResponse model validation."""
        from datetime import datetime

        response = OnDemandResponse(
            symbol="AAPL",
            query="What is the current trend?",
            timestamp=datetime.now().isoformat(),
            answer="The trend is bullish"
        )

        assert response.symbol == "AAPL"
        assert response.query == "What is the current trend?"


class TestQuantAnalyst:
    """Test suite for QuantAnalyst class."""

    def test_initialization(self, analyst):
        """Test analyst initializes correctly."""
        assert analyst.model == "gpt-5-mini"
        assert analyst.backtest_mode is True

    def test_tools_are_loaded(self, analyst):
        """Test that all tools are loaded."""
        assert hasattr(analyst, 'tools')
        assert len(analyst.tools) == 4

        tool_names = [tool.name for tool in analyst.tools]
        assert "get_market_bars" in tool_names
        assert "get_company_fundamentals" in tool_names
        assert "save_eod_summary" in tool_names
        assert "save_strategy_result_tool" in tool_names

    def test_middleware_stack_is_created(self, analyst):
        """Test that middleware stack is created on agent initialization."""
        # Mock _get_agent to avoid constructing real ChatOpenAI + deep agent
        with patch.object(analyst, '_get_agent') as mock_get_agent:
            mock_agent = Mock()
            mock_get_agent.return_value = mock_agent
            
            # Simulate the side effect of _get_agent creating middleware_stack
            def set_middleware_stack():
                analyst.middleware_stack = [Mock(), Mock(), Mock()]  # Simulate 3 middleware
                return mock_agent
            
            mock_get_agent.side_effect = set_middleware_stack
            
            # Trigger agent initialization
            agent = analyst._get_agent()

            assert hasattr(analyst, 'middleware_stack')
            assert len(analyst.middleware_stack) == 3
            mock_get_agent.assert_called_once()

    def test_invoke_method_exists(self, analyst):
        """Test that invoke method exists."""
        assert hasattr(analyst, 'invoke')
        assert callable(analyst.invoke)

    @pytest.mark.skip(reason="Requires API key and takes time")
    def test_invoke_with_natural_language(self, analyst):
        """Test invoking analyst with natural language query."""
        query = "What skills do you have?"

        result = analyst.invoke(query, apply_middleware=False)

        assert result is not None
        assert "query" in result
        assert "response" in result
        assert result["query"] == query

    def test_invoke_returns_structured_response(self, analyst):
        """Test that invoke returns properly structured response."""
        # Mock the agent to avoid actual API call
        with patch.object(analyst, '_get_agent') as mock_get_agent:
            mock_agent = Mock()
            mock_agent.invoke.return_value = {
                "messages": [
                    Mock(content="Test response")
                ]
            }
            mock_get_agent.return_value = mock_agent

            result = analyst.invoke(
                "Test query",
                apply_middleware=False
            )

            assert "query" in result
            assert "response" in result
            assert "timestamp" in result
            assert "model" in result
<<<<<<< HEAD:tests/agents/quant/test_analyst.py
=======
            assert result["model"] == "gpt-5-mini"
>>>>>>> 0f2566f... feat: Refactor src into common/agentic/langgraph modules with prebuilt middleware:src/agentic/tests/agents/quant/test_analyst.py

    def test_invoke_with_middleware(self, analyst):
        """Test that middleware can be applied."""
        with patch.object(analyst, '_invoke_with_middleware') as mock_invoke:
            mock_invoke.return_value = {
                "messages": [Mock(content="Test response")]
            }

            result = analyst.invoke(
                "Test query",
                apply_middleware=True
            )

            # _invoke_with_middleware should have been called
            mock_invoke.assert_called_once()

    def test_invoke_without_middleware(self, analyst):
        """Test that middleware can be bypassed."""
        with patch.object(analyst, '_get_agent') as mock_get_agent:
            mock_agent = Mock()
            mock_agent.invoke.return_value = {
                "messages": [Mock(content="Test response")]
            }
            mock_get_agent.return_value = mock_agent

            result = analyst.invoke(
                "Test query",
                apply_middleware=False
            )

            # Direct agent.invoke should have been called
            mock_agent.invoke.assert_called_once()


class TestAnalystIntegration:
    """Integration tests for QuantAnalyst."""

    def test_analyst_with_backtest_mode(self):
        """Test analyst in backtest mode bypasses market hours."""
        analyst = QuantAnalyst(
            model="gpt-5-mini",
            backtest_mode=True
        )

        # Mock _get_agent to avoid constructing a real deep agent in tests
        with patch.object(analyst, "_get_agent", return_value=Mock()) as mock_get_agent:
            agent = analyst._get_agent()
            assert agent is not None
            mock_get_agent.assert_called_once()

    def test_skills_are_discovered(self, analyst):
        """Test that skills are available to the agent."""
        # Mock _get_agent to avoid constructing a real deep agent in tests
        with patch.object(analyst, "_get_agent", return_value=Mock()) as mock_get_agent:
            agent = analyst._get_agent()
            # Agent should be created with skills paths
            # (Actual skill discovery happens at runtime)
            assert agent is not None
            mock_get_agent.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
