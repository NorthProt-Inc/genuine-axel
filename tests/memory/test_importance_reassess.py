"""W5-2: Test importance reassessment during consolidation."""

from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone


from backend.memory.permanent.consolidator import MemoryConsolidator
from backend.memory.permanent.config import MemoryConfig


def _make_consolidator(memories, conn_mgr=None):
    """Build consolidator with mock repository containing given memories."""
    repo = MagicMock()
    ids = [m["id"] for m in memories]
    metadatas = [m["metadata"] for m in memories]
    repo.get_all.return_value = {"ids": ids, "metadatas": metadatas}
    repo.delete.return_value = 0
    repo.batch_update_metadata.return_value = len(ids)

    decay_calc = MagicMock()
    decay_calc.calculate_batch.return_value = [
        m["metadata"].get("importance", 0.5) for m in memories
    ]

    consolidator = MemoryConsolidator(
        repository=repo,
        decay_calculator=decay_calc,
        conn_mgr=conn_mgr,
    )
    return consolidator, repo


def test_reassess_config_values():
    """REASSESS constants should be accessible in MemoryConfig."""
    assert MemoryConfig.REASSESS_AGE_HOURS == 168
    assert MemoryConfig.REASSESS_BATCH_SIZE == 50


def test_reassess_old_high_access_memories():
    """Old memories with high access_count should be reassessed."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=200)).isoformat()
    memories = [
        {
            "id": "mem-old-1",
            "metadata": {
                "importance": 0.4,
                "repetitions": 1,
                "access_count": 10,
                "created_at": old_time,
                "last_accessed": old_time,
                "type": "fact",
                "content": "old fact",
            },
        },
    ]

    consolidator, repo = _make_consolidator(memories)
    with patch(
        "backend.memory.permanent.consolidator.calculate_importance_sync",
        return_value=0.6,
    ):
        report = consolidator.consolidate()

    assert report["checked"] >= 1
    # reassess_count should be in the report
    assert "reassessed" in report, "consolidation report should include reassessed count"


def test_reassess_skips_recent_memories():
    """Recent memories should NOT be reassessed."""
    recent_time = datetime.now(timezone.utc).isoformat()
    memories = [
        {
            "id": "mem-recent-1",
            "metadata": {
                "importance": 0.4,
                "repetitions": 1,
                "access_count": 10,
                "created_at": recent_time,
                "last_accessed": recent_time,
                "type": "fact",
            },
        },
    ]

    consolidator, repo = _make_consolidator(memories)
    report = consolidator.consolidate()

    assert report.get("reassessed", 0) == 0, "recent memories should not be reassessed"


def test_reassess_batch_size_limit():
    """Reassessment should be limited to REASSESS_BATCH_SIZE."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=200)).isoformat()
    # Create more memories than batch size
    memories = [
        {
            "id": f"mem-{i}",
            "metadata": {
                "importance": 0.4,
                "repetitions": 1,
                "access_count": 10,
                "created_at": old_time,
                "last_accessed": old_time,
                "type": "fact",
                "content": f"fact {i}",
            },
        }
        for i in range(60)
    ]

    consolidator, repo = _make_consolidator(memories)
    with patch(
        "backend.memory.permanent.consolidator.calculate_importance_sync",
        return_value=0.6,
    ):
        report = consolidator.consolidate()

    assert report.get("reassessed", 0) <= MemoryConfig.REASSESS_BATCH_SIZE
