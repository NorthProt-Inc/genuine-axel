"""Google Gemini LLM client implementation.

This module provides the GeminiClient class for interacting with
Google's Gemini API with streaming support, retry logic, and circuit breaking.
"""

import base64
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from backend.config import MODEL_NAME, STREAM_MAX_RETRIES
from backend.core.logging import get_logger
from backend.core.logging.error_monitor import error_monitor
from backend.core.utils.retry import RetryConfig, classify_error, retry_async_generator
from backend.core.errors import ProviderError

from .base import BaseLLMClient
from .circuit_breaker import CircuitBreakerState, _adaptive_timeout

_log = get_logger("llm.gemini_client")


class GeminiClient(BaseLLMClient):
    """Google Gemini API client with streaming support."""

    _circuit_breaker = CircuitBreakerState()

    @classmethod
    def is_circuit_open(cls) -> bool:
        """Check if circuit breaker is currently blocking requests."""
        return not cls._circuit_breaker.can_proceed()

    def __init__(self, model: Optional[str] = None):
        """Initialize Gemini client.

        Args:
            model: Model name (defaults to MODEL_NAME from config)
        """
        model = model or MODEL_NAME
        _log.debug("gemini client init start", model=model)
        from backend.core.utils.gemini_client import get_gemini_client
        from google.genai import types

        self._client = get_gemini_client()
        self.model_name = model
        self._types = types
        _log.info("gemini client ready", model=model)

    @staticmethod
    def _build_config(
        temperature: float,
        max_tokens: int,
        enable_thinking: bool,
        thinking_level: str | None,
        tools: Any,
        force_tool_call: bool,
    ) -> Any:
        """Build GenerateContentConfig from parameters.

        Args:
            temperature: Sampling temperature
            max_tokens: Maximum output tokens
            enable_thinking: Whether to enable thinking mode
            thinking_level: Level of thinking (if enabled)
            tools: Tool definitions
            force_tool_call: Whether to force tool usage

        Returns:
            GenerateContentConfig instance
        """
        from google.genai import types

        thinking_config = None
        if enable_thinking:
            kwargs: dict[str, Any] = {"include_thoughts": True}
            if thinking_level:
                kwargs["thinking_level"] = thinking_level
            thinking_config = types.ThinkingConfig(**kwargs)

        tool_config = None
        if tools and force_tool_call:
            tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")  # type: ignore[arg-type]
            )

        return types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            thinking_config=thinking_config,
            tools=tools,
            tool_config=tool_config,
        )

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
        """Generate a streaming response from Gemini.

        Args:
            prompt: User prompt text
            system_prompt: System instructions
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            images: Optional list of images
            enable_thinking: Whether to enable thinking mode
            thinking_level: Level of thinking
            tools: Optional tool definitions
            force_tool_call: Whether to force tool call

        Yields:
            Tuples of (text_chunk, is_thought, function_call)

        Raises:
            Exception: If circuit breaker is open or API call fails
        """
        _log.debug("circuit breaker check",
                   state=GeminiClient._circuit_breaker._state,
                   failures=GeminiClient._circuit_breaker._failure_count)
        if GeminiClient.is_circuit_open():
            remaining = GeminiClient._circuit_breaker.get_remaining_cooldown()
            _log.warning("circuit breaker open", remaining_s=remaining)
            raise ProviderError(
                f"Circuit breaker open ({remaining}s remaining). Gemini API temporarily unavailable.",
                provider="gemini",
            )

        # Build content
        text_content = prompt
        if system_prompt:
            text_content = f"[System Instructions]\n{system_prompt}\n\n{prompt}"

        parts = [self._types.Part.from_text(text=text_content)]

        # Add images
        if images:
            for img_data in images:
                try:
                    if isinstance(img_data, dict):
                        mime_type = img_data.get("mime_type", "image/png")
                        b64_data = img_data.get("data", "")
                        if b64_data:
                            image_bytes = base64.b64decode(b64_data)
                            parts.append(self._types.Part.from_bytes(
                                data=image_bytes,
                                mime_type=mime_type
                            ))
                            _log.debug("image added", mime=mime_type, size_bytes=len(image_bytes))
                    elif isinstance(img_data, bytes):
                        parts.append(self._types.Part.from_bytes(
                            data=img_data,
                            mime_type="image/png"
                        ))
                    elif isinstance(img_data, str):
                        image_bytes = base64.b64decode(img_data)
                        parts.append(self._types.Part.from_bytes(
                            data=image_bytes,
                            mime_type="image/png"
                        ))
                except Exception as e:
                    _log.error("image add failed", err=str(e))

        contents = [self._types.Content(role="user", parts=parts)]

        # Convert tools to Gemini format
        gemini_tools = None
        if tools:
            try:
                from google.genai.types import FunctionDeclaration, Tool as GeminiTool
                function_declarations = [
                    FunctionDeclaration(
                        name=t["name"],
                        description=t["description"],
                        parameters=t.get("parameters", {})
                    )
                    for t in tools
                ]
                gemini_tools = [GeminiTool(function_declarations=function_declarations)]
            except Exception as e:
                _log.warning("tools setup failed", err=str(e))

        # Build config
        config = self._build_config(
            temperature, max_tokens, enable_thinking, thinking_level,
            gemini_tools, force_tool_call,
        )

        GEMINI_STREAM_RETRY_CONFIG = RetryConfig(
            max_retries=STREAM_MAX_RETRIES, base_delay=2.0, max_delay=60.0, jitter=0.3,
        )

        if force_tool_call and gemini_tools:
            _log.info("force tool call enabled", tools=len(tools) if tools else 0)

        stream_start_time = time.time()
        _log.debug("stream call start",
                   model=self.model_name,
                   tools=len(tools) if tools else 0,
                   images=len(images) if images else 0,
                   max_retries=GEMINI_STREAM_RETRY_CONFIG.max_retries)

        async def _create_stream() -> AsyncGenerator[tuple, None]:
            async for chunk in self._client.aio.models.generate_content_stream(  # type: ignore[attr-defined]
                model=self.model_name,
                contents=contents,  # type: ignore[arg-type]
                config=config,
            ):
                is_thought = False
                text_chunk = ""
                function_calls: list[dict[str, Any]] = []

                try:
                    if hasattr(chunk, "candidates") and chunk.candidates:
                        candidate = chunk.candidates[0]
                        if hasattr(candidate, "content") and candidate.content:
                            parts_list = candidate.content.parts if hasattr(candidate.content, "parts") else []
                            for part in (parts_list or []):
                                if hasattr(part, "thought") and part.thought:
                                    is_thought = True
                                if hasattr(part, "text") and part.text:
                                    text_chunk += part.text
                                if hasattr(part, "function_call") and part.function_call:
                                    fc = part.function_call
                                    if fc.name:
                                        function_calls.append({
                                            "name": fc.name,
                                            "args": dict(fc.args) if fc.args else {},
                                        })
                    elif hasattr(chunk, "text") and chunk.text:
                        text_chunk = chunk.text
                except Exception as e:
                    _log.warning("Chunk parsing error", error=str(e)[:100])
                    continue

                # Yield function calls
                for fc_item in function_calls:
                    yield ("", False, fc_item)

                # Yield text chunks (excluding those with function calls)
                if text_chunk and not function_calls:
                    yield (text_chunk, is_thought, None)

        def _on_retry(attempt: int, error: Exception, delay: float) -> None:
            error_monitor.record(classify_error(error), str(error)[:200])

        try:
            async for item in retry_async_generator(
                _create_stream,
                config=GEMINI_STREAM_RETRY_CONFIG,
                on_retry=_on_retry,
            ):
                yield item
        except Exception as e:
            error_type = classify_error(e)
            GeminiClient._circuit_breaker.record_failure(error_type)
            raise

        GeminiClient._circuit_breaker.record_success()
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
        """Generate a non-streaming response from Gemini.

        Args:
            prompt: User prompt text
            system_prompt: System instructions
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            images: Optional list of images

        Returns:
            Generated text response
        """
        text_content = prompt
        if system_prompt:
            text_content = f"[System Instructions]\n{system_prompt}\n\n{prompt}"

        parts = [self._types.Part.from_text(text=text_content)]

        if images:
            for img_data in images:
                try:
                    if isinstance(img_data, dict):
                        mime = img_data.get("mime_type", "image/png")
                        data = img_data.get("data", "")
                        if data:
                            b_data = base64.b64decode(data)
                            parts.append(self._types.Part.from_bytes(data=b_data, mime_type=mime))
                    elif isinstance(img_data, bytes):
                        parts.append(self._types.Part.from_bytes(data=img_data, mime_type="image/png"))
                    elif isinstance(img_data, str):
                        b_data = base64.b64decode(img_data)
                        parts.append(self._types.Part.from_bytes(data=b_data, mime_type="image/png"))
                except Exception as e:
                    _log.error("image add failed", err=str(e))

        contents = [self._types.Content(role="user", parts=parts)]

        config = self._types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        response = await self._client.aio.models.generate_content(
            model=self.model_name,
            contents=contents,  # type: ignore[arg-type]
            config=config,
        )
        return response.text if response.text else ""


__all__ = ["GeminiClient"]
