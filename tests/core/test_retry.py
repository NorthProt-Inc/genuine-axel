"""Unit tests for backend.core.utils.retry module."""


import pytest

from backend.core.utils.retry import (
    RetryConfig,
    calculate_backoff,
    classify_error,
    is_retryable_error,
    retry_async,
    retry_async_generator,
    retry_sync,
)


# ---------------------------------------------------------------------------
# RetryConfig
# ---------------------------------------------------------------------------

class TestRetryConfig:

    def test_default_config_values(self) -> None:
        cfg = RetryConfig()
        assert cfg.max_retries == 5
        assert cfg.base_delay == 2.0
        assert cfg.max_delay == 60.0
        assert cfg.jitter == 0.3
        assert cfg.retryable_check is None

    def test_custom_config_overrides(self) -> None:
        check = lambda e: True
        cfg = RetryConfig(max_retries=2, base_delay=1.0, retryable_check=check)
        assert cfg.max_retries == 2
        assert cfg.base_delay == 1.0
        assert cfg.retryable_check is check

    def test_retryable_check_takes_precedence(self) -> None:
        """retryable_check should be used over pattern matching."""
        cfg = RetryConfig(retryable_check=lambda e: False)
        # "429" is in default retryable_patterns, but check says no
        err = Exception("429 rate limited")
        assert is_retryable_error(err, cfg) is False


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------

class TestClassifyError:

    def test_429_classified_as_rate_limit(self) -> None:
        assert classify_error(Exception("429 Too Many Requests")) == "rate_limit"

    def test_503_classified_as_server_error(self) -> None:
        assert classify_error(Exception("503 Service Unavailable")) == "server_error"

    def test_timeout_classified_as_timeout(self) -> None:
        assert classify_error(Exception("Request timeout")) == "timeout"

    def test_ssl_classified_as_ssl(self) -> None:
        assert classify_error(Exception("SSL handshake failed")) == "ssl"

    def test_unknown_classified_as_unknown(self) -> None:
        assert classify_error(Exception("something weird")) == "unknown"


# ---------------------------------------------------------------------------
# calculate_backoff
# ---------------------------------------------------------------------------

class TestCalculateBackoff:

    def test_exponential_growth(self) -> None:
        cfg = RetryConfig(base_delay=1.0, jitter=0.0)
        b1 = calculate_backoff(1, "unknown", cfg)
        b2 = calculate_backoff(2, "unknown", cfg)
        b3 = calculate_backoff(3, "unknown", cfg)
        assert b1 == pytest.approx(1.0)
        assert b2 == pytest.approx(2.0)
        assert b3 == pytest.approx(4.0)

    def test_server_error_multiplier_1_5x(self) -> None:
        cfg = RetryConfig(base_delay=1.0, jitter=0.0)
        b = calculate_backoff(1, "server_error", cfg)
        assert b == pytest.approx(1.5)

    def test_max_delay_cap(self) -> None:
        cfg = RetryConfig(base_delay=1.0, max_delay=10.0, jitter=0.0)
        b = calculate_backoff(10, "unknown", cfg)
        assert b <= 10.0

    def test_jitter_applied(self) -> None:
        cfg = RetryConfig(base_delay=1.0, jitter=0.5)
        values = {calculate_backoff(1, "unknown", cfg) for _ in range(20)}
        # With jitter > 0, we should see some variation
        assert len(values) > 1


# ---------------------------------------------------------------------------
# is_retryable_error
# ---------------------------------------------------------------------------

class TestIsRetryableError:

    def test_pattern_matching(self) -> None:
        assert is_retryable_error(Exception("503 server error")) is True
        assert is_retryable_error(Exception("something random")) is False

    def test_custom_retryable_check(self) -> None:
        cfg = RetryConfig(retryable_check=lambda e: isinstance(e, ValueError))
        assert is_retryable_error(ValueError("val"), cfg) is True
        assert is_retryable_error(TypeError("type"), cfg) is False

    def test_retryable_check_overrides_patterns(self) -> None:
        """When retryable_check returns False, patterns should be ignored."""
        cfg = RetryConfig(retryable_check=lambda e: False)
        # "503" matches default pattern, but check says no
        assert is_retryable_error(Exception("503"), cfg) is False


# ---------------------------------------------------------------------------
# retry_async
# ---------------------------------------------------------------------------

class TestRetryAsync:

    async def test_success_on_first_attempt(self) -> None:
        call_count = 0

        async def success() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_async(success, config=RetryConfig(max_retries=3))
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_retryable_error(self) -> None:
        call_count = 0

        async def fail_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("503 service unavailable")
            return "ok"

        cfg = RetryConfig(max_retries=5, base_delay=0.01, jitter=0.0)
        result = await retry_async(fail_then_succeed, config=cfg)
        assert result == "ok"
        assert call_count == 3

    async def test_raises_on_non_retryable_error(self) -> None:
        async def bad() -> None:
            raise ValueError("not retryable at all")

        cfg = RetryConfig(max_retries=3, base_delay=0.01)
        with pytest.raises(ValueError, match="not retryable"):
            await retry_async(bad, config=cfg)

    async def test_exhausts_retries(self) -> None:
        call_count = 0

        async def always_fail() -> None:
            nonlocal call_count
            call_count += 1
            raise Exception("503 always failing")

        cfg = RetryConfig(max_retries=3, base_delay=0.01, jitter=0.0)
        with pytest.raises(Exception, match="503"):
            await retry_async(always_fail, config=cfg)
        assert call_count == 3

    async def test_on_retry_callback_called(self) -> None:
        on_retry_calls: list = []

        async def fail_then_succeed() -> str:
            if len(on_retry_calls) < 1:
                raise Exception("503 error")
            return "ok"

        cfg = RetryConfig(max_retries=3, base_delay=0.01, jitter=0.0)
        result = await retry_async(
            fail_then_succeed,
            config=cfg,
            on_retry=lambda attempt, err, delay: on_retry_calls.append((attempt, str(err))),
        )
        assert result == "ok"
        assert len(on_retry_calls) == 1
        assert on_retry_calls[0][0] == 1


# ---------------------------------------------------------------------------
# retry_sync
# ---------------------------------------------------------------------------

class TestRetrySync:

    def test_success_on_first_attempt(self) -> None:
        call_count = 0

        def success() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = retry_sync(success, config=RetryConfig(max_retries=3))
        assert result == "ok"
        assert call_count == 1

    def test_retries_on_retryable_error(self) -> None:
        call_count = 0

        def fail_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("timeout error")
            return "ok"

        cfg = RetryConfig(max_retries=3, base_delay=0.01, jitter=0.0)
        result = retry_sync(fail_then_succeed, config=cfg)
        assert result == "ok"
        assert call_count == 2

    def test_raises_on_non_retryable_error(self) -> None:
        def bad() -> None:
            raise KeyError("nope")

        cfg = RetryConfig(max_retries=3, base_delay=0.01)
        with pytest.raises(KeyError):
            retry_sync(bad, config=cfg)

    def test_exhausts_retries(self) -> None:
        call_count = 0

        def always_fail() -> None:
            nonlocal call_count
            call_count += 1
            raise Exception("503 stuck")

        cfg = RetryConfig(max_retries=2, base_delay=0.01, jitter=0.0)
        with pytest.raises(Exception, match="503"):
            retry_sync(always_fail, config=cfg)
        assert call_count == 2


# ---------------------------------------------------------------------------
# retry_async_generator
# ---------------------------------------------------------------------------

class TestRetryAsyncGenerator:

    async def test_successful_generator_yields_all_items(self) -> None:
        async def factory() -> None:
            for item in ["a", "b", "c"]:
                yield item

        items = []
        async for item in retry_async_generator(factory, config=RetryConfig(max_retries=3)):
            items.append(item)
        assert items == ["a", "b", "c"]

    async def test_retries_on_retryable_error_during_iteration(self) -> None:
        call_count = 0

        async def factory() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield "partial"
                raise Exception("503 unavailable")
            yield "a"
            yield "b"

        cfg = RetryConfig(max_retries=3, base_delay=0.01, jitter=0.0)
        items = []
        async for item in retry_async_generator(factory, config=cfg):
            items.append(item)
        # First attempt yields "partial" then fails; second attempt yields "a", "b"
        assert items == ["partial", "a", "b"]

    async def test_no_retry_on_non_retryable_error(self) -> None:
        call_count = 0

        async def factory() -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")
            yield  # make it a generator  # noqa: F811

        cfg = RetryConfig(max_retries=3, base_delay=0.01)
        with pytest.raises(ValueError, match="bad input"):
            async for _ in retry_async_generator(factory, config=cfg):
                pass
        assert call_count == 1

    async def test_exhausted_retries_raises_last_error(self) -> None:
        call_count = 0

        async def factory() -> None:
            nonlocal call_count
            call_count += 1
            raise Exception("503 always broken")
            yield  # noqa: F811

        cfg = RetryConfig(max_retries=2, base_delay=0.01, jitter=0.0)
        with pytest.raises(Exception, match="503"):
            async for _ in retry_async_generator(factory, config=cfg):
                pass
        assert call_count == 2

    async def test_on_retry_callback_called(self) -> None:
        on_retry_calls: list = []
        call_count = 0

        async def factory() -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("503 fail")
            yield "ok"

        cfg = RetryConfig(max_retries=5, base_delay=0.01, jitter=0.0)
        items = []
        async for item in retry_async_generator(
            factory,
            config=cfg,
            on_retry=lambda attempt, err, delay: on_retry_calls.append(attempt),
        ):
            items.append(item)
        assert items == ["ok"]
        assert on_retry_calls == [1, 2]

    async def test_respects_config_max_retries(self) -> None:
        call_count = 0

        async def factory() -> None:
            nonlocal call_count
            call_count += 1
            raise Exception("timeout error")
            yield  # noqa: F811

        cfg = RetryConfig(max_retries=4, base_delay=0.01, jitter=0.0)
        with pytest.raises(Exception, match="timeout"):
            async for _ in retry_async_generator(factory, config=cfg):
                pass
        assert call_count == 4
