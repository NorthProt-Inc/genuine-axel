"""Tests for asymmetric embedding task types."""

import pytest
from unittest.mock import MagicMock, call


class TestAsymmetricEmbedding:

    def test_storage_uses_document_type(self, mock_genai_client):
        """Storage embedding uses retrieval_document task type."""
        from backend.memory.permanent.embedding_service import EmbeddingService

        svc = EmbeddingService(client=mock_genai_client)
        svc.get_embedding("test content", task_type="retrieval_document")

        call_kwargs = mock_genai_client.models.embed_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config["task_type"] == "retrieval_document"

    def test_search_uses_query_type(self, mock_genai_client):
        """Search embedding uses retrieval_query task type."""
        from backend.memory.permanent.embedding_service import EmbeddingService

        svc = EmbeddingService(client=mock_genai_client)
        svc.get_embedding("search query", task_type="retrieval_query")

        call_kwargs = mock_genai_client.models.embed_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config["task_type"] == "retrieval_query"

    def test_different_task_types_different_cache_keys(self, mock_genai_client):
        """Same text with different task_types should have different cache keys."""
        from backend.memory.permanent.embedding_service import EmbeddingService

        svc = EmbeddingService(client=mock_genai_client)
        svc.get_embedding("test", task_type="retrieval_document")
        svc.get_embedding("test", task_type="retrieval_query")

        # Should be called twice (different cache keys)
        assert mock_genai_client.models.embed_content.call_count == 2
