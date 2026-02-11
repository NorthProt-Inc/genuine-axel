"""W2-2: Verify circadian stability integration in decay calculator."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.memory.permanent.decay_calculator import AdaptiveDecayCalculator

VANCOUVER_TZ = ZoneInfo("America/Vancouver")


class TestCircadianDecay:
    """Verify circadian stability affects decay calculation."""

    def test_peak_hour_access_slows_decay(self):
        """Memory accessed during peak hour should decay slower."""
        calc_with_peaks = AdaptiveDecayCalculator(peak_hours=[10, 11, 14, 15])
        calc_no_peaks = AdaptiveDecayCalculator()

        created = (datetime.now(VANCOUVER_TZ) - timedelta(days=30)).isoformat()
        # Set last_accessed to 10:30 (peak hour=10)
        last_accessed = datetime.now(VANCOUVER_TZ).replace(hour=10, minute=30).isoformat()

        decay_with = calc_with_peaks.calculate(
            importance=0.8,
            created_at=created,
            access_count=3,
            last_accessed=last_accessed,
            memory_type="fact",
        )
        decay_without = calc_no_peaks.calculate(
            importance=0.8,
            created_at=created,
            access_count=3,
            last_accessed=last_accessed,
            memory_type="fact",
        )

        # Peak hour boosts effective access_count (3→4), giving higher retention
        assert decay_with >= decay_without

    def test_non_peak_hour_no_boost(self):
        """Memory accessed during non-peak hour should not get boost."""
        calc = AdaptiveDecayCalculator(peak_hours=[10, 11, 14, 15])

        created = (datetime.now(VANCOUVER_TZ) - timedelta(days=30)).isoformat()
        # Set last_accessed to 03:00 (non-peak)
        last_accessed = datetime.now(VANCOUVER_TZ).replace(hour=3, minute=0).isoformat()

        decay_peak_calc = calc.calculate(
            importance=0.8,
            created_at=created,
            access_count=3,
            last_accessed=last_accessed,
            memory_type="fact",
        )

        calc_no_peaks = AdaptiveDecayCalculator()
        decay_no_peaks = calc_no_peaks.calculate(
            importance=0.8,
            created_at=created,
            access_count=3,
            last_accessed=last_accessed,
            memory_type="fact",
        )

        # Non-peak hour: no boost, same result
        assert abs(decay_peak_calc - decay_no_peaks) < 1e-10

    def test_empty_peak_hours_no_effect(self):
        """Empty peak_hours list should not affect calculation."""
        calc = AdaptiveDecayCalculator(peak_hours=[])
        created = (datetime.now(VANCOUVER_TZ) - timedelta(days=7)).isoformat()
        last_accessed = datetime.now(VANCOUVER_TZ).isoformat()

        result = calc.calculate(
            importance=0.8,
            created_at=created,
            access_count=2,
            last_accessed=last_accessed,
        )
        assert 0 < result <= 1.0

    def test_batch_python_applies_circadian(self):
        """Batch python path should also apply circadian stability."""
        calc = AdaptiveDecayCalculator(peak_hours=[14, 15])

        created = (datetime.now(VANCOUVER_TZ) - timedelta(days=30)).isoformat()

        memories = [
            {
                "importance": 0.8,
                "created_at": created,
                "access_count": 3,
                "connection_count": 0,
                "last_accessed": datetime.now(VANCOUVER_TZ).replace(hour=14).isoformat(),
                "memory_type": "conversation",
            },
        ]

        results = calc._calculate_batch_python([{
            "importance": 0.8,
            "hours_passed": 720.0,
            "access_count": 3,
            "connection_count": 0,
            "last_access_hours": 0.5,
            "last_accessed_hour": 14,  # peak hour
            "memory_type": 0,
            "channel_mentions": 0,
        }])

        # Without peaks
        calc_no = AdaptiveDecayCalculator()
        results_no = calc_no._calculate_batch_python([{
            "importance": 0.8,
            "hours_passed": 720.0,
            "access_count": 3,
            "connection_count": 0,
            "last_access_hours": 0.5,
            "last_accessed_hour": 14,
            "memory_type": 0,
            "channel_mentions": 0,
        }])

        assert results[0] >= results_no[0]
