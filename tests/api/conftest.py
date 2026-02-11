"""Shared fixtures for API layer tests.

Provides a mock application state, a FastAPI app with ``get_state`` patched
globally so that every module-level call to ``get_state()`` returns the mock,
and a Starlette TestClient wired to that app.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from backend.api.deps import AppState, get_state


def _build_mock_state() -> MagicMock:
    """Build a MagicMock that quacks like AppState.

    Every sub-service (memory_manager, long_term_memory, identity_manager,
    mcp_server, graph_rag, etc.) is a MagicMock so endpoint code that
    accesses nested attributes won't blow up.
    """
    state = MagicMock(spec=AppState)

    # Core memory components
    state.memory_manager = MagicMock()
    state.memory_manager.working = MagicMock()
    state.memory_manager.working.get_turn_count.return_value = 5
    state.memory_manager.working.MAX_TURNS = 30
    state.memory_manager.working.session_id = "sess-abc12345"
    state.memory_manager.long_term = MagicMock()
    state.memory_manager.long_term.get_stats.return_value = {"total_memories": 42}
    state.memory_manager.session_archive = MagicMock()
    state.memory_manager.session_archive.get_recent_summaries.return_value = []
    state.memory_manager.session_archive.get_recent_interaction_logs.return_value = []
    state.memory_manager.session_archive.get_interaction_stats.return_value = {}
    state.memory_manager.session_archive.get_sessions_by_date.return_value = []
    state.memory_manager.session_archive.get_session_detail.return_value = None
    state.memory_manager.session_archive.get_session_messages.return_value = []
    state.memory_manager.get_stats.return_value = {"working": {}, "permanent": {}}
    state.memory_manager.get_working_context.return_value = "Recent conversation context"
    state.memory_manager.build_smart_context.return_value = "Smart context"
    state.memory_manager.end_session = AsyncMock(return_value={"status": "ok"})
    state.memory_manager.graph_rag = MagicMock()
    state.memory_manager.knowledge_graph = MagicMock()
    state.memory_manager.knowledge_graph.entities = {}

    state.long_term_memory = MagicMock()
    state.long_term_memory.get_stats.return_value = {"total_memories": 42}
    state.long_term_memory.consolidate_memories.return_value = {
        "merged": 0,
        "decayed": 0,
    }
    state.long_term_memory.search.return_value = []
    state.long_term_memory.flush_access_updates.return_value = 0

    state.identity_manager = MagicMock()
    state.identity_manager.evolve = AsyncMock(return_value=0)
    state.identity_manager.get_traits.return_value = ["curious"]
    state.identity_manager.get_mood.return_value = "neutral"

    state.gemini_client = MagicMock()
    state.graph_rag = MagicMock()
    state.graph_rag.get_stats.return_value = {"entities": 0, "relations": 0}
    state.mcp_server = None  # created lazily by mcp router

    state.current_session_id = "sess-abc12345"
    state.last_activity = None
    state.turn_count = 5

    state.background_tasks = []
    state.shutdown_event = MagicMock()
    state.active_streams = set()  # Fix: should be set not list

    return state


# All modules that import get_state and call it at runtime.
# We patch every import site so that both FastAPI dependency injection
# and direct `get_state()` calls return our mock.
_GET_STATE_TARGETS = [
    "backend.api.deps.get_state",
    "backend.api.memory.get_state",
    "backend.api.status.get_state",
    "backend.api.openai.get_state",
    "backend.api.mcp.get_state",
]


@pytest.fixture()
def mock_state():
    """A MagicMock shaped like AppState with sensible defaults."""
    return _build_mock_state()


@pytest.fixture()
def app(mock_state):
    """FastAPI application with get_state monkey-patched everywhere.

    We import the app inside the fixture so module-level side-effects
    (like ensure_data_directories) only happen once per session.
    We also patch ``get_state`` in every module that imports it so both
    FastAPI dependency-injected calls and direct function calls see
    the mock.
    """
    from backend.app import app as real_app

    # Also override via FastAPI DI for any Depends(get_state) usage
    real_app.dependency_overrides[get_state] = lambda: mock_state

    patches = [patch(target, return_value=mock_state) for target in _GET_STATE_TARGETS]
    for p in patches:
        p.start()

    yield real_app

    for p in patches:
        p.stop()
    real_app.dependency_overrides.clear()


@pytest.fixture()
def client(app):
    """Starlette TestClient bound to the overridden FastAPI app.

    Uses raise_server_exceptions=False so we can assert on HTTP status
    codes (including 4xx/5xx) without the client raising Python exceptions.
    """
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def authed_client(app):
    """TestClient that always sends a valid API key header.

    Patches AXNMIHN_API_KEY to a known value and sets the matching
    Authorization header so every request passes require_api_key.
    """
    import backend.api.deps as deps_mod
    import backend.config as config_mod

    original_key_config = config_mod.AXNMIHN_API_KEY
    original_key_deps = deps_mod.AXNMIHN_API_KEY
    test_key = "test-secret-key-12345678"

    config_mod.AXNMIHN_API_KEY = test_key
    deps_mod.AXNMIHN_API_KEY = test_key

    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers.update({"Authorization": f"Bearer {test_key}"})
        yield c

    config_mod.AXNMIHN_API_KEY = original_key_config
    deps_mod.AXNMIHN_API_KEY = original_key_deps


@pytest.fixture()
def no_auth_client(app):
    """TestClient with API key authentication disabled (key unset)."""
    import backend.api.deps as deps_mod
    import backend.config as config_mod

    original_key_config = config_mod.AXNMIHN_API_KEY
    original_key_deps = deps_mod.AXNMIHN_API_KEY
    config_mod.AXNMIHN_API_KEY = ""
    deps_mod.AXNMIHN_API_KEY = ""

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    config_mod.AXNMIHN_API_KEY = original_key_config
    deps_mod.AXNMIHN_API_KEY = original_key_deps
