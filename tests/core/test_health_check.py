"""Tests for health check system."""

import pytest
from backend.core.health.health_check import (
    HealthChecker,
    HealthResult,
    HealthState,
)


class TestHealthChecker:

    @pytest.mark.asyncio
    async def test_all_healthy(self):
        checker = HealthChecker()

        async def check_ok():
            return HealthResult(HealthState.HEALTHY, 1.0, "ok")

        checker.register("db", check_ok)
        checker.register("cache", check_ok)

        results = await checker.check_all()
        assert checker.overall_state(results) == HealthState.HEALTHY

    @pytest.mark.asyncio
    async def test_one_unhealthy_degrades(self):
        checker = HealthChecker()

        async def check_ok():
            return HealthResult(HealthState.HEALTHY, 1.0)

        async def check_fail():
            return HealthResult(HealthState.UNHEALTHY, 0, "down")

        checker.register("db", check_ok)
        checker.register("cache", check_fail)

        results = await checker.check_all()
        assert checker.overall_state(results) == HealthState.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_exception_caught(self):
        checker = HealthChecker()

        async def check_crash():
            raise RuntimeError("boom")

        checker.register("bad", check_crash)

        results = await checker.check_all()
        assert results["bad"].state == HealthState.UNHEALTHY
        assert "boom" in results["bad"].message

    @pytest.mark.asyncio
    async def test_empty_checks(self):
        checker = HealthChecker()
        results = await checker.check_all()
        assert checker.overall_state(results) == HealthState.HEALTHY
