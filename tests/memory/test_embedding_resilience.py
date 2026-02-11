"""Tests for embedding service circuit breaker integration."""

import pytest
from unittest.mock import MagicMock
from backend.memory.permanent.embedding_service import EmbeddingService


class TestEmbeddingResilience:

    def test_breaker_opens_after_failures(self):
        client = MagicMock()
        client.models.embed_content.side_effect = RuntimeError("API down")

        svc = EmbeddingService(client=client)
        svc._breaker._failure_threshold = 3

        for _ in range(3):
            result = svc.get_embedding("test")
            assert result is None

        # Circuit should now be open
        result = svc.get_embedding("test")
        assert result is None
        # Should not have called embed_content again (circuit open)
        assert client.models.embed_content.call_count == 3

    def test_breaker_recovers(self):
        client = MagicMock()
        mock_result = MagicMock()
        mock_value = MagicMock()
        mock_value.values = [0.1] * 3072
        mock_result.embeddings = [mock_value]

        # First fail, then succeed
        client.models.embed_content.side_effect = [
            RuntimeError("fail"),
            RuntimeError("fail"),
            RuntimeError("fail"),
            mock_result,
        ]

        svc = EmbeddingService(client=client)
        svc._breaker._failure_threshold = 3
        svc._breaker._cooldown_sec = 0.1

        for _ in range(3):
            svc.get_embedding("test")

        import time
        time.sleep(0.15)

        # Should be in half-open, allow one probe
        result = svc.get_embedding("test after recovery")
        assert result is not None

    def test_normal_operation_unaffected(self, mock_genai_client):
        svc = EmbeddingService(client=mock_genai_client)
        result = svc.get_embedding("normal text")
        assert result is not None
        assert len(result) == 3072
