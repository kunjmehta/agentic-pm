"""Backtester DeepAgent implementation.

Post-market simulation agent for validating trading strategies against historical data.
Uses deepagents framework with progressive disclosure skill discovery.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
from datetime import datetime
from typing import Dict, Optional, List

from src.common.utils import get_logger

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver

from src.agentic.agents.base_agent import BaseAgent
from src.agentic.agents.backtester_tools import (
    fetch_backtest_run,
    fetch_backtest_trades,
    fetch_backtest_performance_history,
    fetch_historical_bars_for_backtest,
    save_backtest_run_to_db,
    run_strategy_comparison
)
from src.common.core.middleware import create_middleware_stack, create_agent_middleware

logger = get_logger(__name__)


class Backtester(BaseAgent):
    """Backtester DeepAgent for post-market simulations.

    Powered by gpt-5-mini for cost-effective strategy validation.
    """

    def __init__(
        self,
        model: str = "gpt-5-mini",
        backtest_mode: bool = True,
        enable_loop_prevention: bool = True,
        max_iterations_per_tool: int = 2,
        streaming: bool = True
    ):
        """Initialize Backtester agent.

        Args:
            model: LLM model (default: gpt-5-mini for cost efficiency)
            backtest_mode: Always True (simulations don't need market hours checks)
            enable_loop_prevention: Enable loop detection (default: True)
            max_iterations_per_tool: Max times a tool can be called (default: 2)
            streaming: Enable thought streaming (default: True)
        """
        self.model = model
        self.backtest_mode = backtest_mode  # Always True for backtester
        self.enable_loop_prevention = enable_loop_prevention
        self.max_iterations_per_tool = max_iterations_per_tool
        self.streaming = streaming
        self.tools = self._create_tools()
        self._agent = None

    def _create_tools(self) -> List:
        """Return data access tools.

        Returns:
            List of 5 tools for fetching/saving backtest data
        """
        return [
            run_strategy_comparison,         # Batch: compare multiple strategies in parallel
            fetch_backtest_run,
            fetch_backtest_trades,
            fetch_backtest_performance_history,
            fetch_historical_bars_for_backtest,
            save_backtest_run_to_db
        ]

    def _get_agent(self):
        """Get or create backtester deep agent.

        Returns:
            Deep agent with skills, tools, and middleware
        """
        if self._agent is None:
            llm = self._create_llm()
            checkpointer = MemorySaver()

            self.middleware_stack = create_middleware_stack(
                backtest_mode=True,
                agent_type="backtester",
            )
            agent_middleware = create_agent_middleware()

            root_dir = Path(__file__).parent.parent.parent.parent

            self._agent = create_deep_agent(
                model=llm,
                backend=FilesystemBackend(root_dir=str(root_dir)),
                skills=[
                    "src/agentic/agents/backtester/skills/"
                ],
                tools=self.tools,
                memory=["src/agentic/agents/backtester/AGENTS.MD"],
                checkpointer=checkpointer,
                middleware=agent_middleware,
            )

            logger.info("Backtester agent created")

        return self._agent

    def invoke(
        self,
        query: str,
        thread_id: str = "default",
        apply_middleware: bool = True,
        previous_response_id: Optional[str] = None
    ) -> Dict:
        """Execute backtester with natural language query.

        Args:
            query: Natural language backtest query
                   (e.g., "Backtest mean-reversion on AAPL from Jan 2024")
            thread_id: Thread ID for context preservation
            apply_middleware: Whether to apply middleware stack
            previous_response_id: Previous response ID for multi-turn conversations

        Returns:
            Dict with query, response, timestamp, metadata, and response_id
        """
        logger.info(f"Backtester query: {query}")
        if previous_response_id:
            logger.info(f"Continuing conversation from response: {previous_response_id}")

        state = self._build_state(query)
        config = self._build_config(thread_id, previous_response_id)

        try:
            if apply_middleware:
                output = self._invoke_with_middleware(state, config)
            else:
                agent = self._get_agent()
                output = agent.invoke(state, config=config)

            # Extract response
            messages = output.get("messages", [])
            if messages:
                final_message = messages[-1]
                response_text = getattr(final_message, "content", str(final_message))

                response_id = self._extract_response_id(final_message)
            else:
                response_text = "No response generated"
                response_id = None

            result = {
                "query": query,
                "response": response_text,
                "response_id": response_id,  # For multi-turn conversations
                "timestamp": datetime.now().isoformat(),
                "thread_id": thread_id,
                "model": self.model,
                "messages": messages
            }

            logger.info(f"Backtester completed successfully")
            if response_id:
                logger.info(f"Response ID: {response_id}")
            return result

        except Exception as e:
            logger.error(f"Backtester query failed: {e}")
            return {
                "query": query,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                "thread_id": thread_id,
                "model": self.model
            }


# =============================================================================
# Functional Testing Entry Point
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Backtester Agent - Historical Strategy Simulation')
    parser.add_argument(
        '--query',
        type=str,
        default='Backtest mean-reversion strategy on AAPL',
        help='Natural language backtest query'
    )
    parser.add_argument(
        '--model',
        type=str,
        default='gpt-5-mini',
        help='LLM model to use'
    )
    parser.add_argument(
        '--thread-id',
        type=str,
        default='backtest-test-001',
        help='Thread ID for conversation'
    )
    parser.add_argument(
        '--no-middleware',
        action='store_true',
        help='Disable middleware'
    )
    parser.add_argument(
        '--stream',
        action='store_true',
        help='Enable streaming mode with reasoning'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Backtester Agent - Functional Test")
    print("=" * 60)
    print(f"\nQuery: {args.query}")
    print(f"Model: {args.model}")
    print(f"Thread: {args.thread_id}")
    print(f"Streaming: {args.stream}")
    print("-" * 60)

    # Create backtester
    backtester = Backtester(model=args.model)

    if args.stream:
        # Streaming mode
        print("\n[STREAMING MODE]")
        print("=" * 60)

        reasoning_blocks = []
        text_blocks = []
        tool_calls = []

        for chunk in backtester.stream(
            query=args.query,
            thread_id=args.thread_id,
            stream_mode=["updates", "messages"]
        ):
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

        # Print summary
        print("\n" + "=" * 60)
        print("STREAMING SUMMARY")
        print("=" * 60)
        print(f"Reasoning blocks: {len(reasoning_blocks)}")
        print(f"Text blocks: {len(text_blocks)}")
        print(f"Tool calls: {len(tool_calls)}")

        if text_blocks:
            print(f"\nFinal Response:\n{text_blocks[-1]}")

        print("\n" + "=" * 60)

    else:
        # Regular invoke mode
        result = backtester.invoke(
            query=args.query,
            thread_id=args.thread_id,
            apply_middleware=not args.no_middleware
        )

        # Display results
        if "error" not in result:
            print(f"\n[SUCCESS] Backtest completed")
            print(f"\nResponse:\n{result['response']}")
            print("\n" + "=" * 60)
        else:
            print(f"\n[ERROR] {result['error']}")
            print("=" * 60)
