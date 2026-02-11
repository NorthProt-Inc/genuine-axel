"""Tests for T-07: M5 Meta Memory (Access Pattern Tracking)."""

import pytest

from backend.memory.meta_memory import MetaMemory
from backend.memory.recent.connection import SQLiteConnectionManager
from backend.memory.recent.schema import SchemaManager


@pytest.fixture
def meta_memory():
    """In-memory-only MetaMemory (no persistence)."""
    return MetaMemory(conn_mgr=None)


@pytest.fixture
def meta_memory_with_db(tmp_path):
    """MetaMemory with SQLite persistence."""
    conn_mgr = SQLiteConnectionManager(db_path=tmp_path / "test_meta.db")
    SchemaManager(conn_mgr).initialize()
    mm = MetaMemory(conn_mgr=conn_mgr)
    yield mm
    conn_mgr.close()


class TestRecordAndGetHot:

    def test_record_and_get_hot(self, meta_memory):
        """Record access for 3 memories, hot memories returns in order."""
        meta_memory.record_access("query about python", ["mem-1", "mem-2"])
        meta_memory.record_access("another query", ["mem-1", "mem-3"])
        meta_memory.record_access("third query", ["mem-1"])

        hot = meta_memory.get_hot_memories(limit=10)

        assert len(hot) == 3
        # mem-1 accessed 3 times → most hot
        assert hot[0]["memory_id"] == "mem-1"
        assert hot[0]["access_count"] == 3

    def test_hot_memories_limit(self, meta_memory):
        """Limit parameter works correctly."""
        for i in range(20):
            meta_memory.record_access(f"query {i}", [f"mem-{i}"])

        hot = meta_memory.get_hot_memories(limit=5)
        assert len(hot) == 5


class TestChannelMentionsCount:

    def test_channel_mentions_count(self, meta_memory):
        """Same memory accessed from different channels → correct count."""
        meta_memory.record_access("q1", ["mem-1"], channel_id="discord")
        meta_memory.record_access("q2", ["mem-1"], channel_id="voice")
        meta_memory.record_access("q3", ["mem-1"], channel_id="discord")  # Duplicate channel

        assert meta_memory.get_channel_mentions("mem-1") == 2  # discord + voice
        assert meta_memory.get_channel_mentions("mem-1") == 2  # Idempotent

    def test_channel_mentions_unknown_memory(self, meta_memory):
        """Unknown memory ID returns 0 channels."""
        assert meta_memory.get_channel_mentions("nonexistent") == 0

    def test_channel_diversity_in_hot(self, meta_memory):
        """Hot memories include channel_diversity field."""
        meta_memory.record_access("q1", ["mem-1"], channel_id="ch-a")
        meta_memory.record_access("q2", ["mem-1"], channel_id="ch-b")
        meta_memory.record_access("q3", ["mem-1"], channel_id="ch-c")

        hot = meta_memory.get_hot_memories()
        assert hot[0]["channel_diversity"] == 3


class TestPruneOldPatterns:

    def test_prune_old_patterns(self, meta_memory_with_db):
        """Prune removes old patterns from SQLite."""
        # Record a pattern (it will be fresh, not old)
        meta_memory_with_db.record_access("test query", ["mem-1"])

        # Pruning with 0 days threshold should delete it
        deleted = meta_memory_with_db.prune_old_patterns(older_than_days=0)
        assert deleted >= 1

    def test_prune_without_db_returns_zero(self, meta_memory):
        """Prune on memory-only instance returns 0."""
        meta_memory.record_access("test", ["mem-1"])
        assert meta_memory.prune_old_patterns() == 0


class TestEmptyAccessReturnsEmpty:

    def test_empty_access_returns_empty(self, meta_memory):
        """No records → empty hot memories."""
        assert meta_memory.get_hot_memories() == []
        assert meta_memory.stats["tracked_memories"] == 0
        assert meta_memory.stats["total_patterns"] == 0
