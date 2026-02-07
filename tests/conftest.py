"""Root conftest: resets all global state after every test."""

import pytest

from backend.core.utils.lazy import Lazy
from backend.api.deps import get_state


@pytest.fixture(autouse=True)
def _reset_global_state():
    """Reset all Lazy singletons and AppState after each test."""
    yield
    Lazy.reset_all()
    get_state().reset()
