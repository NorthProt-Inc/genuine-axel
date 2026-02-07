"""Tests for rate_limiter singleton via Lazy[T]."""

from backend.core.utils.rate_limiter import get_embedding_limiter, TokenBucketRateLimiter


class TestRateLimiterSingleton:
    """get_embedding_limiter() should use Lazy[T] pattern."""

    def test_returns_token_bucket(self) -> None:
        limiter = get_embedding_limiter()
        assert isinstance(limiter, TokenBucketRateLimiter)

    def test_returns_same_instance(self) -> None:
        first = get_embedding_limiter()
        second = get_embedding_limiter()
        assert first is second

    def test_reset_creates_new_instance(self) -> None:
        from backend.core.utils.lazy import Lazy

        first = get_embedding_limiter()
        Lazy.reset_all()
        second = get_embedding_limiter()
        assert first is not second
