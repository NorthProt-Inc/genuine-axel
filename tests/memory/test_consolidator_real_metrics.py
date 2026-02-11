"""W2-1: Verify consolidator calls collect_behavior_metrics with conn_mgr."""

from unittest.mock import MagicMock, patch

import pytest

from backend.memory.permanent.consolidator import MemoryConsolidator


class TestConsolidatorRealMetrics:
    """Verify consolidator uses real behavior metrics instead of defaults."""

    def test_collect_behavior_metrics_called_when_dynamic_enabled(self):
        mock_repo = MagicMock()
        mock_repo.get_all.return_value = {"ids": [], "metadatas": []}
        mock_conn_mgr = MagicMock()

        consolidator = MemoryConsolidator(
            repository=mock_repo, conn_mgr=mock_conn_mgr
        )

        with patch(
            "backend.memory.permanent.dynamic_decay.DYNAMIC_DECAY_ENABLED", True
        ), patch(
            "backend.memory.permanent.dynamic_decay.collect_behavior_metrics"
        ) as mock_collect:
            from backend.memory.permanent.dynamic_decay import UserBehaviorMetrics
            mock_collect.return_value = UserBehaviorMetrics()

            consolidator.consolidate()

        mock_collect.assert_called_once_with(mock_conn_mgr)

    def test_conn_mgr_none_still_works(self):
        """collect_behavior_metrics(None) returns defaults — no crash."""
        mock_repo = MagicMock()
        mock_repo.get_all.return_value = {"ids": [], "metadatas": []}

        consolidator = MemoryConsolidator(repository=mock_repo, conn_mgr=None)

        with patch(
            "backend.memory.permanent.dynamic_decay.DYNAMIC_DECAY_ENABLED", True
        ):
            report = consolidator.consolidate()

        assert report["checked"] == 0

    def test_peak_hours_set_on_decay_calculator(self):
        mock_repo = MagicMock()
        mock_repo.get_all.return_value = {"ids": [], "metadatas": []}
        mock_conn_mgr = MagicMock()

        consolidator = MemoryConsolidator(
            repository=mock_repo, conn_mgr=mock_conn_mgr
        )

        with patch(
            "backend.memory.permanent.dynamic_decay.DYNAMIC_DECAY_ENABLED", True
        ), patch(
            "backend.memory.permanent.dynamic_decay.collect_behavior_metrics"
        ) as mock_collect:
            from backend.memory.permanent.dynamic_decay import UserBehaviorMetrics
            metrics = UserBehaviorMetrics(peak_hours=[9, 10, 14, 15])
            mock_collect.return_value = metrics

            consolidator.consolidate()

        assert consolidator.decay_calculator.peak_hours == [9, 10, 14, 15]
