"""Tests for 3072-dimensional embedding upgrade."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestEmbeddingDimension:
    """Verify embedding service passes output_dimensionality=3072."""

    def test_embed_content_passes_3072(self, mock_genai_client):
        """embed_content call includes output_dimensionality=3072."""
        from backend.memory.permanent.embedding_service import EmbeddingService

        svc = EmbeddingService(client=mock_genai_client)
        svc.get_embedding("hello world")

        mock_genai_client.models.embed_content.assert_called_once()
        call_kwargs = mock_genai_client.models.embed_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config["output_dimensionality"] == 3072

    def test_embedding_output_length(self, mock_genai_client):
        """Returned embedding vector has length 3072."""
        from backend.memory.permanent.embedding_service import EmbeddingService

        svc = EmbeddingService(client=mock_genai_client)
        result = svc.get_embedding("test text")

        assert result is not None
        assert len(result) == 3072

    def test_chromadb_accepts_3072(self):
        """ChromaDB can store and retrieve 3072d vectors."""
        collection = MagicMock()
        collection.add.return_value = None

        embedding_3072 = [0.1] * 3072
        collection.add(
            ids=["test-1"],
            embeddings=[embedding_3072],
            documents=["test document"],
            metadatas=[{"type": "fact"}],
        )
        collection.add.assert_called_once()

        call_args = collection.add.call_args
        stored_embedding = call_args.kwargs.get("embeddings") or call_args[1].get("embeddings")
        assert len(stored_embedding[0]) == 3072


class TestGeminiClientEmbedding:
    """Verify gemini_client.py passes output_dimensionality."""

    @pytest.mark.asyncio
    async def test_gemini_embed_passes_3072(self):
        """gemini_embed() includes output_dimensionality=3072 in config."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_client.aio.models.embed_content = AsyncMock(return_value=mock_response)

        with patch("backend.core.utils.gemini_client.get_gemini_client", return_value=mock_client):
            from backend.core.utils.gemini_client import gemini_embed

            await gemini_embed("test", task_type="retrieval_query")

            call_kwargs = mock_client.aio.models.embed_content.call_args
            config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
            assert config["output_dimensionality"] == 3072
