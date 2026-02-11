"""Tests for circuit breaker pattern."""

import time
import pytest
from unittest.mock import patch
from backend.core.resilience.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreaker:

    def test_closed_allows_requests(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        assert cb.allow_request() is True
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker("test", failure_threshold=2, cooldown_sec=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_closes_on_success(self):
        cb = CircuitBreaker("test", failure_threshold=2, cooldown_sec=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_half_open_limits_probes(self):
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=0.1, half_open_max_probes=1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.allow_request() is True  # First probe
        assert cb.allow_request() is False  # Second probe blocked
