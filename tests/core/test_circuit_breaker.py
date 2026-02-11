"""Tests for circuit breaker pattern."""

import time
from backend.core.utils.circuit_breaker import CircuitBreaker, CircuitState, CircuitConfig


class TestCircuitBreaker:

    def test_closed_allows_requests(self):
        cb = CircuitBreaker("test_closed", CircuitConfig(failure_threshold=3))
        assert cb.can_execute() is True
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker("test_opens", CircuitConfig(failure_threshold=3))
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker("test_half", CircuitConfig(failure_threshold=2, timeout_seconds=0.1))
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_on_success(self):
        cfg = CircuitConfig(failure_threshold=2, timeout_seconds=0.1, success_threshold=1)
        cb = CircuitBreaker("test_close_success", cfg)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.can_execute()  # trigger HALF_OPEN transition
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True

    def test_half_open_limits_calls(self):
        cfg = CircuitConfig(failure_threshold=1, timeout_seconds=0.1, half_open_max_calls=1)
        cb = CircuitBreaker("test_limit", cfg)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.can_execute() is True   # Transitions to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
        # Failure in HALF_OPEN goes back to OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False
