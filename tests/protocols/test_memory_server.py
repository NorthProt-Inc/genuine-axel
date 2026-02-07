"""Tests for memory_server _get_memory_components() without caching."""

from unittest.mock import MagicMock

from backend.api.deps import get_state


class TestGetMemoryComponents:
    """_get_memory_components() should read from AppState directly, no caching."""

    def test_returns_current_state_values(self) -> None:
        from backend.protocols.mcp.memory_server import _get_memory_components

        state = get_state()
        mock_mm = MagicMock()
        mock_mm.session_archive = MagicMock()
        mock_mm.graph_rag = MagicMock()
        state.memory_manager = mock_mm
        state.long_term_memory = MagicMock()

        mm, ltm, sa, gr = _get_memory_components()

        assert mm is mock_mm
        assert ltm is state.long_term_memory
        assert sa is mock_mm.session_archive
        assert gr is mock_mm.graph_rag

    def test_reflects_state_changes(self) -> None:
        """After AppState changes, _get_memory_components returns new values."""
        from backend.protocols.mcp.memory_server import _get_memory_components

        state = get_state()

        # First: set something
        mm1 = MagicMock()
        mm1.session_archive = MagicMock()
        mm1.graph_rag = MagicMock()
        state.memory_manager = mm1
        state.long_term_memory = MagicMock()

        result1 = _get_memory_components()
        assert result1[0] is mm1

        # Second: change state
        mm2 = MagicMock()
        mm2.session_archive = MagicMock()
        mm2.graph_rag = MagicMock()
        state.memory_manager = mm2
        state.long_term_memory = MagicMock()

        result2 = _get_memory_components()
        assert result2[0] is mm2
        assert result2[0] is not mm1

    def test_returns_nones_when_no_memory_manager(self) -> None:
        from backend.protocols.mcp.memory_server import _get_memory_components

        state = get_state()
        state.memory_manager = None
        state.long_term_memory = None

        mm, ltm, sa, gr = _get_memory_components()

        assert mm is None
        assert ltm is None
        assert sa is None
        assert gr is None
