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
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime
from typing import Dict, List, Optional

from src.common.utils import get_logger

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver

from src.agentic.agents.base_agent import BaseAgent
from src.agentic.agents.portfolio_tools import (
    get_portfolio_status,
    get_positions_summary,
    check_portfolio_health,
    delegate_to_quant_analyst,
    delegate_to_backtester,
    fetch_historical_data,
    check_data_availability

)
from src.common.core.middleware import create_middleware_stack, create_agent_middleware, ToolTracingCallback

logger = get_logger(__name__)


class PortfolioManager(BaseAgent):
    """Portfolio Manager agent using DeepAgents framework.

    Central coordinator for portfolio management with risk enforcement
    and technical analysis delegation capabilities.
    """

    def __init__(
        self,
        model: str = "gpt-5-mini",
        backtest_mode: bool = True
    ):
        """Initialize Portfolio Manager.

        Args:
            model: LLM model to use (default: gpt-5-mini)
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
            check_data_availability,
            fetch_historical_data,
            delegate_to_quant_analyst,
            delegate_to_backtester
        ]

    def _get_agent(self):
        """Get or create Portfolio Manager deep agent.

        Returns:
            Configured DeepAgent instance
        """
        if self._agent is None:
            tools = self._create_tools()

            root_dir = Path(__file__).parent.parent.parent.parent
            skills_dir = Path(__file__).parent / "skills"
            agents_md = Path(__file__).parent / "AGENTS.MD"
            backend = FilesystemBackend(root_dir=str(root_dir))

            def _rel(path: Path) -> str:
                return path.relative_to(root_dir).as_posix()

            llm = self._create_llm()

            self.middleware_stack = create_middleware_stack(
                backtest_mode=self.backtest_mode,
                agent_type="portfolio"
            )
            agent_middleware = create_agent_middleware()

            self._agent = create_deep_agent(
                model=llm,
                tools=tools,
<<<<<<< HEAD:src/agents/portfolio/manager.py
                skills=[str(skills_dir / "portfolio-management")],
                memory=[str(Path(__file__).parent / "AGENTS.MD")],
                memory=[str(Path(__file__).parent / "AGENTS.MD")],
=======
                skills=[
                    _rel(skills_dir)],
                memory=[_rel(agents_md)],
>>>>>>> 0f2566f... feat: Refactor src into common/agentic/langgraph modules with prebuilt middleware:src/agentic/agents/portfolio/manager.py
                backend=backend,
                checkpointer=MemorySaver(),
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
        """Execute Portfolio Manager with user query.

        Args:
            query: User's portfolio management query
            thread_id: Conversation thread ID for state persistence
            apply_middleware: Whether to apply middleware stack
            previous_response_id: Previous response ID for multi-turn conversations

        Returns:
            Dict with:
                - query: Original query
                - response: Agent's response
                - response_id: Response ID for multi-turn conversations
                - timestamp: Execution timestamp
                - thread_id: Thread identifier
                - model: Model used
                - tool_timings: Performance data (if available)
        """
        logger.info(f"Processing query: {query}")
        start_time = datetime.now()

        # Reset tool timings for this interaction
        self._callback.reset()

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
                last_message = messages[-1]
                response_text = getattr(last_message, "content", str(last_message))

                response_id = self._extract_response_id(last_message)
            else:
                response_text = "No response generated"
                response_id = None

            # Get tool timings
            tool_timings = self._callback.get_tool_timings()

            result = {
                "query": query,
                "response": response_text,
                "response_id": response_id,
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
    parser.add_argument("--model", type=str, default="gpt-5-mini",
                        help="Model to use")
    parser.add_argument("--no-middleware", action="store_true",
                        help="Disable middleware")
    parser.add_argument("--stream", action="store_true",
                        help="Enable streaming mode with reasoning")

    args = parser.parse_args()

    print("=" * 60)
    print("Portfolio Manager Functional Tests")
    print("=" * 60)

    # Create Portfolio Manager
    manager = PortfolioManager(model=args.model, backtest_mode=True)

    if args.stream:
        print(f"\n[STREAMING MODE] Query: {args.query}")
        print("=" * 60)

        reasoning_blocks = []
        text_blocks = []
        tool_calls = []

        for chunk in manager.stream(query=args.query, thread_id=args.thread):
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
        print("=" * 60)

    else:
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
