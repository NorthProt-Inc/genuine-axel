"""Tests for async_utils semaphore singleton via Lazy[T]."""

import asyncio


from backend.core.utils.async_utils import _get_semaphore


class TestSemaphoreSingleton:
    """_get_semaphore() should use Lazy[T] pattern."""

    def test_returns_semaphore(self) -> None:
        sem = _get_semaphore()
        assert isinstance(sem, asyncio.Semaphore)

    def test_returns_same_instance(self) -> None:
        first = _get_semaphore()
        second = _get_semaphore()
        assert first is second

    def test_reset_creates_new_instance(self) -> None:
        from backend.core.utils.lazy import Lazy

        first = _get_semaphore()
        Lazy.reset_all()
        second = _get_semaphore()
        assert first is not second
