"""Dynamic per-user decay parameters (ADR-023 port from axel).

Provides user behavior tracking, peak hour detection, engagement scoring,
and circadian stability for memory decay optimization.

Feature-gated: DYNAMIC_DECAY_ENABLED env var must be "true" to activate.
When disabled, all functions return neutral/default values.
"""

import math
import os
from dataclasses import dataclass, field
from typing import List

from backend.core.logging import get_logger

_log = get_logger("memory.dynamic_decay")

DYNAMIC_DECAY_ENABLED = os.environ.get("DYNAMIC_DECAY_ENABLED", "false").lower() == "true"


@dataclass
class UserBehaviorMetrics:
    user_id: str = "default"
    hourly_activity_rate: List[float] = field(default_factory=lambda: [0.0] * 24)
    avg_latency_ms: float = 1000.0
    tool_usage_frequency: float = 0.0
    session_duration_avg: float = 600.0  # seconds
    daily_active_hours: float = 4.0
    peak_hours: List[int] = field(default_factory=list)
    engagement_score: float = 0.5


# Safety bounds for dynamic parameters
DYNAMIC_BOUNDS = {
    "base_rate": {"min": 0.0005, "max": 0.002},
    "recency_boost": {"min": 1.1, "max": 1.5},
}


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value to [min_val, max_val]."""
    return max(min_val, min(max_val, value))


def update_ema(current: float, new_value: float, alpha: float, hours_elapsed: float) -> float:
    """Update Exponential Moving Average with time-weighted decay.

    Args:
        current: Current EMA value
        new_value: New observation
        alpha: Base smoothing factor
        hours_elapsed: Hours since last update

    Returns:
        Updated EMA value
    """
    time_weight = 1 - (1 - alpha) ** (hours_elapsed / 6)
    return current * (1 - time_weight) + new_value * time_weight


def detect_peak_hours(hourly_rate: List[float]) -> List[int]:
    """Detect peak activity hours from hourly rate distribution.

    Peak hours are those with activity > mean + 0.5 * stddev.

    Args:
        hourly_rate: 24-element list of activity rates per hour

    Returns:
        Sorted list of peak hour indices (0-23)
    """
    if len(hourly_rate) != 24:
        return []
    total = sum(hourly_rate)
    if total == 0:
        return []
    mean = total / 24
    variance = sum((v - mean) ** 2 for v in hourly_rate) / 24
    stddev = math.sqrt(variance)
    threshold = mean + 0.5 * stddev
    return sorted([h for h, rate in enumerate(hourly_rate) if rate > threshold])


def calculate_engagement(metrics: UserBehaviorMetrics) -> float:
    """Calculate user engagement score from behavior metrics.

    Combines session duration, tool usage, and response latency.

    Args:
        metrics: User behavior metrics

    Returns:
        Engagement score in [0, 1]
    """
    duration_score = min(1.0, metrics.session_duration_avg / 1800)
    tool_score = min(1.0, metrics.tool_usage_frequency / 5)
    latency_score = max(0.0, min(1.0, (5000 - metrics.avg_latency_ms) / 4500))
    return (duration_score + tool_score + latency_score) / 3


def calculate_dynamic_config(metrics: UserBehaviorMetrics, base_rate: float = 0.002) -> dict:
    """Calculate dynamic decay configuration from user metrics.

    Args:
        metrics: User behavior metrics
        base_rate: Base decay rate to adjust

    Returns:
        Dict with 'base_rate' and 'recency_boost' keys
    """
    activity_level = min(1.0, metrics.daily_active_hours / 16)
    base_rate_multiplier = 0.8 + activity_level * 0.4
    dynamic_base_rate = clamp(
        base_rate * base_rate_multiplier,
        DYNAMIC_BOUNDS["base_rate"]["min"],
        DYNAMIC_BOUNDS["base_rate"]["max"],
    )
    dynamic_recency_boost = clamp(
        1.1 + metrics.engagement_score * 0.4,
        DYNAMIC_BOUNDS["recency_boost"]["min"],
        DYNAMIC_BOUNDS["recency_boost"]["max"],
    )
    return {"base_rate": dynamic_base_rate, "recency_boost": dynamic_recency_boost}


def apply_circadian_stability(
    access_count: int, last_accessed_hour: int, peak_hours: List[int]
) -> int:
    """Apply circadian stability boost to access count.

    Memories accessed during peak hours get virtual +1 access_count,
    slowing their decay.

    Args:
        access_count: Current access count
        last_accessed_hour: Hour of day (0-23) when last accessed
        peak_hours: List of peak activity hours

    Returns:
        Adjusted access count
    """
    if last_accessed_hour in peak_hours:
        return access_count + 1
    return access_count
