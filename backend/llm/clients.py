import os
import time
from collections import deque
from typing import AsyncGenerator, List, Dict, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod
from dotenv import load_dotenv
from backend.config import STREAM_MAX_RETRIES
from backend.core.logging import get_logger
from backend.core.logging.error_monitor import error_monitor
from backend.core.utils.retry import RetryConfig, classify_error, retry_async_generator
from backend.core.utils.timeouts import TIMEOUTS

_log = get_logger("llm.clients")

API_CALL_TIMEOUT = TIMEOUTS.API_CALL
STREAM_CHUNK_TIMEOUT = TIMEOUTS.STREAM_CHUNK
CIRCUIT_BREAKER_DURATION = TIMEOUTS.CIRCUIT_BREAKER_DEFAULT
FIRST_CHUNK_BASE_TIMEOUT = TIMEOUTS.FIRST_CHUNK_BASE

class AdaptiveTimeout:

    def __init__(self):
        self._recent_latencies: deque = deque(maxlen=10)

    def record_latency(self, latency_seconds: float):

        self._recent_latencies.append(latency_seconds)

    def calculate(self, tool_count: int, model: str, is_first_chunk: bool = True) -> int:

        if not is_first_chunk:
            return STREAM_CHUNK_TIMEOUT

        base = FIRST_CHUNK_BASE_TIMEOUT

        if tool_count <= 10:
            tool_factor = tool_count * 2
        elif tool_count <= 20:
            tool_factor = 20 + ((tool_count - 10) * 3)
        else:
            tool_factor = 50 + ((tool_count - 20) * 4)

        if self._recent_latencies:
            avg_latency = sum(self._recent_latencies) / len(self._recent_latencies)
            latency_factor = 1 + (avg_latency / 30)
            latency_factor = min(latency_factor, 2.0)
        else:
            latency_factor = 1.0

        timeout = int((base + tool_factor) * latency_factor)
        max_timeout = TIMEOUTS.API_CALL - 10
        return min(timeout, max_timeout)

_adaptive_timeout = AdaptiveTimeout()

class CircuitBreakerState:

    def __init__(self):
        self._state = "closed"
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._cooldown_seconds = CIRCUIT_BREAKER_DURATION
        self._open_until = 0.0

    def record_failure(self, error_type: str):

        self._failure_count += 1
        self._last_failure_time = time.time()

        if error_type == "rate_limit":
            self._cooldown_seconds = 300
        elif error_type == "server_error":
            self._cooldown_seconds = 60
        elif error_type == "timeout":
            self._cooldown_seconds = 30
        else:
            self._cooldown_seconds = CIRCUIT_BREAKER_DURATION

        if self._failure_count >= 5:
            self._state = "open"
            self._open_until = time.time() + self._cooldown_seconds
            _log.warning("circuit breaker opened",
                         err_type=error_type,
                         cooldown_s=self._cooldown_seconds,
                         failures=self._failure_count)

    def record_success(self):

        self._failure_count = 0
        if self._state == "half-open":
            self._state = "closed"
            _log.info("circuit breaker closed")

    def can_proceed(self) -> bool:

        if self._state == "closed":
            return True

        if time.time() > self._open_until:
            self._state = "half-open"
            _log.info("circuit breaker half-open")
            return True

        return False

    def get_remaining_cooldown(self) -> int:

        if self._state == "closed":
            return 0
        remaining = int(self._open_until - time.time())
        return max(0, remaining)

def _calculate_dynamic_timeout(tool_count: int, is_first_chunk: bool = True, model: str = None) -> int:

    return _adaptive_timeout.calculate(tool_count, model or "", is_first_chunk)

load_dotenv()

from backend.config import MODEL_NAME, ANTHROPIC_CHAT_MODEL, ANTHROPIC_THINKING_BUDGET

@dataclass
class LLMProvider:

    name: str
    model: str
    provider: str
    api_key_env: str
    icon: str
    supports_vision: bool = True
    supports_streaming: bool = True

LLM_PROVIDERS: Dict[str, LLMProvider] = {
    "google": LLMProvider(
        name="Gemini 3 Flash",
        model=MODEL_NAME,
        provider="google",
        api_key_env="GEMINI_API_KEY",
        icon="",
        supports_vision=True,
    ),
    "anthropic": LLMProvider(
        name="Claude Sonnet 4.5",
        model=ANTHROPIC_CHAT_MODEL,
        provider="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        icon="",
        supports_vision=True,
    ),
}

DEFAULT_PROVIDER = "anthropic"

def get_provider(name: str) -> LLMProvider:

    return LLM_PROVIDERS.get(name, LLM_PROVIDERS[DEFAULT_PROVIDER])

def get_all_providers() -> List[Dict[str, Any]]:

    return [
        {
            "id": key,
            "name": p.name,
            "icon": p.icon,
            "available": bool(os.getenv(p.api_key_env)),
        }
        for key, p in LLM_PROVIDERS.items()
    ]

class BaseLLMClient(ABC):

    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        images: List[Any] = None,
        enable_thinking: bool = False,
        thinking_level: str = "high",
        tools: List[Dict] = None,
        force_tool_call: bool = False,
    ) -> AsyncGenerator[tuple, None]:

        pass

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        images: List[Any] = None,
    ) -> str:

        pass

def _gemini_schema_to_anthropic(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert Gemini UPPERCASED schema types to Anthropic lowercase.

    Args:
        schema: Gemini-format schema dict with UPPERCASE type values

    Returns:
        Schema dict with lowercase type values for Anthropic API
    """
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            result[key] = value.lower()
        elif isinstance(value, dict):
            result[key] = _gemini_schema_to_anthropic(value)
        elif isinstance(value, list):
            result[key] = [
                _gemini_schema_to_anthropic(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


class GeminiClient(BaseLLMClient):

    _circuit_breaker = CircuitBreakerState()

    @classmethod
    def is_circuit_open(cls) -> bool:

        return not cls._circuit_breaker.can_proceed()

    def __init__(self, model: str = None):
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
    ) -> "types.GenerateContentConfig":
        """Build GenerateContentConfig from parameters."""
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
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
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
        images: List[Any] = None,
        enable_thinking: bool = False,
        thinking_level: str = "high",
        tools: List[Dict] = None,
        force_tool_call: bool = False,
    ) -> AsyncGenerator[tuple, None]:

        import base64
        import asyncio

        _log.debug("circuit breaker check",
                   state=GeminiClient._circuit_breaker._state,
                   failures=GeminiClient._circuit_breaker._failure_count)
        if GeminiClient.is_circuit_open():
            remaining = GeminiClient._circuit_breaker.get_remaining_cooldown()
            _log.warning("circuit breaker open", remaining_s=remaining)
            raise Exception(f"Circuit breaker open ({remaining}s remaining). Gemini API temporarily unavailable.")

        text_content = prompt
        if system_prompt:
            text_content = f"[System Instructions]\n{system_prompt}\n\n{prompt}"

        parts = [self._types.Part.from_text(text=text_content)]

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
            first_chunk_received = False
            tool_count = len(gemini_tools[0].function_declarations) if gemini_tools else 0

            async for chunk in self._client.aio.models.generate_content_stream(
                model=self.model_name,
                contents=contents,
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
                            for part in parts_list:
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

                if not first_chunk_received:
                    first_chunk_received = True

                for fc in function_calls:
                    yield ("", False, fc)

                if text_chunk and not function_calls:
                    yield (text_chunk, is_thought, None)

        def _on_retry(attempt: int, error: Exception, delay: float) -> None:
            error_type = classify_error(error)
            GeminiClient._circuit_breaker.record_failure(error_type)
            error_monitor.record(error_type, str(error)[:200])

        async for item in retry_async_generator(
            _create_stream,
            config=GEMINI_STREAM_RETRY_CONFIG,
            on_retry=_on_retry,
        ):
            yield item

        GeminiClient._circuit_breaker.record_success()
        stream_elapsed = time.time() - stream_start_time
        _adaptive_timeout.record_latency(stream_elapsed)

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        images: List[Any] = None,
    ) -> str:

        import base64

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
            contents=contents,
            config=config,
        )
        return response.text if response.text else ""

class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API client with native async support."""

    _circuit_breaker = CircuitBreakerState()

    @classmethod
    def is_circuit_open(cls) -> bool:
        return not cls._circuit_breaker.can_proceed()

    def __init__(self, model: str | None = None):
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
        images: List[Any] = None,
        enable_thinking: bool = False,
        thinking_level: str = "high",
        tools: List[Dict] = None,
        force_tool_call: bool = False,
    ) -> AsyncGenerator[tuple, None]:
        import json as json_mod

        if AnthropicClient.is_circuit_open():
            remaining = AnthropicClient._circuit_breaker.get_remaining_cooldown()
            _log.warning("circuit breaker open (anthropic)", remaining_s=remaining)
            raise Exception(f"Circuit breaker open ({remaining}s remaining). Anthropic API temporarily unavailable.")

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
            if isinstance(error, self._anthropic.RateLimitError):
                return True
            if isinstance(error, self._anthropic.APIStatusError):
                return getattr(error, "status_code", 0) == 529
            if isinstance(error, (self._anthropic.APITimeoutError, self._anthropic.APIConnectionError)):
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
            error_type = classify_error(error)
            AnthropicClient._circuit_breaker.record_failure(error_type)
            error_monitor.record(error_type, str(error)[:200])

        async for item in retry_async_generator(
            _create_stream,
            config=anthropic_retry_config,
            on_retry=_on_retry,
        ):
            yield item

        AnthropicClient._circuit_breaker.record_success()
        stream_elapsed = time.time() - stream_start_time
        _adaptive_timeout.record_latency(stream_elapsed)

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        images: List[Any] = None,
    ) -> str:
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


def get_llm_client(provider_name: str, model: str | None = None) -> BaseLLMClient:
    """Get an LLM client for the given provider.

    Args:
        provider_name: Provider key (e.g. "google", "anthropic")
        model: Optional model override

    Returns:
        BaseLLMClient instance
    """
    provider = get_provider(provider_name)
    model_name = model or provider.model

    if provider.provider == "google":
        return GeminiClient(model=model_name)
    elif provider.provider == "anthropic":
        return AnthropicClient(model=model_name)
    else:
        raise ValueError(f"알 수 없는 프로바이더: {provider_name}")
