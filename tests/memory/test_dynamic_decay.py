"""Tests for T-05: Dynamic Per-User Decay + Circadian Stability."""

import pytest

from backend.memory.permanent.dynamic_decay import (
    UserBehaviorMetrics,
    DYNAMIC_BOUNDS,
    clamp,
    update_ema,
    detect_peak_hours,
    calculate_engagement,
    calculate_dynamic_config,
    apply_circadian_stability,
)


class TestUpdateEmaSmoothing:

    def test_known_values(self):
        """EMA with known inputs produces expected smooth output."""
        current = 0.5
        new_value = 1.0
        alpha = 0.3
        hours_elapsed = 6.0

        result = update_ema(current, new_value, alpha, hours_elapsed)

        # time_weight = 1 - (1-0.3)^(6/6) = 1 - 0.7 = 0.3
        # result = 0.5 * 0.7 + 1.0 * 0.3 = 0.65
        assert abs(result - 0.65) < 0.01

    def test_zero_hours_elapsed(self):
        """Zero hours elapsed → very small weight → stays near current."""
        result = update_ema(0.5, 1.0, 0.3, 0.0)
        # time_weight = 1 - (0.7)^0 = 0
        assert abs(result - 0.5) < 0.01

    def test_large_hours_approaches_new_value(self):
        """Large hours → weight ≈ 1 → approaches new value."""
        result = update_ema(0.0, 1.0, 0.3, 100.0)
        assert result > 0.95


class TestDetectPeakHours:

    def test_known_distribution(self):
        """Known hourly distribution returns correct peak hours."""
        # Uniform except hours 9, 14, 20 which are much higher
        hourly = [1.0] * 24
        hourly[9] = 10.0
        hourly[14] = 8.0
        hourly[20] = 12.0

        peaks = detect_peak_hours(hourly)

        assert 9 in peaks
        assert 14 in peaks
        assert 20 in peaks
        # Most non-peak hours should NOT be included
        assert 3 not in peaks

    def test_all_zero_returns_empty(self):
        """All-zero distribution returns no peaks."""
        assert detect_peak_hours([0.0] * 24) == []

    def test_wrong_length_returns_empty(self):
        """Non-24 length returns empty."""
        assert detect_peak_hours([1.0] * 12) == []

    def test_uniform_distribution(self):
        """Uniform distribution → no peaks (stddev = 0)."""
        result = detect_peak_hours([5.0] * 24)
        # With stddev=0, threshold = mean + 0 = mean, no value > threshold
        assert result == []


class TestCalculateEngagement:

    def test_bounds(self):
        """Engagement score is always in [0, 1]."""
        metrics_low = UserBehaviorMetrics(
            session_duration_avg=0,
            tool_usage_frequency=0,
            avg_latency_ms=5000,
        )
        assert 0.0 <= calculate_engagement(metrics_low) <= 1.0

        metrics_high = UserBehaviorMetrics(
            session_duration_avg=3600,
            tool_usage_frequency=10,
            avg_latency_ms=100,
        )
        result_high = calculate_engagement(metrics_high)
        assert 0.0 <= result_high <= 1.0
        assert result_high > 0.5

    def test_mid_range(self):
        """Mid-range metrics produce mid-range engagement."""
        metrics = UserBehaviorMetrics(
            session_duration_avg=900,  # 15 min → 0.5
            tool_usage_frequency=2.5,  # 0.5
            avg_latency_ms=2750,  # 0.5
        )
        result = calculate_engagement(metrics)
        assert 0.4 < result < 0.6


class TestCircadianBoost:

    def test_peak_hour_boost(self):
        """Access during peak hour → +1 access_count."""
        result = apply_circadian_stability(
            access_count=5, last_accessed_hour=14, peak_hours=[10, 14, 20]
        )
        assert result == 6

    def test_non_peak_hour_no_boost(self):
        """Access during non-peak hour → same access_count."""
        result = apply_circadian_stability(
            access_count=5, last_accessed_hour=3, peak_hours=[10, 14, 20]
        )
        assert result == 5

    def test_empty_peak_hours(self):
        """No peak hours defined → no boost."""
        result = apply_circadian_stability(
            access_count=5, last_accessed_hour=14, peak_hours=[]
        )
        assert result == 5


class TestFeatureFlagOff:

    def test_feature_flag_default_off(self):
        """DYNAMIC_DECAY_ENABLED defaults to False."""
        from backend.memory.permanent.dynamic_decay import DYNAMIC_DECAY_ENABLED
        # In test environment, should be False unless env var is set
        assert DYNAMIC_DECAY_ENABLED is False


class TestDynamicConfig:

    def test_config_within_bounds(self):
        """Dynamic config values stay within safety bounds."""
        metrics = UserBehaviorMetrics(
            daily_active_hours=8.0,
            engagement_score=0.7,
        )
        config = calculate_dynamic_config(metrics, base_rate=0.002)

        assert DYNAMIC_BOUNDS["base_rate"]["min"] <= config["base_rate"] <= DYNAMIC_BOUNDS["base_rate"]["max"]
        assert DYNAMIC_BOUNDS["recency_boost"]["min"] <= config["recency_boost"] <= DYNAMIC_BOUNDS["recency_boost"]["max"]

    def test_extreme_values_clamped(self):
        """Extreme metrics produce clamped config."""
        metrics_extreme = UserBehaviorMetrics(
            daily_active_hours=24.0,
            engagement_score=1.0,
        )
        config = calculate_dynamic_config(metrics_extreme, base_rate=0.01)
        assert config["base_rate"] <= DYNAMIC_BOUNDS["base_rate"]["max"]
        assert config["recency_boost"] <= DYNAMIC_BOUNDS["recency_boost"]["max"]
