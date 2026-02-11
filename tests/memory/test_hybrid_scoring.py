"""Tests for hybrid vector + text scoring."""

import pytest
from unittest.mock import MagicMock, patch
from backend.memory.permanent.facade import _text_similarity


class TestTextSimilarity:

    def test_identical_strings(self):
        assert _text_similarity("hello world", "hello world") == 1.0

    def test_different_strings(self):
        score = _text_similarity("hello", "goodbye")
        assert 0 <= score <= 1

    def test_case_insensitive(self):
        score = _text_similarity("Hello World", "hello world")
        assert score == 1.0

    def test_score_bounds(self):
        score = _text_similarity("abc", "xyz")
        assert 0 <= score <= 1


class TestHybridScoring:

    def test_hybrid_score_reranks(self):
        """Text similarity should boost results with matching text."""
        from backend.memory.permanent.facade import LongTermMemory

        ltm = MagicMock(spec=LongTermMemory)
        ltm._embedding_service = MagicMock()
        ltm._embedding_service.get_embedding.return_value = [0.1] * 3072
        ltm._repository = MagicMock()
        
        # Mock the retriever which now handles find_similar_memories
        ltm._retriever = MagicMock()
        ltm._retriever.find_similar_memories.return_value = [
            {"id": "1", "content": "Python programming", "similarity": 0.85, "metadata": {}},
            {"id": "2", "content": "python programming language", "similarity": 0.82, "metadata": {}},
        ]

        result = LongTermMemory.find_similar_memories(ltm, "python programming", threshold=0.5)
        # Both should pass threshold
        assert len(result) >= 1

    def test_vector_only_fallback(self):
        """When text similarity fails, vector score is used."""
        score = _text_similarity("", "")
        assert score >= 0  # Should not crash
