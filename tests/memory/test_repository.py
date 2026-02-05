"""Tests for ChromaDBRepository."""

import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, "/home/northprot/projects/axnmihn")

from backend.memory.permanent.repository import ChromaDBRepository


class TestChromaDBRepository:
    """Test cases for ChromaDBRepository."""

    def test_add_memory(self, mock_chromadb_client, sample_embedding):
        """Adding memory should return document ID."""
        repo = ChromaDBRepository(client=mock_chromadb_client)

        doc_id = repo.add(
            content="Test memory content",
            embedding=sample_embedding,
            metadata={"type": "fact", "importance": 0.8},
        )

        assert doc_id is not None
        mock_chromadb_client.get_or_create_collection().add.assert_called_once()

    def test_get_all_memories(self, mock_chromadb_client, populated_chromadb_collection):
        """get_all should return all memories."""
        mock_chromadb_client.get_or_create_collection.return_value = populated_chromadb_collection
        repo = ChromaDBRepository(client=mock_chromadb_client)

        result = repo.get_all()

        assert "ids" in result
        assert "documents" in result
        assert len(result["ids"]) == 3

    def test_get_by_id(self, mock_chromadb_client, mock_chromadb_collection):
        """get_by_id should return specific memory."""
        mock_chromadb_collection.get.return_value = {
            "ids": ["mem-001"],
            "documents": ["Test content"],
            "metadatas": [{"type": "fact"}],
        }
        mock_chromadb_client.get_or_create_collection.return_value = mock_chromadb_collection
        repo = ChromaDBRepository(client=mock_chromadb_client)

        result = repo.get_by_id("mem-001")

        assert result is not None
        assert result["id"] == "mem-001"
        assert result["content"] == "Test content"

    def test_get_by_id_not_found(self, mock_chromadb_client, mock_chromadb_collection):
        """get_by_id should return None for non-existent ID."""
        mock_chromadb_collection.get.return_value = {
            "ids": [],
            "documents": [],
            "metadatas": [],
        }
        mock_chromadb_client.get_or_create_collection.return_value = mock_chromadb_collection
        repo = ChromaDBRepository(client=mock_chromadb_client)

        result = repo.get_by_id("non-existent")

        assert result is None

    def test_query_by_embedding(self, mock_chromadb_client, mock_chromadb_collection, sample_embedding):
        """query_by_embedding should return similar memories."""
        mock_chromadb_collection.query.return_value = {
            "ids": [["mem-001", "mem-002"]],
            "documents": [["Memory 1", "Memory 2"]],
            "metadatas": [[{"type": "fact"}, {"type": "preference"}]],
            "distances": [[0.1, 0.3]],
        }
        mock_chromadb_client.get_or_create_collection.return_value = mock_chromadb_collection
        repo = ChromaDBRepository(client=mock_chromadb_client)

        results = repo.query_by_embedding(embedding=sample_embedding, n_results=5)

        assert len(results) == 2
        assert results[0]["id"] == "mem-001"
        assert results[0]["similarity"] == 0.9  # 1 - 0.1

    def test_update_metadata(self, mock_chromadb_client, mock_chromadb_collection):
        """update_metadata should update and return True."""
        mock_chromadb_client.get_or_create_collection.return_value = mock_chromadb_collection
        repo = ChromaDBRepository(client=mock_chromadb_client)

        result = repo.update_metadata("mem-001", {"last_accessed": "2024-01-01"})

        assert result is True
        mock_chromadb_collection.update.assert_called_once()

    def test_delete_memories(self, mock_chromadb_client, mock_chromadb_collection):
        """delete should remove memories and return count."""
        mock_chromadb_client.get_or_create_collection.return_value = mock_chromadb_collection
        repo = ChromaDBRepository(client=mock_chromadb_client)

        result = repo.delete(["mem-001", "mem-002"])

        assert result == 2
        mock_chromadb_collection.delete.assert_called_once_with(ids=["mem-001", "mem-002"])

    def test_delete_empty_list(self, mock_chromadb_client, mock_chromadb_collection):
        """delete with empty list should return 0."""
        mock_chromadb_client.get_or_create_collection.return_value = mock_chromadb_collection
        repo = ChromaDBRepository(client=mock_chromadb_client)

        result = repo.delete([])

        assert result == 0
        mock_chromadb_collection.delete.assert_not_called()

    def test_count(self, mock_chromadb_client, mock_chromadb_collection):
        """count should return total memory count."""
        mock_chromadb_collection.count.return_value = 42
        mock_chromadb_client.get_or_create_collection.return_value = mock_chromadb_collection
        repo = ChromaDBRepository(client=mock_chromadb_client)

        result = repo.count()

        assert result == 42
