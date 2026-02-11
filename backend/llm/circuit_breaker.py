"""Circuit breaker and adaptive timeout logic for LLM API calls.

This module provides:
- CircuitBreakerState: Prevents cascading failures by temporarily blocking requests
- AdaptiveTimeout: Dynamically adjusts timeouts based on latency history
"""

import time
from collections import deque

from backend.core.logging import get_logger
from backend.core.utils.timeouts import TIMEOUTS

_log = get_logger("llm.circuit_breaker")

# Timeout constants
API_CALL_TIMEOUT = TIMEOUTS.API_CALL
STREAM_CHUNK_TIMEOUT = TIMEOUTS.STREAM_CHUNK
CIRCUIT_BREAKER_DURATION = TIMEOUTS.CIRCUIT_BREAKER_DEFAULT
FIRST_CHUNK_BASE_TIMEOUT = TIMEOUTS.FIRST_CHUNK_BASE


class AdaptiveTimeout:
    """Dynamically adjusts API timeouts based on historical latency."""

    def __init__(self):
        self._recent_latencies: deque = deque(maxlen=10)

    def record_latency(self, latency_seconds: float):
        """Record a successful API call latency."""
        self._recent_latencies.append(latency_seconds)

    def calculate(self, tool_count: int, model: str, is_first_chunk: bool = True) -> int:
        """Calculate adaptive timeout for API calls.

        Args:
            tool_count: Number of tools available to the LLM
            model: Model name (for future per-model tuning)
            is_first_chunk: Whether this is the first chunk (vs subsequent chunks)

        Returns:
            Calculated timeout in seconds
        """
        if not is_first_chunk:
            return STREAM_CHUNK_TIMEOUT

        base = FIRST_CHUNK_BASE_TIMEOUT

        # Tool count factor (more tools = longer timeout)
        if tool_count <= 10:
            tool_factor = tool_count * 2
        elif tool_count <= 20:
            tool_factor = 20 + ((tool_count - 10) * 3)
        else:
            tool_factor = 50 + ((tool_count - 20) * 4)

        # Latency-based adjustment
        if self._recent_latencies:
            avg_latency = sum(self._recent_latencies) / len(self._recent_latencies)
            latency_factor = 1 + (avg_latency / 30)
            latency_factor = min(latency_factor, 2.0)
        else:
            latency_factor = 1.0

        timeout = int((base + tool_factor) * latency_factor)
        max_timeout = TIMEOUTS.API_CALL - 10
        return min(timeout, max_timeout)


# Global singleton instance
_adaptive_timeout = AdaptiveTimeout()


class CircuitBreakerState:
    """Circuit breaker to prevent cascading failures in LLM API calls.

    States:
    - closed: Normal operation, requests allowed
    - open: Too many failures, requests blocked
    - half-open: Testing if service recovered
    """

    def __init__(self):
        self._state = "closed"
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._cooldown_seconds = CIRCUIT_BREAKER_DURATION
        self._open_until = 0.0

    def record_failure(self, error_type: str):
        """Record an API failure and potentially open the circuit.

        Args:
            error_type: Type of error (rate_limit, server_error, timeout, etc.)
        """
        self._failure_count += 1
        self._last_failure_time = time.time()

        # Adjust cooldown based on error type
        if error_type == "rate_limit":
            self._cooldown_seconds = 300  # 5 minutes
        elif error_type == "server_error":
            self._cooldown_seconds = 60
        elif error_type == "timeout":
            self._cooldown_seconds = 30
        else:
            self._cooldown_seconds = CIRCUIT_BREAKER_DURATION

        # Open circuit after 5 consecutive failures
        if self._failure_count >= 5:
            self._state = "open"
            self._open_until = time.time() + self._cooldown_seconds
            _log.warning("circuit breaker opened",
                         err_type=error_type,
                         cooldown_s=self._cooldown_seconds,
                         failures=self._failure_count)

    def record_success(self):
        """Record a successful API call and potentially close the circuit."""
        self._failure_count = 0
        if self._state == "half-open":
            self._state = "closed"
            _log.info("circuit breaker closed")

    def can_proceed(self) -> bool:
        """Check if requests are currently allowed.

        Returns:
            True if requests should proceed, False if blocked
        """
        if self._state == "closed":
            return True

        if time.time() > self._open_until:
            self._state = "half-open"
            _log.info("circuit breaker half-open")
            return True

        return False

    def get_remaining_cooldown(self) -> int:
        """Get remaining cooldown time in seconds.

        Returns:
            Remaining seconds until circuit can be half-opened, or 0 if closed
        """
        if self._state == "closed":
            return 0
        remaining = int(self._open_until - time.time())
        return max(0, remaining)


def _calculate_dynamic_timeout(tool_count: int, is_first_chunk: bool = True, model: str | None = None) -> int:
    """Calculate dynamic timeout using global adaptive timeout instance.

    Args:
        tool_count: Number of tools available
        is_first_chunk: Whether this is the first chunk
        model: Optional model name

    Returns:
        Calculated timeout in seconds
    """
    return _adaptive_timeout.calculate(tool_count, model or "", is_first_chunk)


__all__ = [
    "AdaptiveTimeout",
    "CircuitBreakerState",
    "_adaptive_timeout",
    "_calculate_dynamic_timeout",
    "API_CALL_TIMEOUT",
    "STREAM_CHUNK_TIMEOUT",
    "CIRCUIT_BREAKER_DURATION",
    "FIRST_CHUNK_BASE_TIMEOUT",
]
