"""Tests for T-04: Consolidation Dedup (Cosine Similarity)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.memory.memgpt import MemGPTManager, MemGPTConfig, SemanticKnowledge


def _make_memgpt_manager(
    *,
    find_similar_return=None,
    all_memories=None,
):
    """Create MemGPTManager with mocked long-term memory."""
    long_term = MagicMock()
    long_term.find_similar_memories.return_value = find_similar_return or []
    long_term.add.return_value = None
    long_term._repository = MagicMock()
    long_term._repository.update_metadata.return_value = None

    if all_memories is None:
        all_memories = {"ids": [], "metadatas": [], "documents": []}
    long_term.get_all_memories.return_value = all_memories

    client = MagicMock()
    mgr = MemGPTManager(
        long_term_memory=long_term,
        client=client,
        model_name="test-model",
    )
    return mgr, long_term


class TestDuplicateNotStoredTwice:

    @pytest.mark.asyncio
    async def test_duplicate_not_stored_twice(self):
        """Same content consolidated twice → existing memory updated, not new one added."""
        existing_memory = {
            "id": "existing-001",
            "metadata": {"repetitions": 1},
            "similarity": 0.95,
        }
        mgr, lt = _make_memgpt_manager(find_similar_return=[existing_memory])

        # Mock _extract_semantic_knowledge to return a known SemanticKnowledge
        semantic = SemanticKnowledge(
            knowledge="User prefers Python over JavaScript",
            confidence=0.9,
            source_count=3,
            topics=["programming"],
        )
        mgr._extract_semantic_knowledge = AsyncMock(return_value=semantic)

        # Setup all_memories to trigger grouping
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        old_time = (datetime.now(ZoneInfo("America/Vancouver")) - timedelta(days=10)).isoformat()
        mgr.long_term.get_all_memories.return_value = {
            "ids": ["ep-1", "ep-2"],
            "metadatas": [
                {"created_at": old_time, "repetitions": 2, "type": "conversation", "key_topics": ["programming"]},
                {"created_at": old_time, "repetitions": 2, "type": "conversation", "key_topics": ["programming"]},
            ],
            "documents": ["I like Python", "Python is great"],
        }

        result = await mgr.episodic_to_semantic(dry_run=False)

        # Should update existing, NOT add new
        lt._repository.update_metadata.assert_called()
        update_call = lt._repository.update_metadata.call_args
        assert update_call[0][0] == "existing-001"
        assert update_call[0][1]["repetitions"] == 2

        # long_term.add should NOT be called
        lt.add.assert_not_called()


class TestDissimilarStoredSeparately:

    @pytest.mark.asyncio
    async def test_dissimilar_stored_separately(self):
        """Different content → no existing match → add as new."""
        mgr, lt = _make_memgpt_manager(find_similar_return=[])  # No similar found

        semantic = SemanticKnowledge(
            knowledge="User enjoys hiking on weekends",
            confidence=0.85,
            source_count=2,
            topics=["hobbies"],
        )
        mgr._extract_semantic_knowledge = AsyncMock(return_value=semantic)

        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        old_time = (datetime.now(ZoneInfo("America/Vancouver")) - timedelta(days=10)).isoformat()
        mgr.long_term.get_all_memories.return_value = {
            "ids": ["ep-1", "ep-2"],
            "metadatas": [
                {"created_at": old_time, "repetitions": 2, "type": "conversation", "key_topics": ["hobbies"]},
                {"created_at": old_time, "repetitions": 2, "type": "conversation", "key_topics": ["hobbies"]},
            ],
            "documents": ["I went hiking", "The trail was beautiful"],
        }

        result = await mgr.episodic_to_semantic(dry_run=False)

        # Should add new semantic memory
        lt.add.assert_called_once()
        call_kwargs = lt.add.call_args[1]
        assert "Semantic Knowledge" in call_kwargs["content"]
        assert call_kwargs["memory_type"] == "semantic"


class TestThresholdBoundary:

    @pytest.mark.asyncio
    async def test_threshold_boundary_below(self):
        """Similarity 0.91 (below 0.92 threshold) → treated as different, add new."""
        # find_similar_memories returns empty because threshold is 0.92
        mgr, lt = _make_memgpt_manager(find_similar_return=[])

        semantic = SemanticKnowledge(
            knowledge="Near duplicate but not quite",
            confidence=0.8,
            source_count=2,
            topics=["test"],
        )
        mgr._extract_semantic_knowledge = AsyncMock(return_value=semantic)

        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        old_time = (datetime.now(ZoneInfo("America/Vancouver")) - timedelta(days=10)).isoformat()
        mgr.long_term.get_all_memories.return_value = {
            "ids": ["ep-1", "ep-2"],
            "metadatas": [
                {"created_at": old_time, "repetitions": 2, "type": "conversation", "key_topics": ["test"]},
                {"created_at": old_time, "repetitions": 2, "type": "conversation", "key_topics": ["test"]},
            ],
            "documents": ["content A", "content B"],
        }

        await mgr.episodic_to_semantic(dry_run=False)
        lt.add.assert_called_once()
