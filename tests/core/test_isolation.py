"""Tests verifying that Lazy singletons are reset between test functions."""

from backend.core.utils.lazy import Lazy

# Use a list-based factory to generate unique instances
_call_count = {"n": 0}


def _counting_factory() -> dict:
    _call_count["n"] += 1
    return {"call": _call_count["n"]}


_shared_lazy: Lazy[dict] = Lazy(_counting_factory)


class TestIsolationA:
    """First test creates a singleton instance."""

    def test_create_singleton(self) -> None:
        instance = _shared_lazy.get()
        assert instance is not None
        TestIsolationA.call_number = instance["call"]


class TestIsolationB:
    """Second test must see a fresh singleton (factory called again)."""

    def test_singleton_is_fresh(self) -> None:
        instance = _shared_lazy.get()
        assert instance is not None
        # After conftest autouse fixture resets, factory runs again
        # so call number must be higher.
        assert instance["call"] > TestIsolationA.call_number
