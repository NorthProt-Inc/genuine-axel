"""Tests for Health Check types enhancement (Wave 1.2).

Tests ComponentHealth and HealthStatus aggregation added to existing
health_check module.
"""

import time

import pytest

from backend.core.health.health_check import (
    HealthState,
    HealthResult,
    HealthChecker,
    ComponentHealth,
    HealthStatus,
)


class TestComponentHealth:
    """Tests for ComponentHealth dataclass."""

    def test_basic_creation(self):
        ch = ComponentHealth(
            name="database",
            state=HealthState.HEALTHY,
            latency_ms=1.5,
        )
        assert ch.name == "database"
        assert ch.state == HealthState.HEALTHY
        assert ch.latency_ms == 1.5

    def test_message_default_empty(self):
        ch = ComponentHealth(name="db", state=HealthState.HEALTHY, latency_ms=0.5)
        assert ch.message == ""

    def test_message_set(self):
        ch = ComponentHealth(
            name="db",
            state=HealthState.UNHEALTHY,
            latency_ms=500.0,
            message="connection refused",
        )
        assert ch.message == "connection refused"

    def test_last_check_auto_set(self):
        before = time.time()
        ch = ComponentHealth(name="db", state=HealthState.HEALTHY, latency_ms=1.0)
        after = time.time()
        assert before <= ch.last_check <= after

    def test_last_check_custom(self):
        ts = 1700000000.0
        ch = ComponentHealth(
            name="db",
            state=HealthState.HEALTHY,
            latency_ms=1.0,
            last_check=ts,
        )
        assert ch.last_check == ts

    def test_to_dict(self):
        ch = ComponentHealth(
            name="redis",
            state=HealthState.DEGRADED,
            latency_ms=50.0,
            message="slow",
        )
        d = ch.to_dict()
        assert d["name"] == "redis"
        assert d["state"] == "degraded"
        assert d["latency_ms"] == 50.0
        assert d["message"] == "slow"
        assert "last_check" in d


class TestHealthStatus:
    """Tests for aggregated HealthStatus."""

    def test_basic_creation(self):
        components = [
            ComponentHealth(name="db", state=HealthState.HEALTHY, latency_ms=1.0),
            ComponentHealth(name="redis", state=HealthState.HEALTHY, latency_ms=0.5),
        ]
        status = HealthStatus(components=components)
        assert status.overall == HealthState.HEALTHY
        assert len(status.components) == 2

    def test_degraded_if_any_degraded(self):
        components = [
            ComponentHealth(name="db", state=HealthState.HEALTHY, latency_ms=1.0),
            ComponentHealth(name="redis", state=HealthState.DEGRADED, latency_ms=100.0),
        ]
        status = HealthStatus(components=components)
        assert status.overall == HealthState.DEGRADED

    def test_unhealthy_if_any_unhealthy(self):
        components = [
            ComponentHealth(name="db", state=HealthState.UNHEALTHY, latency_ms=0.0),
            ComponentHealth(name="redis", state=HealthState.DEGRADED, latency_ms=100.0),
        ]
        status = HealthStatus(components=components)
        assert status.overall == HealthState.UNHEALTHY

    def test_empty_components_healthy(self):
        status = HealthStatus(components=[])
        assert status.overall == HealthState.HEALTHY

    def test_uptime_seconds(self):
        status = HealthStatus(components=[])
        assert status.uptime_seconds >= 0

    def test_to_dict(self):
        components = [
            ComponentHealth(name="db", state=HealthState.HEALTHY, latency_ms=1.0),
        ]
        status = HealthStatus(components=components)
        d = status.to_dict()
        assert d["overall"] == "healthy"
        assert "uptime_seconds" in d
        assert "components" in d
        assert len(d["components"]) == 1
        assert d["components"][0]["name"] == "db"


class TestExistingHealthCheckUnchanged:
    """Ensure existing HealthChecker behavior is preserved."""

    def test_health_checker_exists(self):
        checker = HealthChecker()
        assert hasattr(checker, "register")
        assert hasattr(checker, "check_all")
        assert hasattr(checker, "overall_state")

    def test_health_result_exists(self):
        r = HealthResult(HealthState.HEALTHY, 1.0)
        assert r.state == HealthState.HEALTHY

    @pytest.mark.asyncio
    async def test_check_all_empty(self):
        checker = HealthChecker()
        results = await checker.check_all()
        assert results == {}
