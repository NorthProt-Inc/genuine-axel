"""Component health check system."""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Callable, Awaitable, Any

from backend.core.logging import get_logger

_log = get_logger("core.health")

_START_TIME = time.time()


class HealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthResult:
    state: HealthState
    latency_ms: float
    message: str = ""


@dataclass
class ComponentHealth:
    """Per-component health status with latency tracking."""

    name: str
    state: HealthState
    latency_ms: float
    message: str = ""
    last_check: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "latency_ms": self.latency_ms,
            "message": self.message,
            "last_check": self.last_check,
        }


@dataclass
class HealthStatus:
    """Aggregated system health status."""

    components: list[ComponentHealth]

    @property
    def overall(self) -> HealthState:
        if not self.components:
            return HealthState.HEALTHY
        states = [c.state for c in self.components]
        if HealthState.UNHEALTHY in states:
            return HealthState.UNHEALTHY
        if HealthState.DEGRADED in states:
            return HealthState.DEGRADED
        return HealthState.HEALTHY

    @property
    def uptime_seconds(self) -> float:
        return time.time() - _START_TIME

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.value,
            "uptime_seconds": self.uptime_seconds,
            "components": [c.to_dict() for c in self.components],
        }


class HealthChecker:
    """Manages component health checks."""

    def __init__(self):
        self._checks: Dict[str, Callable[[], Awaitable[HealthResult]]] = {}

    def register(self, name: str, check_fn: Callable[[], Awaitable[HealthResult]]):
        """Register a health check function."""
        self._checks[name] = check_fn

    async def check_all(self) -> Dict[str, HealthResult]:
        """Run all registered health checks concurrently."""

        async def _run_check(name: str, fn: Callable[[], Awaitable[HealthResult]]) -> tuple[str, HealthResult]:
            t0 = time.monotonic()
            try:
                return name, await fn()
            except Exception as e:
                latency = (time.monotonic() - t0) * 1000
                return name, HealthResult(
                    HealthState.UNHEALTHY, latency, str(e)[:200]
                )

        if not self._checks:
            return {}

        pairs = await asyncio.gather(
            *(_run_check(name, fn) for name, fn in self._checks.items())
        )
        return dict(pairs)

    def overall_state(self, results: Dict[str, HealthResult]) -> HealthState:
        """Determine overall health from component results."""
        states = [r.state for r in results.values()]
        if not states:
            return HealthState.HEALTHY
        if HealthState.UNHEALTHY in states:
            return HealthState.UNHEALTHY
        if HealthState.DEGRADED in states:
            return HealthState.DEGRADED
        return HealthState.HEALTHY
