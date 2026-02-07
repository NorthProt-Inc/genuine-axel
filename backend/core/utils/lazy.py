"""Thread-safe lazy singleton descriptor.

Provides a unified pattern for all module-level singletons in the project.
Supports reset() for test isolation and reset_all() for global teardown.
"""

import threading
import weakref
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class Lazy(Generic[T]):
    """Thread-safe lazy-initialized singleton.

    Usage:
        _client = Lazy(lambda: create_client())

        def get_client() -> Client:
            return _client.get()
    """

    _all_instances: list["weakref.ref[Lazy]"] = []
    _registry_lock = threading.Lock()

    def __init__(self, factory: Callable[[], T]) -> None:
        self._factory = factory
        self._instance: T | None = None
        self._lock = threading.Lock()
        with Lazy._registry_lock:
            Lazy._all_instances.append(weakref.ref(self))

    def get(self) -> T:
        """Return the cached instance, creating it on first call.

        Uses double-checked locking for thread safety.
        """
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = self._factory()
        return self._instance

    def reset(self) -> None:
        """Clear the cached instance. Next get() will call factory again."""
        with self._lock:
            self._instance = None

    @classmethod
    def reset_all(cls) -> None:
        """Reset every Lazy instance created so far."""
        with cls._registry_lock:
            alive: list[weakref.ref[Lazy]] = []
            for ref in cls._all_instances:
                obj = ref()
                if obj is not None:
                    obj.reset()
                    alive.append(ref)
            cls._all_instances = alive
