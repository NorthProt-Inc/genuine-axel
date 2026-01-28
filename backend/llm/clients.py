import os
import time
from collections import deque
from typing import Optional, AsyncGenerator, List, Dict, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod
from dotenv import load_dotenv
from backend.core.logging import get_logger
from backend.core.logging.error_monitor import error_monitor
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

from backend.config import MODEL_NAME

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
        name="Gemini 3 Pro",
        model=MODEL_NAME,
        provider="google",
        api_key_env="GEMINI_API_KEY",
        icon="",
        supports_vision=True,
    ),
}

DEFAULT_PROVIDER = "google"

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

class GeminiClient(BaseLLMClient):

    _circuit_breaker = CircuitBreakerState()

    @classmethod
    def is_circuit_open(cls) -> bool:

        return not cls._circuit_breaker.can_proceed()

    def __init__(self, model: str = None):
        model = model or MODEL_NAME
        _log.debug("gemini client init start", model=model)
        from backend.core.utils.gemini_wrapper import GenerativeModelWrapper
        from google.genai import types

        self.wrapper = GenerativeModelWrapper(model_name=model)
        self.model_name = model
        self._types = types
        _log.info("gemini client ready", model=model)

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

        generation_config = self._types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

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

        MAX_STREAM_RETRIES = 5

        if force_tool_call and gemini_tools:
            _log.info("force tool call enabled", tools=len(tools) if tools else 0)

        stream_start_time = time.time()
        _log.debug("stream call start",
                   model=self.model_name,
                   tools=len(tools) if tools else 0,
                   images=len(images) if images else 0,
                   max_retries=MAX_STREAM_RETRIES)

        def sync_stream_call():

            _log.debug("sync stream call enter")
            result = self.wrapper.generate_content_sync(
                contents=contents,
                stream=True,
                generation_config=generation_config,
                enable_thinking=enable_thinking,
                thinking_level=thinking_level,
                tools=gemini_tools,
                force_tool_call=force_tool_call
            )
            _log.debug("sync stream call done")
            return result

        for retry_attempt in range(MAX_STREAM_RETRIES):
            try:

                if retry_attempt > 0:
                    from backend.core.utils.gemini_wrapper import GenerativeModelWrapper
                    self.wrapper = GenerativeModelWrapper(model_name=self.model_name)
                    _log.info("wrapper recreated for retry", attempt=retry_attempt + 1)

                _log.debug("api call start", timeout_s=API_CALL_TIMEOUT, attempt=retry_attempt + 1)
                try:
                    response_wrapper = await asyncio.wait_for(
                        asyncio.to_thread(sync_stream_call),
                        timeout=API_CALL_TIMEOUT
                    )
                    _log.debug("api call response received")
                except asyncio.TimeoutError:
                    _log.error("api call timeout", timeout_s=API_CALL_TIMEOUT)
                    raise Exception(f"Gemini API timeout ({API_CALL_TIMEOUT}s) - server not responding")

                queue = asyncio.Queue()
                loop = asyncio.get_event_loop()

                def run_sync_iteration():
                    try:
                        for chunk in response_wrapper:

                             func_call = chunk.function_call if hasattr(chunk, 'function_call') else None
                             loop.call_soon_threadsafe(queue.put_nowait, (chunk.text, chunk.is_thought, func_call))
                        loop.call_soon_threadsafe(queue.put_nowait, None)
                    except Exception as e:
                        loop.call_soon_threadsafe(queue.put_nowait, e)

                import threading
                t = threading.Thread(target=run_sync_iteration)
                t.start()

                first_chunk_received = False

                while True:

                    tool_count = len(gemini_tools[0].function_declarations) if gemini_tools else 0
                    dynamic_timeout = _calculate_dynamic_timeout(tool_count, is_first_chunk=not first_chunk_received, model=self.model_name)

                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=dynamic_timeout)
                    except asyncio.TimeoutError:
                        _log.warning("stream chunk timeout",
                                     timeout_s=dynamic_timeout,
                                     tools=tool_count,
                                     first_chunk=not first_chunk_received,
                                     model=self.model_name)
                        raise Exception(f"Stream timeout ({dynamic_timeout}s) - tools: {tool_count}")
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item

                    if not first_chunk_received:
                        first_chunk_received = True

                    yield item

                GeminiClient._circuit_breaker.record_success()

                stream_elapsed = time.time() - stream_start_time
                _adaptive_timeout.record_latency(stream_elapsed)

                break

            except Exception as e:
                error_str = str(e).lower()
                is_429 = '429' in error_str or 'resource_exhausted' in error_str
                is_503 = '503' in error_str or 'unavailable' in error_str or 'overloaded' in error_str
                is_timeout = 'timeout' in error_str
                is_retryable = is_429 or is_503 or is_timeout

                error_category = "rate_limit" if is_429 else ("server_error" if is_503 else ("timeout" if is_timeout else "unknown"))
                attempt_elapsed = time.time() - stream_start_time

                _log.warning("stream error",
                             category=error_category,
                             attempt=retry_attempt + 1,
                             max_retries=MAX_STREAM_RETRIES,
                             dur_ms=int(attempt_elapsed * 1000),
                             retryable=is_retryable,
                             err=str(e)[:150])

                if is_503:
                    GeminiClient._circuit_breaker.record_failure("server_error")
                    error_monitor.record("503", str(e)[:200])
                    _log.warning("circuit breaker failure (503)",
                                 cooldown_s=GeminiClient._circuit_breaker._cooldown_seconds,
                                 failures=GeminiClient._circuit_breaker._failure_count)

                elif is_429:
                    GeminiClient._circuit_breaker.record_failure("rate_limit")
                    error_monitor.record("429", str(e)[:200])
                    _log.warning("rate limit (429)",
                                 failures=GeminiClient._circuit_breaker._failure_count)

                elif is_timeout:
                    GeminiClient._circuit_breaker.record_failure("timeout")
                    error_monitor.record("timeout", str(e)[:200])
                    _log.warning("timeout detected",
                                 err=str(e)[:50],
                                 failures=GeminiClient._circuit_breaker._failure_count)

                if is_retryable and retry_attempt < MAX_STREAM_RETRIES - 1:
                    if is_503:
                        delay = (2 ** retry_attempt) * 3
                    elif is_timeout:
                        delay = (2 ** retry_attempt) * 2
                    else:
                        delay = 2 ** retry_attempt

                    _log.warning("retry backoff",
                                 err_type="503" if is_503 else ("timeout" if is_timeout else "429"),
                                 next_attempt=retry_attempt + 2,
                                 delay_s=delay,
                                 remaining=MAX_STREAM_RETRIES - retry_attempt - 1)
                    await asyncio.sleep(delay)
                    continue

                total_elapsed = time.time() - stream_start_time
                _log.error("gemini stream failed",
                           err=str(e)[:300],
                           err_type=type(e).__name__,
                           category=error_category,
                           dur_ms=int(total_elapsed * 1000),
                           retry_exhausted=is_retryable)
                raise

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        images: List[Any] = None,
    ) -> str:

        import asyncio

        text_content = prompt
        if system_prompt:
            text_content = f"[System Instructions]\n{system_prompt}\n\n{prompt}"

        parts = [self._types.Part.from_text(text=text_content)]

        if images:
            import base64
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

        generation_config = self._types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        result = self.wrapper.generate_content_sync(
            contents=contents,
            stream=False,
            generation_config=generation_config
        )
        return result.text

def get_llm_client(provider_name: str, model: str = None) -> BaseLLMClient:

    provider = get_provider(provider_name)
    model_name = model or provider.model

    if provider.provider == "google":
        return GeminiClient(model=model_name)

    else:
        raise ValueError(f"알 수 없는 프로바이더: {provider_name}")
