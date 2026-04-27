"""Callback for logging LLM requests and responses."""

import json
from typing import Any, Dict, List
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.messages import BaseMessage
from typer import prompt
from src.common.utils import get_logger

logger = get_logger(__name__)


class LLMLoggingCallback(BaseCallbackHandler):
    """Callback that logs LLM tool calls and responses for debugging."""

    def __init__(self, log_prompts: bool = False, log_responses: bool = False, log_tool_calls: bool = True):
        """Initialize callback.

        Args:
            log_prompts: Whether to log full prompts sent to LLM (default: False - too verbose)
            log_responses: Whether to log full LLM responses (default: False - too verbose)
            log_tool_calls: Whether to log tool call sequence (default: True)
        """
        super().__init__()
        self.log_prompts = log_prompts
        self.log_responses = log_responses
        self.log_tool_calls = log_tool_calls
        self.call_count = 0

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        **kwargs: Any
    ) -> None:
        """Log when LLM starts processing."""
        # self.call_count += 1
        # logger.info(f"{'='*60}")
        # logger.info(f"[LLM CALL #{self.call_count}] Starting LLM request")
        # logger.info(f"Model: {serialized.get('name', serialized.get('id', ['unknown'])[0])}")

        # if self.log_prompts and prompts:
        #     logger.info(f"[LLM CALL #{self.call_count}] Prompts:")
        #     for i, prompt in enumerate(prompts):
        #         # Truncate very long prompts
        #         if len(prompt) > 100:
        #             logger.info(f"  Prompt {i+1}: {prompt[:100]}...\n  ...[TRUNCATED {len(prompt)-100} chars]...")
        #         else:
        #             logger.info(f"  Prompt {i+1}:\n{prompt}")

        pass

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        **kwargs: Any
    ) -> None:
        """Log when chat model starts processing."""
        # self.call_count += 1
        # logger.info(f"{'='*60}")
        # logger.info(f"[LLM CALL #{self.call_count}] Starting Chat LLM request")
        # logger.info(f"Model: {serialized.get('name', serialized.get('id', ['unknown'])[0])}")

        # if self.log_prompts and messages:
        #     logger.info(f"[LLM CALL #{self.call_count}] Messages:")
        #     for i, message_list in enumerate(messages):
        #         logger.info(f"  Message batch {i+1}:")
        #         for msg in message_list:
        #             role = getattr(msg, 'type', 'unknown')
        #             content = getattr(msg, 'content', str(msg))

        #             # Truncate very long messages
        #             if len(str(content)) > 100:
        #                 logger.info(f"  Prompt {i+1}: {str(content)[:100]}...\n  ...[TRUNCATED {len(str(content))-100} chars]...")
        #             else:
        #                 logger.info(f"    [{role}]: {content}")
        pass

    def on_llm_end(
        self,
        response: LLMResult,
        **kwargs: Any
    ) -> None:
        """Log when LLM finishes processing."""
        # Always log token usage (lightweight)
        if response.llm_output and 'token_usage' in response.llm_output:
            usage = response.llm_output['token_usage']
            logger.info(f"[LLM CALL #{self.call_count}] Tokens: {usage.get('total_tokens', 0)} "
                       f"(prompt: {usage.get('prompt_tokens', 0)}, "
                       f"completion: {usage.get('completion_tokens', 0)})")

        # Log tool calls if enabled (more useful than full responses)
        if self.log_tool_calls and response.generations:
            for generation_list in response.generations:
                for generation in generation_list:
                    # Check if generation has tool calls
                    if hasattr(generation, 'message') and hasattr(generation.message, 'tool_calls'):
                        tool_calls = generation.message.tool_calls
                        if tool_calls:
                            logger.info(f"[LLM CALL #{self.call_count}] Tool calls requested:")
                            for tc in tool_calls:
                                logger.info(f"  → {tc.get('name', 'unknown')}({list(tc.get('args', {}).keys())})")

        # Log full responses only if explicitly enabled
        if self.log_responses and response.generations:
            for i, generation_list in enumerate(response.generations):
                for j, generation in enumerate(generation_list):
                    text = generation.text if hasattr(generation, 'text') else str(generation)
                    if len(text) > 500:
                        logger.info(f"[LLM CALL #{self.call_count}] Response: {text[:500]}... (truncated)")
                    else:
                        logger.info(f"[LLM CALL #{self.call_count}] Response: {text}")

        logger.info(f"{'='*60}")

    def on_llm_error(
        self,
        error: Exception,
        **kwargs: Any
    ) -> None:
        """Log when LLM encounters an error."""
        logger.error(f"[LLM CALL #{self.call_count}] LLM Error: {error}", exc_info=True)
        logger.info(f"{'='*60}")
