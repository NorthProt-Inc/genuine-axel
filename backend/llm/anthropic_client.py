"""Anthropic Claude LLM client implementation.

This module provides the AnthropicClient class for interacting with
Anthropic's Claude API with streaming support, retry logic, and circuit breaking.
"""

import json as json_mod
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from backend.config import ANTHROPIC_CHAT_MODEL, ANTHROPIC_THINKING_BUDGET, STREAM_MAX_RETRIES
from backend.core.logging import get_logger
from backend.core.logging.error_monitor import error_monitor
from backend.core.utils.retry import RetryConfig, classify_error, retry_async_generator
from backend.core.errors import ProviderError

from .base import BaseLLMClient
from .circuit_breaker import CircuitBreakerState, _adaptive_timeout

_log = get_logger("llm.anthropic_client")


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API client with native async support."""

    _circuit_breaker = CircuitBreakerState()

    @classmethod
    def is_circuit_open(cls) -> bool:
        """Check if circuit breaker is currently blocking requests."""
        return not cls._circuit_breaker.can_proceed()

    def __init__(self, model: str | None = None):
        """Initialize Anthropic client.

        Args:
            model: Model name (defaults to ANTHROPIC_CHAT_MODEL from config)
        """
        model = model or ANTHROPIC_CHAT_MODEL
        _log.debug("anthropic client init", model=model)
        import anthropic
        self._client = anthropic.AsyncAnthropic()
        self._anthropic = anthropic
        self.model_name = model
        _log.info("anthropic client ready", model=model)

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        images: Optional[List[Any]] = None,
        enable_thinking: bool = False,
        thinking_level: str = "high",
        tools: Optional[List[Dict]] = None,
        force_tool_call: bool = False,
    ) -> AsyncGenerator[tuple, None]:
        """Generate a streaming response from Anthropic Claude.

        Args:
            prompt: User prompt text
            system_prompt: System instructions
            temperature: Sampling temperature (ignored if enable_thinking=True)
            max_tokens: Maximum tokens to generate
            images: Optional list of images
            enable_thinking: Whether to enable extended thinking
            thinking_level: Level of thinking (currently unused by Anthropic API)
            tools: Optional tool definitions
            force_tool_call: Whether to force tool call

        Yields:
            Tuples of (text_chunk, is_thought, function_call)

        Raises:
            Exception: If circuit breaker is open or API call fails
        """
        if AnthropicClient.is_circuit_open():
            remaining = AnthropicClient._circuit_breaker.get_remaining_cooldown()
            _log.warning("circuit breaker open (anthropic)", remaining_s=remaining)
            raise ProviderError(
                f"Circuit breaker open ({remaining}s remaining). Anthropic API temporarily unavailable.",
                provider="anthropic",
            )

        # Build user content array
        content: List[Dict[str, Any]] = []
        if images:
            for img_data in images:
                if isinstance(img_data, dict):
                    mime_type = img_data.get("mime_type", "image/png")
                    b64_data = img_data.get("data", "")
                    if b64_data:
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64_data,
                            },
                        })
        content.append({"type": "text", "text": prompt})

        messages = [{"role": "user", "content": content}]

        # Build API kwargs
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        # System prompt with prompt caching
        if system_prompt:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        # Thinking configuration
        if enable_thinking:
            budget = ANTHROPIC_THINKING_BUDGET
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget,
            }
            # Anthropic: temperature not allowed with thinking
            # Ensure max_tokens covers both thinking + response
            kwargs["max_tokens"] = max(max_tokens, budget + max_tokens)
        else:
            kwargs["temperature"] = temperature

        # Tools (with cache_control on last item for prompt caching)
        if tools:
            tools_copy = [dict(t) for t in tools]
            if tools_copy:
                tools_copy[-1]["cache_control"] = {"type": "ephemeral"}
            kwargs["tools"] = tools_copy
            if force_tool_call and not enable_thinking:
                kwargs["tool_choice"] = {"type": "any"}
            else:
                kwargs["tool_choice"] = {"type": "auto"}

        stream_start_time = time.time()

        _log.debug("anthropic stream start",
                   model=self.model_name,
                   tools=len(tools) if tools else 0,
                   images=len(images) if images else 0,
                   thinking=enable_thinking)

        def _is_retryable_anthropic(error: Exception) -> bool:
            """Check if an Anthropic API error is retryable."""
            if isinstance(error, self._anthropic.RateLimitError):
                return True
            if isinstance(error, self._anthropic.APIStatusError):
                return getattr(error, "status_code", 0) in (429, 503, 529)
            if isinstance(error, (self._anthropic.APITimeoutError, self._anthropic.APIConnectionError)):
                return True
            # Fallback: check error string for retryable patterns (e.g. streaming overloaded errors)
            error_str = str(error).lower()
            if any(p in error_str for p in ("overloaded", "529", "503", "rate_limit")):
                return True
            return False

        anthropic_retry_config = RetryConfig(
            max_retries=STREAM_MAX_RETRIES, base_delay=2.0, max_delay=60.0, jitter=0.3,
            retryable_check=_is_retryable_anthropic,
        )

        async def _create_stream() -> AsyncGenerator[tuple, None]:
            current_tool_name: str | None = None
            current_tool_json = ""

            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if hasattr(block, "type") and block.type == "tool_use":
                            current_tool_name = block.name
                            current_tool_json = ""

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield (delta.text, False, None)
                        elif delta.type == "thinking_delta":
                            yield (delta.thinking, True, None)
                        elif delta.type == "input_json_delta":
                            current_tool_json += delta.partial_json

                    elif event.type == "content_block_stop":
                        if current_tool_name:
                            try:
                                args = json_mod.loads(current_tool_json) if current_tool_json else {}
                            except json_mod.JSONDecodeError:
                                _log.error("tool json parse failed, skipping tool call",
                                           tool=current_tool_name,
                                           json_preview=current_tool_json[:100])
                                current_tool_name = None
                                current_tool_json = ""
                                continue
                            yield ("", False, {"name": current_tool_name, "args": args})
                            current_tool_name = None
                            current_tool_json = ""

        def _on_retry(attempt: int, error: Exception, delay: float) -> None:
            error_monitor.record(classify_error(error), str(error)[:200])

        try:
            async for item in retry_async_generator(
                _create_stream,
                config=anthropic_retry_config,
                on_retry=_on_retry,
            ):
                yield item
        except Exception as e:
            error_type = classify_error(e)
            AnthropicClient._circuit_breaker.record_failure(error_type)
            raise

        AnthropicClient._circuit_breaker.record_success()
        stream_elapsed = time.time() - stream_start_time
        _adaptive_timeout.record_latency(stream_elapsed)

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        images: Optional[List[Any]] = None,
    ) -> str:
        """Generate a non-streaming response from Anthropic Claude.

        Args:
            prompt: User prompt text
            system_prompt: System instructions
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            images: Optional list of images

        Returns:
            Generated text response
        """
        content: List[Dict[str, Any]] = []
        if images:
            for img_data in images:
                if isinstance(img_data, dict):
                    mime_type = img_data.get("mime_type", "image/png")
                    b64_data = img_data.get("data", "")
                    if b64_data:
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64_data,
                            },
                        })
        content.append({"type": "text", "text": prompt})

        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self._client.messages.create(**kwargs)
        return "".join(
            block.text for block in response.content if block.type == "text"
        )


__all__ = ["AnthropicClient"]
