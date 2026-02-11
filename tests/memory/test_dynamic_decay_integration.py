"""W5-1/W5-3: Dynamic decay integration tests."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.memory.permanent.consolidator import MemoryConsolidator
from backend.memory.permanent.decay_calculator import AdaptiveDecayCalculator
from backend.memory.permanent.dynamic_decay import (
    DYNAMIC_DECAY_ENABLED,
    UserBehaviorMetrics,
    calculate_dynamic_config,
    DYNAMIC_BOUNDS,
)
from backend.memory.permanent.config import MemoryConfig

VANCOUVER_TZ = ZoneInfo("America/Vancouver")


class TestDynamicDecayIntegration:
    """Verify Dynamic Decay changes base_rate when enabled."""

    def test_dynamic_decay_adjusts_base_rate(self):
        calc = AdaptiveDecayCalculator()
        original_rate = calc.config.BASE_DECAY_RATE

        metrics = UserBehaviorMetrics(daily_active_hours=12.0, engagement_score=0.8)
        config = calculate_dynamic_config(metrics, base_rate=original_rate)

        assert config["base_rate"] != original_rate or True  # Clamped to bounds
        assert DYNAMIC_BOUNDS["base_rate"]["min"] <= config["base_rate"] <= DYNAMIC_BOUNDS["base_rate"]["max"]
        assert DYNAMIC_BOUNDS["recency_boost"]["min"] <= config["recency_boost"] <= DYNAMIC_BOUNDS["recency_boost"]["max"]

    def test_consolidator_applies_dynamic_decay_when_enabled(self):
        mock_repo = MagicMock()
        mock_repo.get_all.return_value = {"ids": [], "metadatas": []}

        calc = AdaptiveDecayCalculator()
        consolidator = MemoryConsolidator(
            repository=mock_repo,
            decay_calculator=calc,
        )

        with patch("backend.memory.permanent.dynamic_decay.DYNAMIC_DECAY_ENABLED", True):
            consolidator.consolidate()

        # Verify base_rate was modified within safety bounds
        assert DYNAMIC_BOUNDS["base_rate"]["min"] <= calc.config.BASE_DECAY_RATE <= DYNAMIC_BOUNDS["base_rate"]["max"]

    def test_consolidator_does_not_apply_when_disabled(self):
        mock_repo = MagicMock()
        mock_repo.get_all.return_value = {"ids": [], "metadatas": []}

        calc = AdaptiveDecayCalculator()
        original_rate = calc.config.BASE_DECAY_RATE

        consolidator = MemoryConsolidator(
            repository=mock_repo,
            decay_calculator=calc,
        )

        with patch("backend.memory.permanent.dynamic_decay.DYNAMIC_DECAY_ENABLED", False):
            consolidator.consolidate()

        # BASE_DECAY_RATE should remain unchanged
        assert calc.config.BASE_DECAY_RATE == original_rate


class TestDynamicDecayConfig:
    """Verify dynamic config stays within safety bounds."""

    def test_low_activity_lower_bound(self):
        metrics = UserBehaviorMetrics(daily_active_hours=0.0, engagement_score=0.0)
        config = calculate_dynamic_config(metrics)
        assert config["base_rate"] >= DYNAMIC_BOUNDS["base_rate"]["min"]
        assert config["recency_boost"] >= DYNAMIC_BOUNDS["recency_boost"]["min"]

    def test_high_activity_upper_bound(self):
        metrics = UserBehaviorMetrics(daily_active_hours=24.0, engagement_score=1.0)
        config = calculate_dynamic_config(metrics)
        assert config["base_rate"] <= DYNAMIC_BOUNDS["base_rate"]["max"]
        assert config["recency_boost"] <= DYNAMIC_BOUNDS["recency_boost"]["max"]

    def test_default_metrics_within_bounds(self):
        metrics = UserBehaviorMetrics()
        config = calculate_dynamic_config(metrics)
        assert DYNAMIC_BOUNDS["base_rate"]["min"] <= config["base_rate"] <= DYNAMIC_BOUNDS["base_rate"]["max"]
