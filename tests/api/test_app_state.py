"""Tests for AppState as the single source of truth."""

from backend.api.deps import AppState, get_state, init_state


class TestGetState:
    """get_state() should always return the same singleton."""

    def test_returns_same_instance(self) -> None:
        s1 = get_state()
        s2 = get_state()
        assert s1 is s2

    def test_returns_app_state_type(self) -> None:
        assert isinstance(get_state(), AppState)


class TestInitState:
    """init_state() should set attributes on the singleton."""

    def test_sets_known_attributes(self) -> None:
        sentinel = object()
        init_state(gemini_client=sentinel)
        assert get_state().gemini_client is sentinel

    def test_ignores_unknown_attributes(self) -> None:
        init_state(nonexistent_field="value")
        assert not hasattr(get_state(), "nonexistent_field")


class TestAppStateReset:
    """AppState.reset() should restore all fields to defaults."""

    def test_reset_clears_all_fields(self) -> None:
        state = get_state()
        state.memory_manager = "fake_mm"
        state.long_term_memory = "fake_ltm"
        state.gemini_client = "fake_gem"
        state.graph_rag = "fake_gr"
        state.mcp_server = "fake_mcp"
        state.current_session_id = "sess_123"
        state.turn_count = 42
        state.background_tasks.append("task1")
        state.shutdown_event = "fake_event"
        state.active_streams.append("stream1")

        state.reset()

        assert state.memory_manager is None
        assert state.long_term_memory is None
        assert state.identity_manager is None
        assert state.gemini_client is None
        assert state.graph_rag is None
        assert state.mcp_server is None
        assert state.current_session_id == ""
        assert state.turn_count == 0
        assert state.background_tasks == []
        assert state.shutdown_event is None
        assert state.active_streams == []

    def test_reset_preserves_identity(self) -> None:
        """reset() should return the same object, not a new one."""
        state = get_state()
        state.gemini_client = "something"
        state.reset()
        assert state is get_state()
