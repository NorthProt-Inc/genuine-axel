import asyncio
import time
from dataclasses import dataclass
from typing import Optional
from backend.core.logging import get_logger

logger = get_logger("rate-limiter")

@dataclass
class RateLimitConfig:

    requests_per_minute: int = 100
    burst_size: int = 10
    retry_after_seconds: float = 1.0

class TokenBucketRateLimiter:

    def __init__(self, config: Optional[RateLimitConfig] = None, name: str = "default"):
        self.config = config or RateLimitConfig()
        self.name = name
        self._tokens: float = float(self.config.burst_size)
        self._last_update: float = time.monotonic()
        self._lock = asyncio.Lock()

        self._refill_rate = self.config.requests_per_minute / 60.0

        logger.debug(
            f"RateLimiter '{name}' initialized: "
            f"rate={self.config.requests_per_minute}/min, "
            f"burst={self.config.burst_size}"
        )

    async def acquire(self, timeout: float = 30.0) -> bool:

        start_time = time.monotonic()

        while True:
            async with self._lock:
                self._refill_tokens()

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True

            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                logger.warning(
                    f"RateLimiter '{self.name}' timeout after {elapsed:.1f}s"
                )
                return False

            wait_time = min(
                1.0 / self._refill_rate,
                timeout - elapsed,
                self.config.retry_after_seconds
            )
            await asyncio.sleep(wait_time)

    def try_acquire(self) -> bool:

        self._refill_tokens()

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def _refill_tokens(self) -> None:

        now = time.monotonic()
        elapsed = now - self._last_update
        self._last_update = now

        self._tokens = min(
            float(self.config.burst_size),
            self._tokens + elapsed * self._refill_rate
        )

    @property
    def available_tokens(self) -> float:

        self._refill_tokens()
        return self._tokens

from backend.core.utils.lazy import Lazy

_embedding_limiter: Lazy[TokenBucketRateLimiter] = Lazy(
    lambda: TokenBucketRateLimiter(
        config=RateLimitConfig(
            requests_per_minute=1000,
            burst_size=50,
            retry_after_seconds=0.5,
        ),
        name="embedding",
    )
)


def get_embedding_limiter() -> TokenBucketRateLimiter:
    """Get the singleton embedding rate limiter."""
    return _embedding_limiter.get()
