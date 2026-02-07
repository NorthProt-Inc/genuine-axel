"""Tests for LongTermMemory facade."""

import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, "/home/northprot/projects/axnmihn")

from backend.memory.permanent.facade import LongTermMemory, PromotionCriteria
from backend.memory.permanent.embedding_service import EmbeddingService
from backend.memory.permanent.repository import ChromaDBRepository
from backend.memory.permanent.config import MemoryConfig


class TestPromotionCriteria:
    """Test cases for PromotionCriteria."""

    def test_force_promotion(self):
        """Force flag should always promote."""
        should, reason = PromotionCriteria.should_promote(
            content="test",
            repetitions=0,
            importance=0.1,
            force=True,
        )
        assert should is True
        assert reason == "forced_promotion"

    def test_repetition_threshold(self):
        """High repetitions should promote."""
        should, reason = PromotionCriteria.should_promote(
            content="test",
            repetitions=MemoryConfig.MIN_REPETITIONS,
            importance=0.1,
        )
        assert should is True
        assert "repetitions" in reason

    def test_importance_threshold(self):
        """High importance should promote."""
        should, reason = PromotionCriteria.should_promote(
            content="test",
            repetitions=0,
            importance=MemoryConfig.MIN_IMPORTANCE,
        )
        assert should is True
        assert "importance" in reason

    def test_low_importance_rejection(self):
        """Low importance without repetitions should reject."""
        should, reason = PromotionCriteria.should_promote(
            content="test",
            repetitions=0,
            importance=0.1,
        )
        assert should is False
        assert "low_importance" in reason


class TestLongTermMemoryFacade:
    """Test cases for LongTermMemory facade (unit tests with mocks)."""

    @pytest.fixture
    def mock_ltm(self, mock_chromadb_collection, mock_genai_client):
        """Create LongTermMemory with mocked components."""
        ltm = object.__new__(LongTermMemory)

        # Set up mock repository
        mock_repo = MagicMock(spec=ChromaDBRepository)
        mock_repo.get_all.return_value = {"ids": [], "metadatas": []}
        mock_repo.count.return_value = 0
        mock_repo._collection = mock_chromadb_collection
        ltm._repository = mock_repo

        # Set up mock embedding service
        mock_embed = MagicMock(spec=EmbeddingService)
        mock_embed.get_embedding.return_value = [0.1] * 768
        mock_embed.client = mock_genai_client
        ltm._embedding_service = mock_embed

        # Set up other attributes
        ltm._decay_calculator = MagicMock()
        ltm._consolidator = MagicMock()
        ltm._repetition_cache = {}
        ltm._pending_access_updates = set()
        ltm._last_flush_time = 0
        ltm.db_path = "/tmp/test"
        ltm.embedding_model = "test-model"

        return ltm

    def test_get_all_memories(self, mock_ltm):
        """get_all_memories should delegate to repository."""
        mock_ltm._repository.get_all.return_value = {
            "ids": ["mem-001"],
            "documents": ["Test"],
            "metadatas": [{"type": "fact"}],
        }

        result = mock_ltm.get_all_memories()

        assert "ids" in result
        mock_ltm._repository.get_all.assert_called()

    def test_delete_memories(self, mock_ltm):
        """delete_memories should delegate to repository."""
        mock_ltm._repository.delete.return_value = 2

        result = mock_ltm.delete_memories(["mem-001", "mem-002"])

        assert result == 2
        mock_ltm._repository.delete.assert_called_once_with(["mem-001", "mem-002"])

    def test_find_similar_memories(self, mock_ltm):
        """find_similar_memories should return similar content."""
        mock_ltm._repository.query_by_embedding.return_value = [
            {"id": "mem-001", "content": "Test", "metadata": {}, "similarity": 0.9},
            {"id": "mem-002", "content": "Test2", "metadata": {}, "similarity": 0.7},
        ]

        result = mock_ltm.find_similar_memories("test content", threshold=0.8)

        assert len(result) == 1  # Only 0.9 >= 0.8
        assert result[0]["id"] == "mem-001"

    def test_get_embedding_for_text(self, mock_ltm):
        """get_embedding_for_text should return embedding vector."""
        result = mock_ltm.get_embedding_for_text("test")

        assert result is not None
        assert len(result) == 768
        mock_ltm._embedding_service.get_embedding.assert_called_once()

    def test_backward_compatible_collection_property(self, mock_ltm):
        """collection property should expose underlying ChromaDB collection."""
        # The collection property delegates to repository.collection
        collection = mock_ltm.collection

        # Verify it's calling the repository's collection property
        assert collection is mock_ltm._repository.collection

    def test_get_stats(self, mock_ltm):
        """get_stats should return memory statistics."""
        mock_ltm._repository.count.return_value = 10
        mock_ltm._repository.get_all.return_value = {
            "ids": ["1", "2"],
            "metadatas": [{"type": "fact"}, {"type": "preference"}],
        }

        stats = mock_ltm.get_stats()

        assert "total_memories" in stats
        assert stats["total_memories"] == 10
        assert "by_type" in stats

    def test_flush_access_updates(self, mock_ltm):
        """flush_access_updates should update pending access times."""
        mock_ltm._pending_access_updates = {"mem-001", "mem-002"}
        mock_ltm._repository.update_metadata.return_value = True

        updated = mock_ltm.flush_access_updates()

        assert updated == 2
        assert len(mock_ltm._pending_access_updates) == 0

    def test_consolidate_memories_delegates(self, mock_ltm):
        """consolidate_memories should delegate to consolidator."""
        mock_ltm._consolidator.consolidate.return_value = {"deleted": 1, "preserved": 2}

        result = mock_ltm.consolidate_memories()

        assert result["deleted"] == 1
        mock_ltm._consolidator.consolidate.assert_called_once()
