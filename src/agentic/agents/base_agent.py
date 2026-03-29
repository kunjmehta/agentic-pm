"""Base agent class with shared streaming and middleware logic.

All DeepAgent implementations inherit from BaseAgent to avoid duplication
of stream chunk parsing and middleware application patterns.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime
from typing import Iterator, Optional

from langchain_openai import ChatOpenAI

from src.common.utils import secrets, get_logger

logger = get_logger(__name__)


class BaseAgent:
    """Shared base for all DeepAgent implementations.

    Provides:
    - stream(): LangGraph chunk parsing with reasoning/text/tool_call events
    - _invoke_with_middleware(): full middleware hook chain
    - _build_state() / _build_config(): common state construction

    Subclasses must implement _get_agent() and set self.middleware_stack.
    """

    # NOTE: Do NOT use a mutable class-level default here.
    # Each subclass sets self.middleware_stack = [...] inside _get_agent().
    # _invoke_with_middleware() reads it via getattr to avoid sharing state.

    @property
    def _agent_name(self) -> str:
        """Human-readable agent name for logging."""
        return self.__class__.__name__

    def _get_agent(self):
        """Return (or lazily create) the underlying deep agent. Must be overridden."""
        raise NotImplementedError(f"{self._agent_name} must implement _get_agent()")

    def _create_llm(self) -> ChatOpenAI:
        """Create a ChatOpenAI instance with shared agent configuration.

        Requires subclass to set self.model before calling.

        Returns:
            Configured ChatOpenAI instance.
        """
        return ChatOpenAI(
            model=self.model,
            temperature=0.1,
            api_key=secrets.get("openai.api_key"),
            verbose=False,
        )

    def _build_state(self, query: str) -> dict:
        """Build initial LangGraph state from a user query.

        Args:
            query: Natural language user query.

        Returns:
            State dict with a single user message.
        """
        return {"messages": [{"role": "user", "content": query}]}

    def _build_config(self, thread_id: str, previous_response_id: Optional[str] = None) -> dict:
        """Build LangGraph run config.

        Args:
            thread_id: Conversation thread identifier.
            previous_response_id: Optional response ID for multi-turn conversations.

        Returns:
            Config dict with thread_id and optional previous_response_id.
        """
        config: dict = {"configurable": {"thread_id": thread_id}}
        if previous_response_id:
            config["previous_response_id"] = previous_response_id
        return config

    def _invoke_with_middleware(self, state: dict, config: dict) -> dict:
        """Invoke the agent with the full middleware hook chain.

        Hook order: before_agent → before_model → invoke → after_model → after_agent
        Loop/budget enforcement is handled by LangChain prebuilt middleware passed
        to create_deep_agent; this method only runs the custom hook chain.
        On exception: on_error hooks fire, then exception re-raises.

        Args:
            state: LangGraph input state.
            config: LangGraph run config.

        Returns:
            Agent output state.

        Raises:
            Exception: Re-raises any exception after running on_error hooks.
        """
        agent = self._get_agent()
        stack = getattr(self, "middleware_stack", [])

        for mw in stack:
            if hasattr(mw, "before_agent"):
                try:
                    result = mw.before_agent(state, None)
                    if result is not None:
                        state = result
                except Exception as e:
                    logger.error(f"Middleware {mw.__class__.__name__} blocked execution: {e}")
                    raise

        for mw in stack:
            if hasattr(mw, "before_model"):
                mw.before_model(state, None)

        try:
            output = agent.invoke(state, config=config)

            for mw in stack:
                if hasattr(mw, "after_model"):
                    mw.after_model(output, None)

            for mw in stack:
                if hasattr(mw, "after_agent"):
                    mw.after_agent(output, None)

            return output

        except Exception as e:
            for mw in stack:
                if hasattr(mw, "on_error"):
                    mw.on_error(state, None, e)
            raise

    def _extract_response_id(self, message) -> Optional[str]:
        """Extract response ID from a LangChain message for multi-turn conversations.

        Args:
            message: Final message from agent output (LangChain message object or dict).

        Returns:
            Response ID string or None if not present.
        """
        if hasattr(message, "response_metadata"):
            return message.response_metadata.get("id")
        if isinstance(message, dict) and "response_metadata" in message:
            return message["response_metadata"].get("id")
        return None

    def stream(
        self,
        query: str,
        thread_id: str = "default",
        stream_mode: list = ["updates", "messages"],
        previous_response_id: Optional[str] = None
    ) -> Iterator[dict]:
        """Stream agent execution, yielding reasoning/text/tool_call events.

        Args:
            query: Natural language query.
            thread_id: Thread ID for context preservation.
            stream_mode: LangGraph stream modes (default: ["updates", "messages"]).
            previous_response_id: Previous response ID for multi-turn conversations.

        Yields:
            Dict with keys: step, type (reasoning/text/tool_call/update/error), content, timestamp.
        """
        logger.info(f"{self._agent_name} streaming query: {query}")
        if previous_response_id:
            logger.info(f"Continuing conversation from response: {previous_response_id}")

        state = self._build_state(query)
        config = self._build_config(thread_id, previous_response_id)

        try:
            agent = self._get_agent()
            for chunk in agent.stream(state, config=config, stream_mode=stream_mode):
                yield from self._parse_chunk(chunk)
        except Exception as e:
            logger.error(f"{self._agent_name} streaming failed: {e}")
            yield {
                "step": "error",
                "type": "error",
                "content": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def _parse_chunk(self, chunk) -> Iterator[dict]:
        """Parse a single LangGraph stream chunk into yield-able events.

        Args:
            chunk: Raw chunk from agent.stream() — either a (mode, data) tuple
                   (when stream_mode is a list) or a plain dict.

        Yields:
            Parsed event dicts.
        """
        if isinstance(chunk, tuple):
            mode, chunk_data = chunk
            if mode == "messages":
                msg = chunk_data[0] if isinstance(chunk_data, (tuple, list)) else chunk_data
                content = getattr(msg, "content", "") or ""
                if content and isinstance(content, str):
                    yield {
                        "step": "model",
                        "type": "text",
                        "content": content,
                        "timestamp": datetime.now().isoformat()
                    }
                return
            items = chunk_data.items() if isinstance(chunk_data, dict) else []
        else:
            items = chunk.items() if isinstance(chunk, dict) else []

        for step, data in items:
            yield from self._parse_step(step, data)

    def _parse_step(self, step: str, data) -> Iterator[dict]:
        """Parse a step/data pair from a LangGraph update chunk.

        Args:
            step: Node name ("model", "tools", etc.).
            data: Node output data.

        Yields:
            Parsed event dicts with type reasoning/text/tool_call/update.
        """
        if step == "model" and "messages" in data and data["messages"]:
            last_message = data["messages"][-1]

            if hasattr(last_message, "content_blocks"):
                content_blocks = last_message.content_blocks
            elif isinstance(last_message, dict) and "content_blocks" in last_message:
                content_blocks = last_message["content_blocks"]
            else:
                yield {
                    "step": step,
                    "type": "text",
                    "content": getattr(last_message, "content", str(last_message)),
                    "timestamp": datetime.now().isoformat()
                }
                return

            for block in content_blocks:
                if isinstance(block, dict):
                    block_type = block.get("type")
                    if block_type == "reasoning":
                        yield {
                            "step": step,
                            "type": "reasoning",
                            "content": block.get("reasoning", ""),
                            "timestamp": datetime.now().isoformat()
                        }
                    elif block_type == "text":
                        yield {
                            "step": step,
                            "type": "text",
                            "content": block.get("text", ""),
                            "timestamp": datetime.now().isoformat()
                        }

        elif step == "tools":
            yield {
                "step": "tool",
                "type": "tool_call",
                "content": data,
                "timestamp": datetime.now().isoformat()
            }

        else:
            yield {
                "step": step,
                "type": "update",
                "content": str(data),
                "timestamp": datetime.now().isoformat()
            }
