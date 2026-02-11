"""Tests for backend.core.utils.async_utils."""

import asyncio
import time
from unittest.mock import patch, MagicMock

import pytest

from backend.core.utils.async_utils import (
    ConcurrencyLimitError,
    _MAX_CONCURRENT_THREADS,
    bounded_to_thread,
)


# ---------------------------------------------------------------------------
# ConcurrencyLimitError
# ---------------------------------------------------------------------------


class TestConcurrencyLimitError:
    def test_is_exception(self):
        assert issubclass(ConcurrencyLimitError, Exception)

    def test_message(self):
        err = ConcurrencyLimitError("too busy")
        assert str(err) == "too busy"


# ---------------------------------------------------------------------------
# bounded_to_thread — basic functionality
# ---------------------------------------------------------------------------


class TestBoundedToThread:
    async def test_runs_sync_function_in_thread(self):
        def add(a, b):
            return a + b

        result = await bounded_to_thread(add, 2, 3)
        assert result == 5

    async def test_passes_kwargs(self):
        def greet(name, greeting="hello"):
            return f"{greeting} {name}"

        result = await bounded_to_thread(greet, "world", greeting="hi")
        assert result == "hi world"

    async def test_returns_none_from_void_function(self):
        def noop():
            pass

        result = await bounded_to_thread(noop)
        assert result is None

    async def test_propagates_exception_from_function(self):
        def fail():
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            await bounded_to_thread(fail)

    async def test_function_timeout_raises_timeout_error(self):
        def slow():
            time.sleep(10)

        with pytest.raises(TimeoutError, match="timed out"):
            await bounded_to_thread(slow, timeout_seconds=0.1)

    async def test_timeout_message_includes_function_name(self):
        def my_slow_func():
            time.sleep(10)

        with pytest.raises(TimeoutError, match="my_slow_func"):
            await bounded_to_thread(my_slow_func, timeout_seconds=0.1)


# ---------------------------------------------------------------------------
# bounded_to_thread — concurrency limiting
# ---------------------------------------------------------------------------


class TestBoundedToThreadConcurrency:
    async def test_max_concurrent_threads_constant(self):
        assert _MAX_CONCURRENT_THREADS == 8

    async def test_concurrent_tasks_within_limit(self):
        """Multiple tasks within the limit should all complete."""
        results = []

        def work(n):
            time.sleep(0.01)
            return n

        tasks = [bounded_to_thread(work, i, timeout_seconds=5) for i in range(4)]
        results = await asyncio.gather(*tasks)

        assert sorted(results) == [0, 1, 2, 3]

    async def test_semaphore_acquire_timeout_raises_concurrency_error(self):
        """If the semaphore can't be acquired within 5s, ConcurrencyLimitError is raised."""
        # Create a mock semaphore that never grants
        never_sem = asyncio.Semaphore(0)

        with patch("backend.core.utils.async_utils._get_semaphore", return_value=never_sem):
            with pytest.raises(ConcurrencyLimitError, match="Could not acquire"):
                await bounded_to_thread(lambda: None, timeout_seconds=10)

    async def test_semaphore_released_on_success(self):
        """Semaphore count should be restored after successful execution."""
        sem = asyncio.Semaphore(_MAX_CONCURRENT_THREADS)

        with patch("backend.core.utils.async_utils._get_semaphore", return_value=sem):
            await bounded_to_thread(lambda: 42)

        # All permits should be back (Semaphore._value == _MAX_CONCURRENT_THREADS)
        # We verify by trying to acquire all of them
        for _ in range(_MAX_CONCURRENT_THREADS):
            assert sem._value > 0 or True  # just verify no deadlock
            await asyncio.wait_for(sem.acquire(), timeout=0.1)

    async def test_semaphore_released_on_exception(self):
        """Semaphore must be released even if the function raises."""
        sem = asyncio.Semaphore(_MAX_CONCURRENT_THREADS)

        with patch("backend.core.utils.async_utils._get_semaphore", return_value=sem):
            with pytest.raises(RuntimeError):
                await bounded_to_thread(lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        # Semaphore should still be available
        acquired = sem.acquire()
        # This would hang if semaphore was leaked
        await asyncio.wait_for(acquired, timeout=0.5)

    async def test_semaphore_released_on_timeout(self):
        """Semaphore must be released even on timeout."""
        sem = asyncio.Semaphore(_MAX_CONCURRENT_THREADS)

        with patch("backend.core.utils.async_utils._get_semaphore", return_value=sem):
            with pytest.raises(TimeoutError):
                await bounded_to_thread(lambda: time.sleep(10), timeout_seconds=0.1)

        # Verify all permits restored
        for _ in range(_MAX_CONCURRENT_THREADS):
            await asyncio.wait_for(sem.acquire(), timeout=0.5)


# ---------------------------------------------------------------------------
# bounded_to_thread — edge cases
# ---------------------------------------------------------------------------


class TestBoundedToThreadEdgeCases:
    async def test_zero_timeout_raises_immediately(self):
        """A timeout of 0 should cause near-immediate timeout."""
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await bounded_to_thread(lambda: time.sleep(1), timeout_seconds=0)

    async def test_function_returning_large_value(self):
        def big():
            return list(range(10000))

        result = await bounded_to_thread(big)
        assert len(result) == 10000

    async def test_function_with_no_args(self):
        def get_answer():
            return 42

        result = await bounded_to_thread(get_answer)
        assert result == 42
