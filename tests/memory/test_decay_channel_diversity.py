"""Tests for T-02: Channel Diversity Factor in Decay Calculation."""

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.memory.permanent.config import MemoryConfig
from backend.memory.permanent.decay_calculator import AdaptiveDecayCalculator

VANCOUVER_TZ = ZoneInfo("America/Vancouver")


def _iso_hours_ago(hours: float) -> str:
    """Create ISO timestamp for N hours ago."""
    dt = datetime.now(VANCOUVER_TZ) - timedelta(hours=hours)
    return dt.isoformat()


class TestChannelMentionsZeroUnchanged:

    def test_channel_mentions_zero_unchanged(self):
        """channel_mentions=0 produces identical result to old behavior."""
        calc = AdaptiveDecayCalculator()
        created = _iso_hours_ago(48)

        result_without = calc.calculate(
            importance=0.8,
            created_at=created,
            access_count=2,
            connection_count=1,
            memory_type="fact",
            channel_mentions=0,
        )

        # channel_boost = 1/(1+0.2*0) = 1.0, so effective_rate unchanged
        # Verify channel_boost = 1.0 doesn't change the formula
        config = MemoryConfig
        stability = 1 + config.ACCESS_STABILITY_K * math.log(1 + 2)
        resistance = min(1.0, 1 * config.RELATION_RESISTANCE_K)
        type_mult = 0.3  # fact
        channel_boost = 1.0 / (1 + config.CHANNEL_DIVERSITY_K * 0)
        assert channel_boost == 1.0

        effective_rate = config.BASE_DECAY_RATE * type_mult * channel_boost / stability * (1 - resistance)
        hours = 48.0
        expected = 0.8 * math.exp(-effective_rate * hours)
        expected = max(expected, 0.8 * config.MIN_RETENTION)

        assert abs(result_without - expected) < 0.001


class TestChannelMentionsSlowsDecay:

    def test_channel_mentions_slows_decay(self):
        """Higher channel_mentions → higher decayed value (slower decay)."""
        calc = AdaptiveDecayCalculator()
        created = _iso_hours_ago(200)

        result_0 = calc.calculate(
            importance=0.7, created_at=created,
            access_count=1, memory_type="conversation",
            channel_mentions=0,
        )
        result_3 = calc.calculate(
            importance=0.7, created_at=created,
            access_count=1, memory_type="conversation",
            channel_mentions=3,
        )
        result_10 = calc.calculate(
            importance=0.7, created_at=created,
            access_count=1, memory_type="conversation",
            channel_mentions=10,
        )

        # More channel mentions → lower effective_rate → higher decayed value
        assert result_3 > result_0
        assert result_10 > result_3

    def test_channel_boost_formula(self):
        """Verify channel_boost = 1/(1 + K * channel_mentions)."""
        k = MemoryConfig.CHANNEL_DIVERSITY_K  # 0.2
        assert abs(1.0 / (1 + k * 0) - 1.0) < 1e-10
        assert abs(1.0 / (1 + k * 5) - 0.5) < 1e-10
        assert abs(1.0 / (1 + k * 10) - 1.0 / 3.0) < 1e-10


class TestBatchChannelDiversity:

    def test_batch_channel_diversity(self):
        """Batch calculation respects channel_mentions."""
        calc = AdaptiveDecayCalculator()
        created = _iso_hours_ago(100)

        memories = [
            {
                "importance": 0.6,
                "created_at": created,
                "access_count": 1,
                "connection_count": 0,
                "memory_type": "conversation",
                "channel_mentions": 0,
            },
            {
                "importance": 0.6,
                "created_at": created,
                "access_count": 1,
                "connection_count": 0,
                "memory_type": "conversation",
                "channel_mentions": 5,
            },
        ]

        results = calc.calculate_batch(memories)
        assert len(results) == 2
        # Memory with 5 channel mentions should decay slower
        assert results[1] > results[0]
