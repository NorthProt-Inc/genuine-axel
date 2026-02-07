"""Gemini SDK client singleton and async helpers.

Replaces gemini_wrapper.py — no ThreadPoolExecutor, no sync wrappers.
Uses google-genai native async (client.aio) and native timeout (HttpOptions).
"""

import asyncio
import os
from typing import Any

from google import genai
from google.genai import types

from backend.core.logging import get_logger
from backend.core.utils.lazy import Lazy

_log = get_logger("gemini_client")

_DEFAULT_TIMEOUT_MS = 180_000  # 180s


def _create_client() -> genai.Client:
    """Create a genai.Client with HttpOptions timeout."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 환경변수가 필요합니다")
    _log.info("genai.Client 생성 시작")
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=_DEFAULT_TIMEOUT_MS),
    )
    _log.info("genai.Client 생성 완료")
    return client


_singleton_client: Lazy[genai.Client] = Lazy(_create_client)


def get_gemini_client() -> genai.Client:
    """Get the singleton genai.Client instance."""
    return _singleton_client.get()


def get_model_name() -> str:
    """Get the default Gemini model name from config."""
    from backend.config import DEFAULT_GEMINI_MODEL

    return DEFAULT_GEMINI_MODEL


async def gemini_generate(
    contents: Any,
    *,
    model: str | None = None,
    config: types.GenerateContentConfig | None = None,
    timeout_seconds: float = 180.0,
) -> types.GenerateContentResponse:
    """Async generate with per-call timeout.

    Args:
        contents: Prompt string or list of Content objects
        model: Model name override (default: DEFAULT_GEMINI_MODEL)
        config: GenerateContentConfig for temperature, thinking, tools, etc.
        timeout_seconds: Per-call timeout in seconds

    Returns:
        Raw SDK GenerateContentResponse
    """
    client = get_gemini_client()
    model = model or get_model_name()

    if isinstance(contents, str):
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=contents)])]

    return await asyncio.wait_for(
        client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        ),
        timeout=timeout_seconds,
    )


async def gemini_embed(
    contents: Any,
    *,
    model: str | None = None,
    task_type: str | None = None,
) -> types.EmbedContentResponse:
    """Async embedding helper.

    Args:
        contents: Text or list of texts to embed
        model: Embedding model name
        task_type: Embedding task type (retrieval_document, retrieval_query)

    Returns:
        Raw SDK EmbedContentResponse
    """
    client = get_gemini_client()
    from backend.memory.permanent.config import MemoryConfig

    model = model or MemoryConfig.EMBEDDING_MODEL

    embed_config: dict[str, Any] | None = None
    if task_type:
        embed_config = {"task_type": task_type}

    return await client.aio.models.embed_content(
        model=model,
        contents=contents,
        config=embed_config,
    )
