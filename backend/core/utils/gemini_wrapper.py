from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types
import os
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from backend.core.logging import get_logger

_logger = get_logger("gemini_wrapper")

DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_RETRIES = 5
RETRY_DELAY_BASE = 2.0

_singleton_wrapper: "GenerativeModelWrapper" = None
_singleton_lock = None

def get_gemini_wrapper() -> "GenerativeModelWrapper":
    global _singleton_wrapper, _singleton_lock
    import threading
    if _singleton_lock is None:
        _singleton_lock = threading.Lock()
    if _singleton_wrapper is None:
        with _singleton_lock:
            if _singleton_wrapper is None:
                _singleton_wrapper = GenerativeModelWrapper()
    return _singleton_wrapper

class GeminiRetryExhaustedError(Exception):

    def __init__(self, message: str, last_error: Optional[Exception] = None):
        super().__init__(message)
        self.last_error = last_error

class GenerativeModelWrapper:

    def __init__(self, client_or_model: Any = None, model_name: str = None):

        if isinstance(client_or_model, str):
            model_name = client_or_model
            client_or_model = None

        if client_or_model is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY 환경변수가 필요합니다")
            _logger.info("genai.Client 생성 시작")
            self.client = genai.Client(api_key=api_key)
            _logger.info("genai.Client 생성 완료")
        else:
            self.client = client_or_model

        from backend.config import DEFAULT_GEMINI_MODEL
        self.model_name = model_name or DEFAULT_GEMINI_MODEL

    def clone(self) -> "GenerativeModelWrapper":

        return GenerativeModelWrapper(model_name=self.model_name)

    def generate_content_sync(
        self,
        contents: Any,
        stream: bool = False,
        generation_config: Any = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        enable_thinking: bool = False,
        thinking_level: str = None,
        tools: Any = None,
        force_tool_call: bool = False
    ) -> Any:

        import random

        if isinstance(contents, str):
            contents = [types.Content(role="user", parts=[types.Part.from_text(text=contents)])]
        elif isinstance(contents, list) and contents and isinstance(contents[0], str):
            parts = [types.Part.from_text(text=p) for p in contents]
            contents = [types.Content(role="user", parts=parts)]

        thinking_config = None
        if enable_thinking:
            thinking_config = types.ThinkingConfig(include_thoughts=True)
            if thinking_level:
                thinking_config = types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_level=thinking_level
                )

        tool_config = None
        if tools and force_tool_call:
            tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            )

        config = None
        if generation_config:
            if isinstance(generation_config, types.GenerateContentConfig):
                if thinking_config or tools or tool_config:
                    config = types.GenerateContentConfig(
                        temperature=generation_config.temperature,
                        max_output_tokens=generation_config.max_output_tokens,
                        thinking_config=thinking_config or generation_config.thinking_config,
                        tools=tools or generation_config.tools,
                        tool_config=tool_config,
                    )
                else:
                    config = generation_config
            else:
                config = types.GenerateContentConfig(
                    temperature=getattr(generation_config, 'temperature', None),
                    max_output_tokens=getattr(generation_config, 'max_output_tokens', None),
                    thinking_config=thinking_config,
                    tools=tools,
                    tool_config=tool_config,
                )
        elif thinking_config or tools or tool_config:
            config = types.GenerateContentConfig(
                thinking_config=thinking_config,
                tools=tools,
                tool_config=tool_config,
            )

        effective_config = None
        if config and (getattr(config, 'thinking_config', None) or
                       getattr(config, 'tools', None) or
                       getattr(config, 'tool_config', None)):
            effective_config = config

        _logger.info("generate_content_sync 시작",
                    model=self.model_name,
                    stream=stream,
                    timeout=timeout_seconds,
                    has_config=effective_config is not None)

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:

                if stream:
                    _logger.info("SDK generate_content_stream 호출 시작", attempt=attempt)
                    response_stream = self.client.models.generate_content_stream(
                        model=self.model_name,
                        contents=contents,
                        config=effective_config
                    )
                    _logger.info("SDK generate_content_stream 호출 완료")
                    return GenerateContentResponseWrapper(response_stream, stream=True)
                else:

                    def _call_sdk_sync():
                        return self.client.models.generate_content(
                            model=self.model_name,
                            contents=contents,
                            config=effective_config
                        )

                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(_call_sdk_sync)
                        try:
                            response = future.result(timeout=timeout_seconds)
                            return GenerateContentResponseWrapper(response, stream=False)
                        except FuturesTimeoutError:
                            _logger.warning("Gemini API timeout",
                                          timeout_seconds=timeout_seconds,
                                          attempt=attempt)
                            raise TimeoutError(f"Gemini API timeout ({timeout_seconds}s)")

            except TimeoutError:
                import random

                last_error = TimeoutError(f"Gemini API timeout ({timeout_seconds}s)")
                _logger.warning("Timeout detected", attempt=attempt)

                if attempt >= MAX_RETRIES:
                    _logger.error("Timeout exhausted",
                              attempt=attempt,
                              timeout=timeout_seconds)
                    raise last_error

                delay = RETRY_DELAY_BASE * (2 ** (attempt - 1)) * (1 + random.uniform(0.1, 0.3))
                _logger.info("Timeout retry", attempt=attempt, delay=round(delay, 1))
                time.sleep(delay)
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                retryable = any(x in error_str for x in ['429', 'timeout', '500', '502', '503', 'overloaded', 'resource_exhausted'])

                if not retryable or attempt == MAX_RETRIES:
                    raise

                delay = RETRY_DELAY_BASE * (2 ** (attempt - 1)) * (1 + random.uniform(0.1, 0.3))
                time.sleep(delay)

        raise GeminiRetryExhaustedError("Sync retry exhausted", last_error=last_error)

    async def embed_content(
        self,
        model: str,
        contents: Any,
        config: Any = None,
        task_type: str = None
    ) -> Any:

        import random

        last_error = None

        if config is None and task_type:
            config = {'task_type': task_type}

        for attempt in range(1, MAX_RETRIES + 1):
            try:

                return self.client.models.embed_content(
                    model=model,
                    contents=contents,
                    config=config
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                retryable = any(x in error_str for x in ['429', 'timeout', '500', '502', '503', 'overloaded', 'resource_exhausted'])

                if not retryable:
                     raise

                _logger.warning("Embed error, retrying",
                               attempt=attempt,
                               error=str(e)[:100])

                delay = RETRY_DELAY_BASE * (2 ** (attempt - 1)) * (1 + random.uniform(0.1, 0.3))
                await asyncio.sleep(delay)

        raise GeminiRetryExhaustedError("Embed retry exhausted", last_error=last_error)

    def embed_content_sync(
        self,
        model: str,
        contents: Any,
        config: Any = None,
        task_type: str = None
    ) -> Any:

        import random

        if config is None and task_type:
            config = {'task_type': task_type}

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self.client.models.embed_content(
                    model=model,
                    contents=contents,
                    config=config
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                retryable = any(x in error_str for x in ['429', 'timeout', '500', '502', '503', 'overloaded', 'resource_exhausted'])

                if not retryable or attempt == MAX_RETRIES:
                    raise

                _logger.warning("Embed sync error, retrying",
                               attempt=attempt,
                               error=str(e)[:100])

                delay = RETRY_DELAY_BASE * (2 ** (attempt - 1)) * (1 + random.uniform(0.1, 0.3))
                time.sleep(delay)

        raise GeminiRetryExhaustedError("Embed sync retry exhausted", last_error=last_error)

    async def generate_images(
        self,
        model: str,
        prompt: str,
        config: Any = None
    ) -> Any:

        import random

        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self.client.models.generate_images(
                    model=model,
                    prompt=prompt,
                    config=config
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                retryable = any(x in error_str for x in ['429', 'timeout', '500', '502', '503', 'overloaded'])

                if not retryable or attempt == MAX_RETRIES:
                    raise

                _logger.warning("Image gen error, retrying",
                               attempt=attempt,
                               error=str(e)[:100])

                delay = RETRY_DELAY_BASE * (2 ** (attempt - 1)) * (1 + random.uniform(0.1, 0.3))
                await asyncio.sleep(delay)

        raise GeminiRetryExhaustedError("Image gen retry exhausted", last_error=last_error)

    def generate_images_sync(
        self,
        model: str,
        prompt: str,
        config: Any = None
    ) -> Any:

        import random

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self.client.models.generate_images(
                    model=model,
                    prompt=prompt,
                    config=config
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                retryable = any(x in error_str for x in ['429', 'timeout', '500', '502', '503', 'overloaded', 'resource_exhausted'])

                if not retryable or attempt == MAX_RETRIES:
                    raise

                _logger.warning("Image gen sync error, retrying",
                               attempt=attempt,
                               error=str(e)[:100])

                delay = RETRY_DELAY_BASE * (2 ** (attempt - 1)) * (1 + random.uniform(0.1, 0.3))
                time.sleep(delay)

        raise GeminiRetryExhaustedError("Image gen sync retry exhausted", last_error=last_error)

class GenerateContentResponseWrapper:

    def __init__(self, response: Any, stream: bool = False):
        self._response = response
        self._stream = stream
        self._text = ""
        self._thought_text = ""
        self._chunks = []
        self._is_thought = False

        if not stream:

            if hasattr(response, 'candidates') and response.candidates:
                content = response.candidates[0].content
                parts = content.parts if content and hasattr(content, 'parts') and content.parts else []
                for part in parts:
                    if hasattr(part, 'thought') and part.thought:
                        self._thought_text += part.text if part.text else ""
                    elif part.text:
                        self._text += part.text
            elif hasattr(response, 'text'):
                self._text = response.text if response.text else ""

            if hasattr(response, 'candidates') and response.candidates:
                content = response.candidates[0].content
                parts = content.parts if content and hasattr(content, 'parts') and content.parts else []
                if len(parts) == 1 and hasattr(parts[0], 'thought'):
                    self._is_thought = parts[0].thought

    @property
    def text(self) -> str:
        if self._stream:
            return "".join(self._chunks)
        return self._text

    @property
    def thought(self) -> str:

        return self._thought_text

    @property
    def is_thought(self) -> bool:

        return self._is_thought

    def __iter__(self):
        if self._stream:
            for chunk in self._response:

                is_thought = False
                text_chunk = ""
                function_calls = []  # Support multiple function calls per chunk

                try:
                    if hasattr(chunk, 'candidates') and chunk.candidates:
                        candidate = chunk.candidates[0]
                        if hasattr(candidate, 'content') and candidate.content:
                            parts = candidate.content.parts if hasattr(candidate.content, 'parts') else []
                            for part in parts:
                                # Check for thought marker
                                if hasattr(part, 'thought') and part.thought:
                                    is_thought = True

                                # Extract text content
                                if hasattr(part, 'text') and part.text:
                                    text_chunk += part.text

                                # Extract function call (critical for tool execution)
                                if hasattr(part, 'function_call') and part.function_call:
                                    fc = part.function_call
                                    if fc.name:  # Valid function call must have a name
                                        function_calls.append({
                                            "name": fc.name,
                                            "args": dict(fc.args) if fc.args else {}
                                        })
                                        _logger.debug("Function call detected",
                                                     name=fc.name,
                                                     args_count=len(fc.args) if fc.args else 0)

                    elif hasattr(chunk, 'text') and chunk.text:
                        text_chunk = chunk.text

                except Exception as e:
                    _logger.warning("Chunk parsing error", error=str(e)[:100])
                    # Continue processing even if one chunk fails
                    continue

                # Yield each function call as a separate wrapper
                for fc in function_calls:
                    wrapper = GenerateContentResponseWrapper.__new__(GenerateContentResponseWrapper)
                    wrapper._response = chunk
                    wrapper._stream = False
                    wrapper._text = ""  # Function call chunks don't have text
                    wrapper._thought_text = ""
                    wrapper._chunks = []
                    wrapper._is_thought = False
                    wrapper._function_call = fc
                    yield wrapper

                # Yield text content if present (and no function call in this chunk)
                if text_chunk and not function_calls:
                    self._chunks.append(text_chunk)
                    wrapper = GenerateContentResponseWrapper.__new__(GenerateContentResponseWrapper)
                    wrapper._response = chunk
                    wrapper._stream = False
                    wrapper._text = text_chunk
                    wrapper._thought_text = ""
                    wrapper._chunks = []
                    wrapper._is_thought = is_thought
                    wrapper._function_call = None
                    yield wrapper
        else:
            yield self

    @property
    def function_call(self):
        """Return the function call if present, or None."""
        return getattr(self, '_function_call', None)
