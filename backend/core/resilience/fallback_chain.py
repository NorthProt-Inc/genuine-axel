"""LLM provider fallback chain with circuit breakers."""

import asyncio
from typing import Any, Callable, List, TypeVar
from backend.core.logging import get_logger

_log = get_logger("core.fallback")
T = TypeVar("T")


async def with_retry(
    fn: Callable,
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 5.0,
) -> Any:
    """Exponential backoff retry."""
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            if attempt == max_retries:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            _log.debug(
                "Retry",
                attempt=attempt + 1,
                delay_sec=round(delay, 2),
                error=str(e)[:80],
            )
            await asyncio.sleep(delay)


class FallbackChain:
    """Chain of providers with circuit breakers and fallback."""

    def __init__(self, providers: List[dict]):
        """Initialize fallback chain.

        Args:
            providers: List of dicts with keys:
                - name: Provider name
                - fn: Async callable
                - breaker: CircuitBreaker instance
        """
        self._providers = providers

    async def call(self, *args, **kwargs) -> Any:
        """Call providers in order, falling back on failure."""
        last_error = None
        for p in self._providers:
            if not p["breaker"].allow_request():
                _log.debug("Provider skipped (circuit open)", provider=p["name"])
                continue
            try:
                result = await with_retry(lambda p=p: p["fn"](*args, **kwargs))
                p["breaker"].record_success()
                return result
            except Exception as e:
                p["breaker"].record_failure()
                last_error = e
                _log.warning(
                    "Provider failed",
                    provider=p["name"],
                    error=str(e)[:80],
                )
        raise last_error or RuntimeError("All providers exhausted")
