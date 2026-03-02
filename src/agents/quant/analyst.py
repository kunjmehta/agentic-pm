"""Quant Analyst DeepAgent implementation.

Uses Langchain deepagents framework with:
- Progressive disclosure skill discovery (Match → Read → Execute)
- StateBackend for file persistence across turns
- Custom tools for data access (fetch_recent_bars, get_fundamentals, save_eod_to_db)
- Middleware stack for guards and tracing
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import argparse
from datetime import datetime
from typing import Dict, Optional, List
from pydantic import BaseModel, Field

from src.utils import secrets, get_logger

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from src.agents.quant_tools import (
    get_market_bars,
    get_company_fundamentals,
    save_eod_summary,
    save_strategy_result_tool
)
from src.agents.middleware import create_middleware_stack, ToolTracingCallback
from src.utils import get_logger

logger = get_logger(__name__)


# ============================================================================
# Pydantic Models for Structured Outputs
# ============================================================================

class TechnicalIndicators(BaseModel):
    """Technical indicator values."""
    rsi: Optional[float] = Field(None, description="Relative Strength Index (0-100)")
    macd: Optional[float] = Field(None, description="MACD line value")
    macd_signal: Optional[float] = Field(None, description="MACD signal line value")
    macd_histogram: Optional[float] = Field(None, description="MACD histogram value")
    bollinger_upper: Optional[float] = Field(None, description="Upper Bollinger Band")
    bollinger_middle: Optional[float] = Field(None, description="Middle Bollinger Band (SMA)")
    bollinger_lower: Optional[float] = Field(None, description="Lower Bollinger Band")
    obv: Optional[float] = Field(None, description="On-Balance Volume")
    volume_trend: Optional[str] = Field(None, description="Volume trend (increasing/decreasing/stable)")
    intrinsic_value: Optional[float] = Field(None, description="Graham intrinsic value")


class Signals(BaseModel):
    """Trading signals derived from technical analysis."""
    momentum: str = Field(..., description="Momentum signal: bullish, bearish, or neutral")
    volatility: str = Field(..., description="Volatility level: high, normal, or low")
    volume_trend: str = Field(..., description="Volume trend: increasing, decreasing, or stable")
    overall_signal: Optional[str] = Field(None, description="Overall trading signal: buy, sell, or hold")


class ThirtyMinSummary(BaseModel):
    """30-minute analysis summary with structured output."""
    symbol: str = Field(..., description="Stock ticker symbol")
    timestamp: str = Field(..., description="ISO timestamp of analysis")
    latest_close: float = Field(..., description="Most recent closing price")
    indicators: TechnicalIndicators = Field(..., description="Technical indicator values")
    signals: Signals = Field(..., description="Trading signals")
    summary_text: str = Field(..., description="Human-readable analysis summary")
    thought_trace: Optional[str] = Field(None, description="Agent reasoning process")


class EODSummary(BaseModel):
    """End-of-day comprehensive analysis summary."""
    symbol: str = Field(..., description="Stock ticker symbol")
    timestamp: str = Field(..., description="ISO timestamp of analysis")
    date: str = Field(..., description="Trading date (YYYY-MM-DD)")
    open_price: Optional[float] = Field(None, description="Opening price")
    close_price: float = Field(..., description="Closing price")
    high_price: Optional[float] = Field(None, description="Day's high price")
    low_price: Optional[float] = Field(None, description="Day's low price")
    volume: Optional[int] = Field(None, description="Total trading volume")
    indicators: TechnicalIndicators = Field(..., description="Technical indicator values")
    signals: Signals = Field(..., description="Trading signals")
    intraday_summary: str = Field(..., description="Summary of intraday patterns from 30-min summaries")
    valuation_assessment: Optional[str] = Field(None, description="Fundamental valuation context")
    summary_text: str = Field(..., description="Comprehensive daily analysis")
    recommendations: str = Field(..., description="Actionable insights for portfolio manager")
    thought_trace: Optional[str] = Field(None, description="Agent reasoning process")


class OnDemandResponse(BaseModel):
    """Response to on-demand query about a symbol."""
    symbol: str = Field(..., description="Stock ticker symbol")
    query: str = Field(..., description="Original query")
    timestamp: str = Field(..., description="ISO timestamp of response")
    answer: str = Field(..., description="Detailed answer to the query")
    supporting_data: Optional[Dict] = Field(None, description="Supporting data used in analysis")
    thought_trace: Optional[str] = Field(None, description="Agent reasoning process")


class QuantAnalyst:
    """Quantitative Analyst DeepAgent for technical analysis.

    Uses progressive disclosure to discover and use indicator skills.
    Persists 30-min summaries to file system, EOD summaries to database.
    """

    def __init__(
        self,
        model: str = "openai:gpt-4",
        backtest_mode: bool = False,
    ):
        """Initialize Quant Analyst agent.

        Args:
            model: LLM model to use (format "provider:model", default "openai:gpt-4")
            backtest_mode: If True, bypass market hours checks for testing
        """
        self.model = model
        self.backtest_mode = backtest_mode

        # Create tools using @tool decorator for compatibility
        self.tools = self._create_tools()

        # Initialize agent (will be created on first use)
        self._agent = None


    def _create_tools(self) -> List:
        """Return tools imported from quant_tools module.

        All tools are centralized in quant_tools.py to avoid duplication.
        """
        return [
            get_market_bars,
            get_company_fundamentals,
            save_eod_summary,
            save_strategy_result_tool
        ]

    def _get_agent(self):
        """Get or create deep agent with middleware support.

        Note: Deepagents may not support middleware parameter directly,
        so middleware is applied at the method invocation level.
        """

        if self._agent is None:
            # Create tool tracing callback
            tool_callback = ToolTracingCallback()

            # Create LLM with callbacks
            llm = ChatOpenAI(
                model=self.model,
                temperature=0.1,
                api_key=secrets.get("openai.api_key"),
                verbose=True,
                callbacks=[tool_callback]
            )

            checkpointer = MemorySaver()

            # Create middleware stack
            self.middleware_stack = create_middleware_stack(backtest_mode=self.backtest_mode)

            # Skills organized hierarchically:
            # - Base indicators (building blocks): momentum, volatility, volume, candlestick
            # - Strategy (uses base indicators): mean-reversion
            self._agent = create_deep_agent(
                model=llm,
                backend=FilesystemBackend(root_dir="D:/Projects/agentic-trader/"),
                skills=[
                    # Base Technical Indicators (Level 1)
                    "src/agents/quant/skills/momentum-indicators",      # MACD, RSI, EMA
                    "src/agents/quant/skills/volatility-indicators",    # Bollinger Bands, ATR
                    "src/agents/quant/skills/volume-indicators",        # OBV, Volume Flow
                    "src/agents/quant/skills/candlestick-patterns",     # Pattern Recognition
                    # Trading Strategy (Level 2 - uses Level 1 indicators)
                    "src/agents/quant/skills/mean-reversion-strategy"   # Mean Reversion Strategy
                ],
                tools=self.tools,  # Add custom tools for data access
                memory=["src/agents/quant/AGENT.MD"],  # System prompt for agent
                checkpointer=checkpointer
            )

            logger.info("Deep agent created with skills discovery and middleware stack")
            logger.info(f"Middleware stack: {[m.__class__.__name__ for m in self.middleware_stack]}")

        return self._agent

    def _invoke_with_middleware(self, state: dict, config: Optional[dict] = None) -> dict:
        """Invoke agent with middleware hooks applied.

        Applies middleware in order: before_agent → invoke → after_agent

        Args:
            state: Agent input state with messages
            config: Optional LangGraph config

        Returns:
            Agent output state
        """
        agent = self._get_agent()

        # Apply before_agent hooks
        for middleware in self.middleware_stack:
            if hasattr(middleware, 'before_agent'):
                result = middleware.before_agent(state, None)
                if result is not None:
                    state = result

        # Invoke agent
        try:
            # Apply before_model hooks
            for middleware in self.middleware_stack:
                if hasattr(middleware, 'before_model'):
                    middleware.before_model(state, None)

            # Execute agent
            if config:
                output = agent.invoke(state, config=config)
            else:
                output = agent.invoke(state)

            # Apply after_model hooks
            for middleware in self.middleware_stack:
                if hasattr(middleware, 'after_model'):
                    middleware.after_model(output, None)

            # Apply after_agent hooks
            for middleware in self.middleware_stack:
                if hasattr(middleware, 'after_agent'):
                    middleware.after_agent(output, None)

            return output

        except Exception as e:
            # Apply error hooks
            for middleware in self.middleware_stack:
                if hasattr(middleware, 'on_error'):
                    middleware.on_error(state, None, e)
            raise

    def invoke(self, query: str, apply_middleware: bool = True) -> Dict:
        """Invoke agent with natural language query.

        The agent interprets the query and determines:
        - Which symbol(s) to analyze
        - What type of analysis to perform
        - Which tools and skills to use
        - What parameters to pass

        Args:
            query: Natural language query (e.g., "Run mean reversion strategy on AAPL")
            apply_middleware: Whether to apply middleware stack (default True)

        Returns:
            Dict with agent response and metadata
        """
        logger.info(f"Processing query: {query}")

        now = datetime.now()

        # Run agent with or without middleware
        if apply_middleware:
            result = self._invoke_with_middleware({
                "messages": [{"role": "user", "content": query}]
            },
            config={"configurable": {"thread_id": "12345"}})
        else:
            agent = self._get_agent()
            result = agent.invoke({
                "messages": [{"role": "user", "content": query}]
            })

        # Extract response
        messages = result.get("messages", [])
        final_message = messages[-1] if messages else None
        output = final_message.content if final_message else "No response generated"

        response = {
            "query": query,
            "response": output,
            "timestamp": now.isoformat(),
            "model": self.model,
            "messages": messages
        }

        logger.info(f"Query processed successfully")
        return response


if __name__ == "__main__":
    """Test Quant Analyst agent with natural language queries."""
    parser = argparse.ArgumentParser(description='Quant Analyst DeepAgent - Natural Language Interface')
    parser.add_argument(
        '--query',
        type=str,
        default='Run mean reversion strategy on AAPL',
        help='Natural language query'
    )
    parser.add_argument('--model', type=str, default='gpt-4o-mini', help='LLM model to use')
    parser.add_argument('--backtest', action='store_true', help='Enable backtest mode (bypass market hours)')
    parser.add_argument('--no-middleware', action='store_true', help='Disable middleware (for testing)')

    args = parser.parse_args()

    # Create analyst
    analyst = QuantAnalyst(
        model=args.model,
        backtest_mode=args.backtest or True  # Default to True for testing
    )

    try:
        print("="*60)
        print(f"Query: {args.query}")
        print("="*60)

        # Invoke agent with natural language
        result = analyst.invoke(
            query=args.query,
            apply_middleware=not args.no_middleware
        )

        print(f"\nResponse:\n{result['response']}")

        print("\n" + "="*60)
        print("Query processed successfully!")
        print("="*60)

    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        print(f"\nError: {e}")
        sys.exit(1)
