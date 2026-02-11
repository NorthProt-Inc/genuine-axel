"""W5-2/W5-3: Dynamic decay metrics collection tests."""

import pytest
from unittest.mock import MagicMock

from backend.memory.permanent.dynamic_decay import (
    collect_behavior_metrics,
    UserBehaviorMetrics,
    calculate_engagement,
    detect_peak_hours,
)


class TestCollectBehaviorMetrics:
    """Test behavior metrics collection function."""

    def test_returns_defaults_without_conn_mgr(self):
        metrics = collect_behavior_metrics(conn_mgr=None)
        assert isinstance(metrics, UserBehaviorMetrics)
        assert metrics.avg_latency_ms == 1000.0
        assert metrics.user_id == "default"

    def test_handles_db_error_gracefully(self):
        mock_conn = MagicMock()
        mock_conn.execute_dict.side_effect = Exception("DB not available")

        metrics = collect_behavior_metrics(conn_mgr=mock_conn)
        assert isinstance(metrics, UserBehaviorMetrics)
        assert metrics.avg_latency_ms == 1000.0

    def test_populates_from_db(self):
        mock_conn = MagicMock()
        mock_conn.execute_dict.side_effect = [
            [{"avg_latency": 500.0, "tool_calls": 10, "total_interactions": 100}],
            [{"avg_dur": 1200.0}],
        ]

        metrics = collect_behavior_metrics(conn_mgr=mock_conn)
        assert metrics.avg_latency_ms == 500.0
        assert metrics.tool_usage_frequency == pytest.approx(1.0)
        assert metrics.session_duration_avg == 1200.0


class TestCalculateEngagement:
    """Test engagement score calculation."""

    def test_zero_engagement(self):
        metrics = UserBehaviorMetrics(
            session_duration_avg=0.0,
            tool_usage_frequency=0.0,
            avg_latency_ms=5000.0,
        )
        score = calculate_engagement(metrics)
        assert score == pytest.approx(0.0)

    def test_max_engagement(self):
        metrics = UserBehaviorMetrics(
            session_duration_avg=3600.0,
            tool_usage_frequency=10.0,
            avg_latency_ms=100.0,
        )
        score = calculate_engagement(metrics)
        assert score >= 0.9

    def test_engagement_range(self):
        metrics = UserBehaviorMetrics()
        score = calculate_engagement(metrics)
        assert 0.0 <= score <= 1.0


class TestDetectPeakHours:
    """Test peak hour detection."""

    def test_no_activity_returns_empty(self):
        assert detect_peak_hours([0.0] * 24) == []

    def test_uniform_returns_empty(self):
        assert detect_peak_hours([1.0] * 24) == []

    def test_detects_peaks(self):
        rates = [0.0] * 24
        rates[9] = 10.0
        rates[14] = 8.0
        peaks = detect_peak_hours(rates)
        assert 9 in peaks
        assert 14 in peaks

    def test_invalid_length(self):
        assert detect_peak_hours([1.0, 2.0]) == []
