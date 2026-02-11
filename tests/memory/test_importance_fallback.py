"""W4-1/W4-3: Importance fallback warning and episodic threshold tests."""

import logging
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.memory.permanent.consolidator import MemoryConsolidator
from backend.memory.memgpt import MemGPTConfig

VANCOUVER_TZ = ZoneInfo("America/Vancouver")


class TestImportanceFallback:
    """Verify importance=None triggers warning log and uses 0.5."""

    def test_consolidator_warns_on_missing_importance(self):
        from unittest.mock import patch

        mock_repo = MagicMock()
        created = (datetime.now(VANCOUVER_TZ) - timedelta(days=7)).isoformat()
        mock_repo.get_all.return_value = {
            "ids": ["mem-no-imp"],
            "metadatas": [
                {
                    "importance": None,
                    "created_at": created,
                    "preserved": False,
                    "repetitions": 1,
                    "access_count": 0,
                    "type": "conversation",
                },
            ],
        }
        mock_repo.batch_update_metadata.return_value = 0
        mock_repo.delete.return_value = 0

        consolidator = MemoryConsolidator(repository=mock_repo)

        with patch("backend.memory.permanent.consolidator._log") as mock_log:
            consolidator.consolidate()
            mock_log.warning.assert_any_call(
                "importance missing, using default", doc_id="mem-no-i"
            )

    def test_consolidator_no_warn_when_importance_present(self):
        from unittest.mock import patch

        mock_repo = MagicMock()
        created = (datetime.now(VANCOUVER_TZ) - timedelta(days=7)).isoformat()
        mock_repo.get_all.return_value = {
            "ids": ["mem-with-imp"],
            "metadatas": [
                {
                    "importance": 0.8,
                    "created_at": created,
                    "preserved": False,
                    "repetitions": 1,
                    "access_count": 0,
                    "type": "fact",
                },
            ],
        }
        mock_repo.batch_update_metadata.return_value = 0
        mock_repo.delete.return_value = 0

        consolidator = MemoryConsolidator(repository=mock_repo)

        with patch("backend.memory.permanent.consolidator._log") as mock_log:
            consolidator.consolidate()
            # Should not have called warning with "importance missing"
            for call in mock_log.warning.call_args_list:
                assert "importance missing" not in str(call)


class TestEpisodicThreshold:
    """Verify min_episodic_repetitions default changed to 2."""

    def test_default_min_episodic_repetitions_is_2(self):
        config = MemGPTConfig()
        assert config.min_episodic_repetitions == 2

    def test_can_override_min_episodic_repetitions(self):
        config = MemGPTConfig(min_episodic_repetitions=3)
        assert config.min_episodic_repetitions == 3
