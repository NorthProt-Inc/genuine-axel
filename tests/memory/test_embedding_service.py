"""Tests for EmbeddingService."""

import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/home/northprot/projects/axnmihn")

# Direct import to avoid circular dependencies during incremental development
from backend.memory.permanent.embedding_service import EmbeddingService


class TestEmbeddingService:
    """Test cases for EmbeddingService."""

    def test_get_embedding_returns_vector(self, mock_genai_wrapper):
        """Embedding generation should return a vector."""
        service = EmbeddingService(genai_wrapper=mock_genai_wrapper)
        result = service.get_embedding("Hello world")

        assert result is not None
        assert len(result) == 768
        mock_genai_wrapper.embed_content_sync.assert_called_once()

    def test_embedding_cache_hit(self, mock_genai_wrapper):
        """Same text should return cached embedding."""
        service = EmbeddingService(genai_wrapper=mock_genai_wrapper)

        # First call
        result1 = service.get_embedding("Hello world")
        # Second call with same text
        result2 = service.get_embedding("Hello world")

        assert result1 == result2
        # Should only call API once due to cache
        assert mock_genai_wrapper.embed_content_sync.call_count == 1

    def test_different_task_type_not_cached(self, mock_genai_wrapper):
        """Different task_type should not use cached result."""
        service = EmbeddingService(genai_wrapper=mock_genai_wrapper)

        service.get_embedding("Hello world", task_type="retrieval_document")
        service.get_embedding("Hello world", task_type="retrieval_query")

        # Should call API twice for different task types
        assert mock_genai_wrapper.embed_content_sync.call_count == 2

    def test_embedding_cache_eviction(self, mock_genai_wrapper):
        """Cache should evict oldest entries when full."""
        service = EmbeddingService(
            genai_wrapper=mock_genai_wrapper,
            cache_size=3,  # Small cache for testing
        )

        # Fill cache
        service.get_embedding("text1")
        service.get_embedding("text2")
        service.get_embedding("text3")

        # This should evict text1
        service.get_embedding("text4")

        # text1 should no longer be cached
        mock_genai_wrapper.embed_content_sync.reset_mock()
        service.get_embedding("text1")
        assert mock_genai_wrapper.embed_content_sync.call_count == 1

    def test_rate_limit_retry(self, mock_genai_wrapper, mock_rate_limiter):
        """Should retry when rate limited."""
        # First call fails, second succeeds
        mock_rate_limiter.try_acquire.side_effect = [False, False, True]

        with patch(
            "backend.memory.permanent.embedding_service.get_embedding_limiter",
            return_value=mock_rate_limiter,
        ):
            service = EmbeddingService(genai_wrapper=mock_genai_wrapper)
            result = service.get_embedding("Hello world")

        assert result is not None
        assert mock_rate_limiter.try_acquire.call_count == 3

    def test_embedding_error_returns_none(self, mock_genai_wrapper):
        """API error should return None."""
        mock_genai_wrapper.embed_content_sync.side_effect = Exception("API Error")

        service = EmbeddingService(genai_wrapper=mock_genai_wrapper)
        result = service.get_embedding("Hello world")

        assert result is None

    def test_no_genai_wrapper_returns_none(self):
        """Should return None when genai_wrapper is not available."""
        service = EmbeddingService(genai_wrapper=None)
        result = service.get_embedding("Hello world")

        assert result is None

    def test_clear_cache(self, mock_genai_wrapper):
        """clear_cache should empty the cache and return count."""
        service = EmbeddingService(genai_wrapper=mock_genai_wrapper)

        service.get_embedding("text1")
        service.get_embedding("text2")

        cleared = service.clear_cache()

        assert cleared == 2
        assert len(service._cache) == 0
