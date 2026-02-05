"""Tests for AdaptiveDecayCalculator."""

import sys
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, "/home/northprot/projects/axnmihn")

from backend.memory.permanent.decay_calculator import (
    AdaptiveDecayCalculator,
    get_memory_age_hours,
    MEMORY_TYPE_DECAY_MULTIPLIERS,
)

VANCOUVER_TZ = ZoneInfo("America/Vancouver")


def get_past_time(hours_ago: float) -> str:
    """Helper to create ISO timestamp from hours ago."""
    dt = datetime.now(VANCOUVER_TZ) - timedelta(hours=hours_ago)
    return dt.isoformat()


class TestGetMemoryAgeHours:
    """Test get_memory_age_hours function."""

    def test_recent_time(self):
        """Recent timestamp should return small age."""
        ts = get_past_time(2)
        age = get_memory_age_hours(ts)
        assert 1.9 < age < 2.1

    def test_old_time(self):
        """Old timestamp should return larger age."""
        ts = get_past_time(48)  # 2 days
        age = get_memory_age_hours(ts)
        assert 47.9 < age < 48.1

    def test_empty_string(self):
        """Empty timestamp should return 0."""
        age = get_memory_age_hours("")
        assert age == 0

    def test_none(self):
        """None should return 0."""
        age = get_memory_age_hours(None)
        assert age == 0

    def test_invalid_format(self):
        """Invalid format should return 0."""
        age = get_memory_age_hours("not-a-date")
        assert age == 0


class TestAdaptiveDecayCalculator:
    """Test AdaptiveDecayCalculator class."""

    def test_decay_reduces_score_over_time(self):
        """Score should decrease as time passes."""
        calc = AdaptiveDecayCalculator()

        recent = calc.calculate(importance=1.0, created_at=get_past_time(1))
        old = calc.calculate(importance=1.0, created_at=get_past_time(168))  # 1 week

        assert old < recent
        assert recent > 0.9  # Recent should stay high
        assert old < 0.9  # Old should decay

    def test_access_count_boosts_score(self):
        """More access should result in slower decay (higher score)."""
        calc = AdaptiveDecayCalculator()
        ts = get_past_time(168)  # 1 week old

        no_access = calc.calculate(importance=1.0, created_at=ts, access_count=0)
        high_access = calc.calculate(importance=1.0, created_at=ts, access_count=10)

        assert high_access > no_access

    def test_connection_count_boosts_score(self):
        """More connections should result in slower decay."""
        calc = AdaptiveDecayCalculator()
        ts = get_past_time(168)  # 1 week old

        no_connections = calc.calculate(importance=1.0, created_at=ts, connection_count=0)
        many_connections = calc.calculate(importance=1.0, created_at=ts, connection_count=5)

        assert many_connections > no_connections

    def test_memory_type_multiplier(self):
        """Facts should decay slower than conversations."""
        calc = AdaptiveDecayCalculator()
        ts = get_past_time(168)  # 1 week old

        fact_score = calc.calculate(importance=1.0, created_at=ts, memory_type="fact")
        conv_score = calc.calculate(importance=1.0, created_at=ts, memory_type="conversation")

        assert fact_score > conv_score
        # Verify multipliers are different
        assert MEMORY_TYPE_DECAY_MULTIPLIERS["fact"] < MEMORY_TYPE_DECAY_MULTIPLIERS["conversation"]

    def test_recency_paradox_protection(self):
        """Old memory recently accessed should get boost."""
        calc = AdaptiveDecayCalculator()
        old_time = get_past_time(200)  # More than 1 week
        recent_access = get_past_time(1)  # 1 hour ago

        without_recent_access = calc.calculate(importance=1.0, created_at=old_time)
        with_recent_access = calc.calculate(
            importance=1.0,
            created_at=old_time,
            last_accessed=recent_access,
        )

        assert with_recent_access > without_recent_access

    def test_minimum_retention(self):
        """Score should never go below MIN_RETENTION * original."""
        calc = AdaptiveDecayCalculator()
        very_old = get_past_time(8760)  # 1 year old

        score = calc.calculate(importance=0.5, created_at=very_old)

        # Score should be at least MIN_RETENTION * original
        min_expected = 0.5 * calc.config.MIN_RETENTION
        assert score >= min_expected

    def test_empty_created_at_returns_original(self):
        """Empty created_at should return original importance."""
        calc = AdaptiveDecayCalculator()

        score = calc.calculate(importance=0.7, created_at="")

        assert score == 0.7

    def test_preference_decays_medium(self):
        """Preferences should decay at medium rate."""
        calc = AdaptiveDecayCalculator()
        ts = get_past_time(168)

        fact = calc.calculate(importance=1.0, created_at=ts, memory_type="fact")
        preference = calc.calculate(importance=1.0, created_at=ts, memory_type="preference")
        conversation = calc.calculate(importance=1.0, created_at=ts, memory_type="conversation")

        assert fact > preference > conversation
