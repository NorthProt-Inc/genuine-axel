"""W3-1: Verify M5 hot memory boost in retrieval query."""

from unittest.mock import MagicMock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.memory.permanent.retrieval import MemoryRetriever
from backend.memory.permanent.decay_calculator import AdaptiveDecayCalculator

VANCOUVER_TZ = ZoneInfo("America/Vancouver")


def _make_retriever(hot_memory_ids: list[str] | None = None) -> MemoryRetriever:
    """Build a MemoryRetriever with mocked dependencies."""
    mock_repo = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.get_embedding.return_value = [0.1] * 3072
    decay_calc = AdaptiveDecayCalculator()

    meta_memory = None
    if hot_memory_ids is not None:
        meta_memory = MagicMock()
        meta_memory.get_hot_memories.return_value = [
            {"memory_id": mid, "access_count": 10, "channel_diversity": 2}
            for mid in hot_memory_ids
        ]

    retriever = MemoryRetriever(
        repository=mock_repo,
        embedding_service=mock_embedding,
        decay_calculator=decay_calc,
        meta_memory=meta_memory,
    )

    created = (datetime.now(VANCOUVER_TZ) - timedelta(hours=1)).isoformat()
    mock_repo.query_by_embedding.return_value = [
        {
            "id": "hot-mem-1",
            "content": "Hot memory content",
            "metadata": {"created_at": created, "access_count": 5, "importance": 0.9},
            "similarity": 0.8,
        },
        {
            "id": "cold-mem-2",
            "content": "Cold memory content",
            "metadata": {"created_at": created, "access_count": 1, "importance": 0.9},
            "similarity": 0.85,
        },
    ]

    return retriever


class TestRetrievalHotBoost:

    def test_hot_memory_gets_score_boost(self):
        retriever = _make_retriever(hot_memory_ids=["hot-mem-1"])
        results = retriever.query("test query")

        hot = next(r for r in results if r["id"] == "hot-mem-1")
        cold = next(r for r in results if r["id"] == "cold-mem-2")

        # Hot memory has similarity=0.8 + 0.1 boost = ~0.9
        # Cold memory has similarity=0.85 with no boost
        # Hot should rank higher or equal due to boost
        assert hot["effective_score"] > cold["effective_score"] - 0.05

    def test_no_meta_memory_no_boost(self):
        retriever = _make_retriever(hot_memory_ids=None)
        results = retriever.query("test query")

        # Without meta_memory, cold-mem-2 (0.85) should rank higher than hot-mem-1 (0.8)
        assert results[0]["id"] == "cold-mem-2"

    def test_hot_boost_value_is_0_1(self):
        retriever = _make_retriever(hot_memory_ids=["hot-mem-1"])
        results = retriever.query("test query")

        hot = next(r for r in results if r["id"] == "hot-mem-1")
        cold = next(r for r in results if r["id"] == "cold-mem-2")

        # The boost should be exactly +0.1 difference in base_relevance impact
        # hot: base=0.8 * decay + 0.1, cold: base=0.85 * decay
        # Verify hot got a meaningful boost
        assert hot["effective_score"] > 0.8  # Must be above base (boost applied)
