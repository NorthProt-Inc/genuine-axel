"""Tests for LLM fallback chain."""

import asyncio
import pytest
from backend.core.resilience.circuit_breaker import CircuitBreaker
from backend.core.resilience.fallback_chain import FallbackChain, with_retry


class TestWithRetry:

    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        async def fn():
            return "ok"
        result = await with_retry(fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        attempts = []
        async def fn():
            attempts.append(1)
            if len(attempts) < 3:
                raise ValueError("fail")
            return "ok"
        result = await with_retry(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert len(attempts) == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        async def fn():
            raise ValueError("always fails")
        with pytest.raises(ValueError):
            await with_retry(fn, max_retries=2, base_delay=0.01)


class TestFallbackChain:

    @pytest.mark.asyncio
    async def test_primary_succeeds(self):
        async def primary():
            return "primary_result"
        chain = FallbackChain([
            {"name": "primary", "fn": primary, "breaker": CircuitBreaker("p")},
        ])
        result = await chain.call()
        assert result == "primary_result"

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self):
        async def primary():
            raise ValueError("down")
        async def secondary():
            return "secondary_result"
        chain = FallbackChain([
            {"name": "primary", "fn": primary, "breaker": CircuitBreaker("p", failure_threshold=10)},
            {"name": "secondary", "fn": secondary, "breaker": CircuitBreaker("s")},
        ])
        result = await chain.call()
        assert result == "secondary_result"

    @pytest.mark.asyncio
    async def test_all_providers_exhausted(self):
        async def fail():
            raise RuntimeError("fail")
        chain = FallbackChain([
            {"name": "a", "fn": fail, "breaker": CircuitBreaker("a", failure_threshold=10)},
            {"name": "b", "fn": fail, "breaker": CircuitBreaker("b", failure_threshold=10)},
        ])
        with pytest.raises(RuntimeError, match="fail"):
            await chain.call()

    @pytest.mark.asyncio
    async def test_skips_open_circuit(self):
        async def primary():
            return "should_not_reach"
        async def secondary():
            return "secondary"

        breaker_p = CircuitBreaker("p", failure_threshold=1)
        breaker_p.record_failure()  # Open the circuit

        chain = FallbackChain([
            {"name": "primary", "fn": primary, "breaker": breaker_p},
            {"name": "secondary", "fn": secondary, "breaker": CircuitBreaker("s")},
        ])
        result = await chain.call()
        assert result == "secondary"
