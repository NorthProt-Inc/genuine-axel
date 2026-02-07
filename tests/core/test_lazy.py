"""Tests for Lazy[T] singleton descriptor."""

import threading
from unittest.mock import MagicMock

from backend.core.utils.lazy import Lazy


class TestLazyGet:
    """Lazy.get() should invoke factory and return instance."""

    def test_get_calls_factory_and_returns_instance(self) -> None:
        factory = MagicMock(return_value="hello")
        lazy: Lazy[str] = Lazy(factory)

        result = lazy.get()

        factory.assert_called_once()
        assert result == "hello"

    def test_repeated_get_returns_same_instance(self) -> None:
        factory = MagicMock(return_value=object())
        lazy: Lazy[object] = Lazy(factory)

        first = lazy.get()
        second = lazy.get()

        assert first is second
        factory.assert_called_once()


class TestLazyReset:
    """reset() should clear cached instance; next get() creates new one."""

    def test_reset_then_get_creates_new_instance(self) -> None:
        call_count = 0

        def factory() -> object:
            nonlocal call_count
            call_count += 1
            return object()

        lazy: Lazy[object] = Lazy(factory)

        first = lazy.get()
        lazy.reset()
        second = lazy.get()

        assert first is not second
        assert call_count == 2


class TestLazyResetAll:
    """reset_all() should clear all Lazy instances."""

    def test_reset_all_clears_every_lazy(self) -> None:
        lazy_a: Lazy[object] = Lazy(object)
        lazy_b: Lazy[object] = Lazy(object)

        a1 = lazy_a.get()
        b1 = lazy_b.get()

        Lazy.reset_all()

        a2 = lazy_a.get()
        b2 = lazy_b.get()

        assert a1 is not a2
        assert b1 is not b2


class TestLazyThreadSafety:
    """Concurrent get() calls should return the same instance."""

    def test_concurrent_get_returns_same_instance(self) -> None:
        results: list[object] = []
        barrier = threading.Barrier(8)

        def slow_factory() -> object:
            import time
            time.sleep(0.01)
            return object()

        lazy: Lazy[object] = Lazy(slow_factory)

        def worker() -> None:
            barrier.wait()
            results.append(lazy.get())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 8
        assert all(r is results[0] for r in results)
