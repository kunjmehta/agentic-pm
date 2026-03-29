"""Quant Analyst DeepAgent implementation.

Uses Langchain deepagents framework with:
- Progressive disclosure skill discovery (Match → Read → Execute)
- StateBackend for file persistence across turns
- Custom tools for data access (fetch_recent_bars, get_fundamentals, save_eod_to_db)
- Middleware stack for guards and tracing
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
from datetime import datetime
from typing import Dict, Optional, List
from pydantic import BaseModel, Field

from src.common.utils import get_logger

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver

from src.agentic.agents.base_agent import BaseAgent
from src.agentic.agents.quant_tools import (
    get_market_bars,
    get_precomputed_indicators,
    get_company_fundamentals,
    save_eod_summary,
    save_strategy_result_tool,
    run_quant_batch
)
from src.common.core.middleware import create_middleware_stack, create_agent_middleware

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


class QuantAnalyst(BaseAgent):
    """Quantitative Analyst DeepAgent for technical analysis.

    Uses progressive disclosure to discover and use indicator skills.
    Persists 30-min summaries to file system, EOD summaries to database.
    """

    def __init__(
        self,
        model: str = "gpt-5-mini",
        backtest_mode: bool = False,
    ):
        """Initialize Quant Analyst agent.

        Args:
            model: LLM model to use (format "provider:model", default "openai:gpt-5-mini")
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
            run_quant_batch,             # Batch: run multiple skills in one action
            get_precomputed_indicators,  # Single-pass: precomputed ETL indicators
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
            llm = self._create_llm()
            checkpointer = MemorySaver()

            # Hook-chain middleware (market hours, tracing, prettify)
            self.middleware_stack = create_middleware_stack(backtest_mode=self.backtest_mode)
            # Prebuilt LangChain middleware (model call limit, tool call limit, retry)
            agent_middleware = create_agent_middleware()

            root_dir = Path(__file__).parent.parent.parent.parent
            skills_dir = Path(__file__).parent / "skills"
            agent_md = Path(__file__).parent / "AGENT.MD"

            def _rel(path: Path) -> str:
                return path.relative_to(root_dir).as_posix()

            self._agent = create_deep_agent(
                model=llm,
                backend=FilesystemBackend(root_dir=str(root_dir)),
                skills=[
                    _rel(skills_dir)
                ],
                tools=self.tools,
                memory=[_rel(agent_md)],
                checkpointer=checkpointer,
                middleware=agent_middleware,
            )

            logger.info("Deep agent created with skills discovery and middleware stack")
            logger.info(f"Hook middleware: {[m.__class__.__name__ for m in self.middleware_stack]}")
            logger.info(f"Agent middleware: {[m.__class__.__name__ for m in agent_middleware]}")

        return self._agent

    def invoke(
        self,
        query: str,
        thread_id: str = "default",
        apply_middleware: bool = True,
        previous_response_id: Optional[str] = None
    ) -> Dict:
        """Invoke agent with natural language query.

        The agent interprets the query and determines:
        - Which symbol(s) to analyze
        - What type of analysis to perform
        - Which tools and skills to use
        - What parameters to pass

        Args:
            query: Natural language query (e.g., "Run mean reversion strategy on AAPL")
            thread_id: Conversation thread ID for state persistence
            apply_middleware: Whether to apply middleware stack (default True)
            previous_response_id: Previous response ID for multi-turn conversations

        Returns:
            Dict with query, response, response_id, timestamp, thread_id, model, messages
        """
        logger.info(f"Processing query: {query}")

        state = self._build_state(query)
        config = self._build_config(thread_id, previous_response_id)

        try:
            if apply_middleware:
                output = self._invoke_with_middleware(state, config)
            else:
                agent = self._get_agent()
                output = agent.invoke(state, config=config)

            messages = output.get("messages", [])
            if messages:
                final_message = messages[-1]
                response_text = getattr(final_message, "content", str(final_message))
                response_id = self._extract_response_id(final_message)
            else:
                response_text = "No response generated"
                response_id = None

            logger.info("Query processed successfully")
            return {
                "query": query,
                "response": response_text,
                "response_id": response_id,
                "timestamp": datetime.now().isoformat(),
                "thread_id": thread_id,
                "model": self.model,
                "messages": messages
            }

        except Exception as e:
            logger.error(f"Query processing failed: {e}", exc_info=True)
            return {
                "query": query,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                "thread_id": thread_id,
                "model": self.model
            }



if __name__ == "__main__":
    """Test Quant Analyst agent with natural language queries."""
    parser = argparse.ArgumentParser(description='Quant Analyst DeepAgent - Natural Language Interface')
    parser.add_argument(
        '--query',
        type=str,
        default='Run mean reversion strategy on AAPL',
        help='Natural language query'
    )
    parser.add_argument('--model', type=str, default='gpt-5-mini', help='LLM model to use')
    parser.add_argument('--backtest', action='store_true', help='Enable backtest mode (bypass market hours)')
    parser.add_argument('--no-middleware', action='store_true', help='Disable middleware (for testing)')
    parser.add_argument('--stream', action='store_true', help='Enable streaming mode with reasoning')

    args = parser.parse_args()

    analyst = QuantAnalyst(
        model=args.model,
        backtest_mode=args.backtest or True
    )

    print("=" * 60)
    print(f"Query: {args.query}")
    print("=" * 60)

    try:
        if args.stream:
            print("\n[STREAMING MODE]")
            reasoning_blocks, text_blocks, tool_calls = [], [], []

            for chunk in analyst.stream(query=args.query):
                chunk_type = chunk.get("type")
                if chunk_type == "reasoning":
                    reasoning_blocks.append(chunk["content"])
                    print(f"\n💭 [THOUGHT] {chunk['content'][:100]}...")
                elif chunk_type == "text":
                    text_blocks.append(chunk["content"])
                    print(f"\n📝 [OUTPUT] {chunk['content'][:100]}...")
                elif chunk_type == "tool_call":
                    tool_calls.append(chunk["content"])
                    print(f"\n🔧 [TOOL] {str(chunk['content'])[:100]}...")
                elif chunk_type == "error":
                    print(f"\n❌ [ERROR] {chunk['content']}")

            print("\n" + "=" * 60)
            print(f"Reasoning blocks: {len(reasoning_blocks)}")
            print(f"Text blocks: {len(text_blocks)}")
            print(f"Tool calls: {len(tool_calls)}")
            if text_blocks:
                print(f"\nFinal Response:\n{text_blocks[-1]}")
        else:
            result = analyst.invoke(
                query=args.query,
                apply_middleware=not args.no_middleware
            )
            print(f"\nResponse:\n{result['response']}")

        print("\n" + "=" * 60)
        print("Query processed successfully!")
        print("=" * 60)

    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        print(f"\nError: {e}")
        sys.exit(1)
