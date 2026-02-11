"""W1-1/W1-3: M5 MetaMemory integration tests.

Tests record_access → get_hot_memories → get_channel_mentions flow.
"""

import pytest

from backend.memory.meta_memory import MetaMemory


class TestMetaMemoryRecordAccessFlow:
    """Test record_access → get_hot_memories pipeline."""

    def test_record_access_updates_hot_memories(self):
        meta = MetaMemory()
        meta.record_access(
            query_text="What is Python?",
            matched_memory_ids=["mem-001", "mem-002"],
            relevance_scores=[0.9, 0.7],
            channel_id="discord",
        )

        hot = meta.get_hot_memories(limit=5)
        assert len(hot) == 2
        assert hot[0]["access_count"] == 1
        assert hot[0]["channel_diversity"] == 1

    def test_multiple_accesses_increase_count(self):
        meta = MetaMemory()
        for _ in range(3):
            meta.record_access(
                query_text="test query",
                matched_memory_ids=["mem-001"],
                channel_id="discord",
            )

        hot = meta.get_hot_memories(limit=1)
        assert hot[0]["memory_id"] == "mem-001"
        assert hot[0]["access_count"] == 3

    def test_multi_channel_diversity(self):
        meta = MetaMemory()
        for ch in ["discord", "slack", "web"]:
            meta.record_access(
                query_text="test",
                matched_memory_ids=["mem-001"],
                channel_id=ch,
            )

        assert meta.get_channel_mentions("mem-001") == 3
        hot = meta.get_hot_memories(limit=1)
        assert hot[0]["channel_diversity"] == 3

    def test_hot_memories_ordered_by_access_count(self):
        meta = MetaMemory()
        meta.record_access(
            query_text="q1",
            matched_memory_ids=["mem-low"],
            channel_id="a",
        )
        for _ in range(5):
            meta.record_access(
                query_text="q2",
                matched_memory_ids=["mem-high"],
                channel_id="a",
            )

        hot = meta.get_hot_memories(limit=2)
        assert hot[0]["memory_id"] == "mem-high"
        assert hot[0]["access_count"] == 5
        assert hot[1]["memory_id"] == "mem-low"

    def test_get_channel_mentions_unknown_id(self):
        meta = MetaMemory()
        assert meta.get_channel_mentions("nonexistent") == 0

    def test_empty_meta_memory(self):
        meta = MetaMemory()
        assert meta.get_hot_memories(limit=5) == []
        assert meta.get_channel_mentions("any") == 0
