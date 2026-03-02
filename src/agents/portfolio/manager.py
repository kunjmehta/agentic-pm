"""Portfolio Manager DeepAgent implementation.

Module 8: Central coordinator for portfolio management with:
- Progressive disclosure skill discovery (Match → Read → Execute)
- StateBackend for file persistence across turns
- Portfolio tools for account status, positions, health, delegation
- Middleware stack with Portfolio Guard for risk enforcement
- State inspection for debugging (Improvement #12)
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import json
from datetime import datetime
from typing import Dict, Optional

from src.utils import secrets, get_logger

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI

from src.agents.portfolio_tools import (
    get_portfolio_status,
    get_positions_summary,
    check_portfolio_health,
    delegate_to_quant_analyst,
<<<<<<< HEAD
    delegate_to_backtester,
    fetch_historical_data,
    check_data_availability
=======
    delegate_to_backtester
>>>>>>> feat: Phase 4 - Backtester Agent Implementation
)
from src.core.middleware import create_middleware_stack, ToolTracingCallback

logger = get_logger(__name__)


class PortfolioManager:
    """Portfolio Manager agent using DeepAgents framework.

    Central coordinator for portfolio management with risk enforcement
    and technical analysis delegation capabilities.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        backtest_mode: bool = True
    ):
        """Initialize Portfolio Manager.

        Args:
            model: LLM model to use (default: gpt-4o-mini)
            backtest_mode: Bypass market hours and portfolio guards if True
        """
        self.model = model
        self.backtest_mode = backtest_mode
        self._agent = None
        self._callback = ToolTracingCallback()

        logger.info(f"Portfolio Manager initialized (model={model}, backtest={backtest_mode})")

    def _create_tools(self):
        """Create tool list for Portfolio Manager.

        Returns:
            List of LangChain tools
        """
        return [
            get_portfolio_status,
            get_positions_summary,
            check_portfolio_health,
<<<<<<< HEAD
            check_data_availability,
            fetch_historical_data,
=======
>>>>>>> feat: Phase 4 - Backtester Agent Implementation
            delegate_to_quant_analyst,
            delegate_to_backtester
        ]

    def _get_agent(self):
        """Get or create Portfolio Manager deep agent.

        Returns:
            Configured DeepAgent instance
        """
        if self._agent is None:
            # Get OpenAI API key
            openai_key = secrets.get("openai.api_key")

            # Create model with callback
            llm = ChatOpenAI(
                model=self.model,
                api_key=openai_key,
                callbacks=[self._callback]
            )

            # Create tools
            tools = self._create_tools()

            # Skills directory
            skills_dir = Path(__file__).parent / "skills"

            # Backend for file persistence
            backend = FilesystemBackend(root_dir="data/portfolio_state")

            # Create deep agent with skills discovery
            self._agent = create_deep_agent(
                model=llm,
                tools=tools,
                skills=[str(skills_dir / "portfolio-management")],
                memory=[str(Path(__file__).parent / "AGENTS.MD")],
                backend=backend,
                checkpointer=MemorySaver()
            )

            logger.info("Deep agent created with skills discovery and middleware stack")

        return self._agent

    def _invoke_with_middleware(
        self,
        state: dict,
        config: dict
    ) -> dict:
        """Invoke agent with middleware stack.

        Args:
            state: Agent state with messages
            config: Configuration with thread_id

        Returns:
            Agent output dict
        """
        agent = self._get_agent()

        # Create middleware stack for portfolio agent
        middleware_stack = create_middleware_stack(
            backtest_mode=self.backtest_mode,
            agent_type="portfolio"
        )

        logger.info(f"Middleware stack: {[m.__class__.__name__ for m in middleware_stack]}")

        # Apply before_agent hooks
        for middleware in middleware_stack:
            if hasattr(middleware, "before_agent"):
                try:
                    middleware.before_agent(state, None)
                except Exception as e:
                    logger.error(f"Middleware {middleware.__class__.__name__} blocked execution: {e}")
                    raise

        # Invoke agent
        try:
            output = agent.invoke(state, config=config)
            logger.info("Agent execution completed successfully")
            return output
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            raise

    def invoke(
        self,
        query: str,
        thread_id: str = "default",
        apply_middleware: bool = True
    ) -> Dict:
        """Execute Portfolio Manager with user query.

        Args:
            query: User's portfolio management query
            thread_id: Conversation thread ID for state persistence
            apply_middleware: Whether to apply middleware stack

        Returns:
            Dict with:
                - query: Original query
                - response: Agent's response
                - timestamp: Execution timestamp
                - thread_id: Thread identifier
                - model: Model used
                - tool_timings: Performance data (if available)
        """
        logger.info(f"Processing query: {query}")
        start_time = datetime.now()

        # Reset tool timings for this interaction
        self._callback.reset()

        # Create state
        state = {
            "messages": [{"role": "user", "content": query}]
        }

        # Create config with thread_id
        config = {
            "configurable": {"thread_id": thread_id}
        }

        try:
            if apply_middleware:
                output = self._invoke_with_middleware(state, config)
            else:
                agent = self._get_agent()
                output = agent.invoke(state, config=config)

            # Extract response
            messages = output.get("messages", [])
            if messages:
                last_message = messages[-1]
                response_text = getattr(last_message, "content", str(last_message))
            else:
                response_text = "No response generated"

            # Get tool timings
            tool_timings = self._callback.get_tool_timings()

            result = {
                "query": query,
                "response": response_text,
                "timestamp": datetime.now().isoformat(),
                "thread_id": thread_id,
                "model": self.model,
                "execution_time_ms": int((datetime.now() - start_time).total_seconds() * 1000),
                "tool_timings": tool_timings if tool_timings else None
            }

            logger.info(f"Query processed successfully in {result['execution_time_ms']}ms")
            return result

        except Exception as e:
            logger.error(f"Query processing failed: {e}", exc_info=True)
            return {
                "query": query,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                "thread_id": thread_id,
                "model": self.model
            }

    def get_state(self, thread_id: str) -> Dict:
        """Get agent's internal state for debugging (Improvement #12).

        Args:
            thread_id: Thread ID to inspect

        Returns:
            Dict with conversation history, tool calls, and memory
        """
        agent = self._get_agent()
        checkpointer = agent.checkpointer

        # Get state from LangGraph checkpointer
        config = {"configurable": {"thread_id": thread_id}}

        try:
            state = checkpointer.get(config)

            if state:
                messages = state.get("messages", [])
                return {
                    "thread_id": thread_id,
                    "messages": [str(m) for m in messages],
                    "message_count": len(messages),
                    "last_updated": state.get("updated_at"),
                    "tool_calls": [
                        str(m) for m in messages
                        if hasattr(m, "tool_calls") and m.tool_calls
                    ]
                }
            else:
                return {
                    "thread_id": thread_id,
                    "error": "No state found for this thread"
                }

        except Exception as e:
            logger.error(f"Failed to retrieve state: {e}")
            return {
                "thread_id": thread_id,
                "error": str(e)
            }


# =============================================================================
# Main Block for Functional Testing
# =============================================================================

if __name__ == "__main__":
    """Functional tests for Portfolio Manager."""
    import argparse

    parser = argparse.ArgumentParser(description="Test Portfolio Manager")
    parser.add_argument("--query", type=str, default="What's my portfolio status?",
                        help="Query to test")
    parser.add_argument("--thread", type=str, default="test-thread-001",
                        help="Thread ID")
    parser.add_argument("--model", type=str, default="gpt-4o-mini",
                        help="Model to use")
    parser.add_argument("--no-middleware", action="store_true",
                        help="Disable middleware")

    args = parser.parse_args()

    print("=" * 60)
    print("Portfolio Manager Functional Tests")
    print("=" * 60)

    # Create Portfolio Manager
    manager = PortfolioManager(model=args.model, backtest_mode=True)

    # Test 1: Basic query
    print(f"\n[TEST 1] Query: {args.query}")
    print("-" * 60)

    result = manager.invoke(
        query=args.query,
        thread_id=args.thread,
        apply_middleware=not args.no_middleware
    )

    if "error" in result:
        print(f"[FAIL] {result['error']}")
    else:
        print(f"[OK] Response received in {result['execution_time_ms']}ms")
        print(f"\nResponse:\n{result['response']}")

        if result.get('tool_timings'):
            print(f"\nTool Timings:")
            for timing in result['tool_timings']:
                print(f"  - {timing['tool']}: {timing['duration_ms']}ms ({timing['status']})")

    # Test 2: State inspection
    print(f"\n[TEST 2] State Inspection for thread: {args.thread}")
    print("-" * 60)

    state = manager.get_state(args.thread)
    print(f"[OK] State retrieved:")
    print(f"  - Messages: {state.get('message_count', 0)}")
    print(f"  - Tool calls: {len(state.get('tool_calls', []))}")

    print("\n" + "=" * 60)
    print("Tests Complete")
    print("=" * 60)
