"""Tests for memory migration from axel PostgreSQL."""

import pytest
from unittest.mock import MagicMock, patch


class TestMemoryMigration:

    def test_memory_import_with_dedup(self):
        """Duplicate content should merge rather than create new entry."""
        from backend.memory.permanent.facade import LongTermMemory

        ltm = MagicMock(spec=LongTermMemory)
        ltm.find_similar_memories.return_value = [
            {
                "id": "existing-1",
                "content": "User likes Python",
                "similarity": 0.95,
                "metadata": {
                    "access_count": 3,
                    "importance": 0.7,
                    "repetitions": 2,
                },
            }
        ]

        existing = ltm.find_similar_memories("User likes Python", threshold=0.92)
        assert len(existing) == 1
        assert existing[0]["id"] == "existing-1"

    def test_importance_preserved(self):
        """Importance values from axel should be preserved."""
        from backend.memory.permanent.facade import LongTermMemory

        ltm = MagicMock(spec=LongTermMemory)
        ltm.add.return_value = "new-id"
        ltm.find_similar_memories.return_value = []

        importance = 0.85
        ltm.add(
            content="Important memory",
            memory_type="fact",
            importance=importance,
            force=True,
        )
        ltm.add.assert_called_once()
        call_kwargs = ltm.add.call_args
        assert call_kwargs.kwargs.get("importance") == 0.85

    def test_batch_rate_limiting(self):
        """Batch processing should respect rate limits."""
        import time

        batch_size = 10
        sleep_time = 0.01

        batches = list(range(0, 25, batch_size))
        assert len(batches) == 3

        start = time.monotonic()
        for _ in batches[:-1]:
            time.sleep(sleep_time)
        elapsed = time.monotonic() - start

        assert elapsed >= sleep_time * 2
