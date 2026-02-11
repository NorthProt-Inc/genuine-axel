"""Embedding generation service with caching."""

import asyncio
import hashlib
import time
from typing import Dict, List, Optional

from google import genai

from backend.config import EMBEDDING_MAX_RETRIES
from backend.core.logging import get_logger
from backend.core.utils.circuit_breaker import EMBEDDING_CIRCUIT
from .config import MemoryConfig

_log = get_logger("memory.embedding")


def get_embedding_limiter():
    """Get rate limiter for embedding API calls."""
    from backend.core.utils.rate_limiter import get_embedding_limiter

    return get_embedding_limiter()


class EmbeddingService:
    """Service for generating text embeddings with caching.

    Handles:
    - Embedding generation via Gemini API
    - LRU cache for repeated queries
    - Rate limiting with retries
    """

    def __init__(
        self,
        client: genai.Client | None = None,
        embedding_model: str | None = None,
        cache_size: int | None = None,
    ):
        """Initialize embedding service.

        Args:
            client: genai.Client instance
            embedding_model: Model name for embeddings
            cache_size: Maximum cache entries (default from MemoryConfig)
        """
        self.client = client
        self.embedding_model = embedding_model or MemoryConfig.EMBEDDING_MODEL
        self._cache_size = cache_size or MemoryConfig.EMBEDDING_CACHE_SIZE
        self._cache: Dict[str, List[float]] = {}
        self._breaker = EMBEDDING_CIRCUIT

    def get_embedding(
        self,
        text: str,
        task_type: str = "retrieval_document",
    ) -> Optional[List[float]]:
        """Generate embedding vector for text.

        Args:
            text: Input text to embed (truncated to first 500 chars for cache key)
            task_type: Embedding task type (retrieval_document, retrieval_query)

        Returns:
            3072-dimensional embedding vector or None on failure
        """
        if not self.client:
            _log.warning("GenAI client not available for embedding")
            return None

        if not self._breaker.can_execute():
            _log.warning("Embedding circuit open, returning None")
            return None

        # PERF-027: Use deterministic hash for cache key
        cache_key = f"{hashlib.sha256(text[:500].encode()).hexdigest()[:16]}:{task_type}"

        if cache_key in self._cache:
            # PERF-027: True LRU - move accessed key to end
            self._cache[cache_key] = self._cache.pop(cache_key)
            _log.debug("MEM embed cache_hit")
            return self._cache[cache_key]

        # Rate limiting
        self._wait_for_rate_limit()

        try:
            result = self.client.models.embed_content(
                model=self.embedding_model,
                contents=text,
                config={"task_type": task_type, "output_dimensionality": 3072},
            )
            if result.embeddings is None:
                return None
            embedding = result.embeddings[0].values

            # Cache with LRU eviction
            self._cache_with_eviction(cache_key, embedding)  # type: ignore[arg-type]
            self._breaker.record_success()

            return embedding

        except Exception as e:
            self._breaker.record_failure()
            _log.error(
                "Embedding generation failed",
                error=str(e),
                model=self.embedding_model,
                text_len=len(text),
                error_type=type(e).__name__,
            )
            return None

    def _wait_for_rate_limit(self) -> None:
        """Wait for rate limiter token with retries (blocking version)."""
        try:
            limiter = get_embedding_limiter()
            for attempt in range(EMBEDDING_MAX_RETRIES):
                if limiter.try_acquire():
                    break

                if attempt < EMBEDDING_MAX_RETRIES - 1:
                    _log.debug("Rate limit: waiting for token", attempt=attempt + 1)
                    # PERF-027: Note - still blocking sleep, but async version available
                    time.sleep(0.5)
                else:
                    _log.warning("Rate limit: proceeding without token after retries")

        except ImportError:
            pass  # Rate limiter not available

    async def _wait_for_rate_limit_async(self) -> None:
        """Wait for rate limiter token with retries (async version for PERF-027)."""
        try:
            limiter = get_embedding_limiter()
            for attempt in range(EMBEDDING_MAX_RETRIES):
                if limiter.try_acquire():
                    break

                if attempt < EMBEDDING_MAX_RETRIES - 1:
                    _log.debug("Rate limit: waiting for token", attempt=attempt + 1)
                    await asyncio.sleep(0.5)
                else:
                    _log.warning("Rate limit: proceeding without token after retries")

        except ImportError:
            pass  # Rate limiter not available

    def _cache_with_eviction(self, key: str, value: List[float]) -> None:
        """Add to cache with LRU eviction if full."""
        if len(self._cache) >= self._cache_size:
            # Remove oldest entry (first key in dict)
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[key] = value

    def clear_cache(self) -> int:
        """Clear embedding cache.

        Returns:
            Number of cached entries cleared
        """
        count = len(self._cache)
        self._cache.clear()
        return count
