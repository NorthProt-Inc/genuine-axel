"""Tests for MemoryConsolidator."""

import sys
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, "/home/northprot/projects/axnmihn")

from backend.memory.permanent.consolidator import MemoryConsolidator
from backend.memory.permanent.decay_calculator import AdaptiveDecayCalculator

VANCOUVER_TZ = ZoneInfo("America/Vancouver")


def get_past_time(days_ago: float) -> str:
    """Helper to create ISO timestamp from days ago."""
    dt = datetime.now(VANCOUVER_TZ) - timedelta(days=days_ago)
    return dt.isoformat()


@pytest.fixture
def mock_repository():
    """Mock repository for consolidator tests."""
    repo = MagicMock()
    repo.get_all.return_value = {
        "ids": [],
        "metadatas": [],
    }
    repo.delete.return_value = 0
    repo.update_metadata.return_value = True
    return repo


@pytest.fixture
def mock_decay_calculator():
    """Mock decay calculator that returns predictable values."""
    calc = MagicMock(spec=AdaptiveDecayCalculator)
    calc.calculate.return_value = 0.5
    return calc


class TestMemoryConsolidator:
    """Test cases for MemoryConsolidator."""

    def test_consolidate_deletes_low_score_memories(self, mock_repository):
        """Memories with low decayed score should be deleted."""
        old_time = get_past_time(30)  # 30 days old

        mock_repository.get_all.return_value = {
            "ids": ["mem-001", "mem-002"],
            "metadatas": [
                {
                    "importance": 0.1,  # Low importance
                    "created_at": old_time,
                    "repetitions": 1,
                    "access_count": 0,
                    "preserved": False,
                },
                {
                    "importance": 0.9,  # High importance
                    "created_at": old_time,
                    "repetitions": 5,
                    "access_count": 10,
                    "preserved": False,
                },
            ],
        }

        # mem-002 has repetitions=5 (>= PRESERVE_REPETITIONS=3) so it goes
        # to the preserve path, not the batch decay path.  Only mem-001
        # reaches calculate_batch.
        calc = MagicMock(spec=AdaptiveDecayCalculator)
        calc.calculate_batch.return_value = [0.01]  # Below threshold → delete

        with patch(
            "backend.memory.permanent.consolidator.get_connection_count",
            return_value=0,
        ):
            consolidator = MemoryConsolidator(
                repository=mock_repository,
                decay_calculator=calc,
            )
            report = consolidator.consolidate()

        assert report["deleted"] == 1
        assert report["checked"] == 2
        mock_repository.delete.assert_called_once_with(["mem-001"])

    def test_consolidate_preserves_high_importance(self, mock_repository):
        """High importance memories should not be deleted."""
        mock_repository.get_all.return_value = {
            "ids": ["mem-001"],
            "metadatas": [
                {
                    "importance": 0.9,
                    "created_at": get_past_time(1),
                    "repetitions": 5,
                    "access_count": 10,
                    "preserved": False,
                },
            ],
        }

        # repetitions=5 >= PRESERVE_REPETITIONS → goes to preserve path,
        # batch_data is empty, so calculate_batch is never called.
        calc = MagicMock(spec=AdaptiveDecayCalculator)
        calc.calculate_batch.return_value = []

        with patch(
            "backend.memory.permanent.consolidator.get_connection_count",
            return_value=0,
        ):
            consolidator = MemoryConsolidator(
                repository=mock_repository,
                decay_calculator=calc,
            )
            report = consolidator.consolidate()

        assert report["deleted"] == 0
        mock_repository.delete.assert_not_called()

    def test_consolidate_preserves_with_high_access(self, mock_repository):
        """Memories with high access count should not be deleted."""
        mock_repository.get_all.return_value = {
            "ids": ["mem-001"],
            "metadatas": [
                {
                    "importance": 0.1,
                    "created_at": get_past_time(30),  # Old
                    "repetitions": 1,
                    "access_count": 5,  # >= 3, should protect
                    "preserved": False,
                },
            ],
        }

        # Low decay score but access_count=5 >= 3 protects from deletion
        calc = MagicMock(spec=AdaptiveDecayCalculator)
        calc.calculate_batch.return_value = [0.01]  # Below threshold

        with patch(
            "backend.memory.permanent.consolidator.get_connection_count",
            return_value=0,
        ):
            consolidator = MemoryConsolidator(
                repository=mock_repository,
                decay_calculator=calc,
            )
            report = consolidator.consolidate()

        # Memory NOT deleted because access_count >= 3
        assert report["deleted"] == 0

    def test_consolidate_marks_high_repetition_preserved(self, mock_repository):
        """Memories with high repetitions should be marked as preserved."""
        mock_repository.get_all.return_value = {
            "ids": ["mem-001"],
            "metadatas": [
                {
                    "importance": 0.5,
                    "created_at": get_past_time(7),
                    "repetitions": 5,  # >= PRESERVE_REPETITIONS (3)
                    "access_count": 2,
                    "preserved": False,
                },
            ],
        }

        # repetitions=5 >= PRESERVE_REPETITIONS → goes to preserve path
        calc = MagicMock(spec=AdaptiveDecayCalculator)
        calc.calculate_batch.return_value = []

        with patch(
            "backend.memory.permanent.consolidator.get_connection_count",
            return_value=0,
        ):
            consolidator = MemoryConsolidator(
                repository=mock_repository,
                decay_calculator=calc,
            )
            report = consolidator.consolidate()

        assert report["preserved"] == 1
        mock_repository.update_metadata.assert_called()

    def test_consolidate_returns_stats(self, mock_repository):
        """consolidate should return proper statistics."""
        mock_repository.get_all.return_value = {
            "ids": ["mem-001", "mem-002", "mem-003"],
            "metadatas": [
                {
                    "importance": 0.1,
                    "created_at": get_past_time(30),
                    "repetitions": 1,
                    "access_count": 0,
                    "preserved": False,
                },
                {
                    "importance": 0.5,
                    "created_at": get_past_time(7),
                    "repetitions": 5,
                    "access_count": 5,
                    "preserved": False,
                },
                {
                    "importance": 0.8,
                    "created_at": get_past_time(1),
                    "repetitions": 2,
                    "access_count": 3,
                    "preserved": True,  # Already preserved
                },
            ],
        }

        # mem-001 (reps=1) → batch_data, mem-002 (reps=5) → preserve,
        # mem-003 (preserved=True) → skipped.  Only mem-001 in batch.
        calc = MagicMock(spec=AdaptiveDecayCalculator)
        calc.calculate_batch.return_value = [0.01]  # mem-001 below threshold

        with patch(
            "backend.memory.permanent.consolidator.get_connection_count",
            return_value=0,
        ):
            consolidator = MemoryConsolidator(
                repository=mock_repository,
                decay_calculator=calc,
            )
            report = consolidator.consolidate()

        assert "deleted" in report
        assert "preserved" in report
        assert "checked" in report
        assert report["checked"] == 3

    def test_consolidate_skips_preserved_memories(self, mock_repository):
        """Already preserved memories should be skipped."""
        mock_repository.get_all.return_value = {
            "ids": ["mem-001"],
            "metadatas": [
                {
                    "importance": 0.1,
                    "created_at": get_past_time(30),
                    "repetitions": 1,
                    "access_count": 0,
                    "preserved": True,  # Already preserved
                },
            ],
        }

        calc = MagicMock(spec=AdaptiveDecayCalculator)

        with patch(
            "backend.memory.permanent.consolidator.get_connection_count",
            return_value=0,
        ):
            consolidator = MemoryConsolidator(
                repository=mock_repository,
                decay_calculator=calc,
            )
            report = consolidator.consolidate()

        assert report["deleted"] == 0
        # Decay should not be calculated for preserved memories
        calc.calculate.assert_not_called()
