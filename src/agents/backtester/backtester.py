"""Backtester DeepAgent implementation.

Post-market simulation agent for validating trading strategies against historical data.
Uses deepagents framework with progressive disclosure skill discovery.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import argparse
from datetime import datetime
from typing import Dict, Optional, List

from src.utils import secrets, get_logger

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI

from src.agents.backtester_tools import (
    fetch_backtest_run,
    fetch_backtest_trades,
    fetch_backtest_performance_history,
    fetch_historical_bars_for_backtest,
    save_backtest_run_to_db
)
from src.core.middleware import create_middleware_stack, ToolTracingCallback

logger = get_logger(__name__)


class Backtester:
    """Backtester DeepAgent for post-market simulations.

    Powered by gpt-4o-mini for cost-effective strategy validation.
    """

    def __init__(self, model: str = "gpt-4o-mini", backtest_mode: bool = True):
        """Initialize Backtester agent.

        Args:
            model: LLM model (default: gpt-4o-mini for cost efficiency)
            backtest_mode: Always True (simulations don't need market hours checks)
        """
        self.model = model
        self.backtest_mode = backtest_mode  # Always True for backtester
        self.tools = self._create_tools()
        self._agent = None

    def _create_tools(self) -> List:
        """Return data access tools.

        Returns:
            List of 5 tools for fetching/saving backtest data
        """
        return [
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
            tool_callback = ToolTracingCallback()

            llm = ChatOpenAI(
                model=self.model,
                temperature=0.1,
                api_key=secrets.get("openai.api_key"),
                verbose=True,
                callbacks=[tool_callback]
            )

            checkpointer = MemorySaver()

            # Create middleware (backtest_mode=True bypasses guards)
            self.middleware_stack = create_middleware_stack(
                backtest_mode=True,
                agent_type="backtester"
            )

            self._agent = create_deep_agent(
                model=llm,
                backend=FilesystemBackend(root_dir="D:/Projects/agentic-trader/"),
                skills=[
                    "src/agents/backtester/skills/simulation-engine",
                    "src/agents/backtester/skills/performance-metrics",
                    "src/agents/backtester/skills/backtest-orchestration"
                ],
                tools=self.tools,
                memory=["src/agents/backtester/AGENTS.MD"],
                checkpointer=checkpointer
            )

            logger.info("Backtester agent created")

        return self._agent

    def _invoke_with_middleware(self, state: dict, config: dict) -> dict:
        """Invoke agent with middleware hooks.

        Args:
            state: Input state with messages
            config: Configuration with thread_id

        Returns:
            Output state with response
        """
        agent = self._get_agent()

        # Apply before_agent hooks
        for middleware in self.middleware_stack:
            if hasattr(middleware, "before_agent"):
                try:
                    result = middleware.before_agent(state, None)
                    if result is not None:
                        state = result
                except Exception as e:
                    logger.error(f"Middleware {middleware.__class__.__name__} blocked execution: {e}")
                    raise

        # Invoke agent
        try:
            output = agent.invoke(state, config=config)

            # Apply after_agent hooks
            for middleware in self.middleware_stack:
                if hasattr(middleware, "after_agent"):
                    middleware.after_agent(output, None)

            return output

        except Exception as e:
            logger.error(f"Agent invocation failed: {e}")
            # Apply error hooks
            for middleware in self.middleware_stack:
                if hasattr(middleware, "on_error"):
                    middleware.on_error(e, None)
            raise

    def invoke(
        self,
        query: str,
        thread_id: str = "default",
        apply_middleware: bool = True
    ) -> Dict:
        """Execute backtester with natural language query.

        Args:
            query: Natural language backtest query
                   (e.g., "Backtest mean-reversion on AAPL from Jan 2024")
            thread_id: Thread ID for context preservation
            apply_middleware: Whether to apply middleware stack

        Returns:
            Dict with query, response, timestamp, and metadata
        """
        logger.info(f"Backtester query: {query}")

        state = {"messages": [{"role": "user", "content": query}]}
        config = {"configurable": {"thread_id": thread_id}}

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
            else:
                response_text = "No response generated"

            result = {
                "query": query,
                "response": response_text,
                "timestamp": datetime.now().isoformat(),
                "thread_id": thread_id,
                "model": self.model,
                "messages": messages
            }

            logger.info(f"Backtester completed successfully")
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
        default='gpt-4o-mini',
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

    args = parser.parse_args()

    print("=" * 60)
    print("Backtester Agent - Functional Test")
    print("=" * 60)
    print(f"\nQuery: {args.query}")
    print(f"Model: {args.model}")
    print(f"Thread: {args.thread_id}")
    print("-" * 60)

    # Create and invoke backtester
    backtester = Backtester(model=args.model)

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
