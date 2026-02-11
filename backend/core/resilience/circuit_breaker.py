"""Circuit breaker for external service calls."""

import time
from enum import Enum
from backend.core.logging import get_logger

_log = get_logger("core.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker pattern implementation.

    States: CLOSED (normal) -> OPEN (failing) -> HALF_OPEN (probing) -> CLOSED
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_sec: float = 60.0,
        half_open_max_probes: int = 1,
    ):
        self.name = name
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._failure_threshold = failure_threshold
        self._cooldown_sec = cooldown_sec
        self._half_open_max = half_open_max_probes
        self._last_failure_time = 0.0
        self._half_open_probes = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self._cooldown_sec:
                self._state = CircuitState.HALF_OPEN
                self._half_open_probes = 0
        return self._state

    def record_success(self):
        """Record a successful operation."""
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            _log.info("Circuit closed", name=self.name)
        self._failure_count = 0

    def record_failure(self):
        """Record a failed operation."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN
            _log.warning(
                "Circuit opened",
                name=self.name,
                failures=self._failure_count,
            )

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            if self._half_open_probes < self._half_open_max:
                self._half_open_probes += 1
                return True
            return False
        return False
