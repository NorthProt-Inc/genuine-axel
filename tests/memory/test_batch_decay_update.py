"""Tests for T-03: Batch Decay Update — Surviving Memories Importance."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, call
from zoneinfo import ZoneInfo

import pytest

from backend.memory.permanent.config import MemoryConfig
from backend.memory.permanent.consolidator import MemoryConsolidator
from backend.memory.permanent.decay_calculator import AdaptiveDecayCalculator

VANCOUVER_TZ = ZoneInfo("America/Vancouver")


def _iso_hours_ago(hours: float) -> str:
    dt = datetime.now(VANCOUVER_TZ) - timedelta(hours=hours)
    return dt.isoformat()


def _make_consolidator(memories_data):
    """Create MemoryConsolidator with mocked repository."""
    repo = MagicMock()
    repo.get_all.return_value = memories_data
    repo.delete.return_value = None
    repo.update_metadata.return_value = None

    calc = AdaptiveDecayCalculator()
    consolidator = MemoryConsolidator(
        repository=repo,
        decay_calculator=calc,
    )
    return consolidator, repo


class TestSurvivingImportanceUpdated:

    def test_surviving_importance_updated(self):
        """After consolidation, surviving memories get their importance updated."""
        old_time = _iso_hours_ago(500)  # ~20 days old
        recent_time = _iso_hours_ago(10)

        memories_data = {
            "ids": ["surv-1", "surv-2"],
            "metadatas": [
                {
                    "importance": 0.8,
                    "created_at": old_time,
                    "access_count": 5,
                    "repetitions": 2,
                    "type": "fact",
                },
                {
                    "importance": 0.6,
                    "created_at": recent_time,
                    "access_count": 10,
                    "repetitions": 2,
                    "type": "preference",
                },
            ],
        }

        consolidator, repo = _make_consolidator(memories_data)
        report = consolidator.consolidate()

        # These memories should survive (high access/repetitions)
        assert report["deleted"] == 0

        # Surviving memories should have update_metadata called
        assert repo.update_metadata.call_count >= 1

        # Each call should set "importance" to a float
        for c in repo.update_metadata.call_args_list:
            doc_id, metadata = c[0]
            assert "importance" in metadata
            assert isinstance(metadata["importance"], float)


class TestDeletedNotUpdated:

    def test_deleted_not_updated(self):
        """Deleted memories are NOT updated — only surviving ones."""
        old_time = _iso_hours_ago(2000)  # Very old

        memories_data = {
            "ids": ["del-1", "surv-1"],
            "metadatas": [
                {
                    # This one should be deleted (low importance, old, low reps, low access)
                    "importance": 0.05,
                    "created_at": old_time,
                    "access_count": 0,
                    "repetitions": 1,
                    "type": "conversation",
                },
                {
                    # This one survives (high reps, access)
                    "importance": 0.7,
                    "created_at": old_time,
                    "access_count": 10,
                    "repetitions": 2,
                    "type": "fact",
                },
            ],
        }

        consolidator, repo = _make_consolidator(memories_data)
        report = consolidator.consolidate()

        # del-1 should be deleted
        assert report["deleted"] >= 1

        # Check that update_metadata was NOT called for the deleted doc
        updated_ids = [c[0][0] for c in repo.update_metadata.call_args_list]

        # update_metadata is called for preservation (if any) AND surviving updates
        # del-1 should NOT be in surviving updates
        surviving_update_ids = [
            c[0][0] for c in repo.update_metadata.call_args_list
            if "importance" in c[0][1]
        ]
        assert "del-1" not in surviving_update_ids


class TestEmptyBatchNoError:

    def test_empty_batch_no_error(self):
        """Empty memory list → no error, clean report."""
        memories_data = {"ids": [], "metadatas": []}
        consolidator, repo = _make_consolidator(memories_data)
        report = consolidator.consolidate()

        assert report["deleted"] == 0
        assert report["preserved"] == 0
        assert report["checked"] == 0
        repo.delete.assert_not_called()
