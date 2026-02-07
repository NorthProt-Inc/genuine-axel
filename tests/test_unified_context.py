"""Tests for MemoryManager context building and dead code removal.

Imports MemoryManager lazily via a fixture to handle the pre-existing
circular import in backend.core.__init__. We pre-seed the partially
initialized module before importing unified.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def MemoryManager():
    """Import MemoryManager, working around circular import.

    The circular chain is:
      backend.config → backend.core.logging → backend.core.__init__
      → backend.core.tools.__init__ → hass_ops → backend.config (partial)

    We break it by ensuring backend.config is fully loaded first via
    a direct attribute check, or by catching and retrying.
    """
    # First attempt: if backend.config is already fully loaded,
    # this will succeed.  Otherwise, try importing config first.
    try:
        import backend.config  # noqa: F401
    except ImportError:
        pass

    from backend.memory.unified import MemoryManager as _MM
    return _MM


class TestBuildSmartContextDelegation:
    """Verify build_smart_context delegates to _build_smart_context_sync."""

    def test_build_smart_context_calls_sync(self, MemoryManager) -> None:
        mm = MagicMock(spec=MemoryManager)
        mm._build_smart_context_sync = MagicMock(return_value="ctx")
        result = MemoryManager.build_smart_context(mm, "hello")
        mm._build_smart_context_sync.assert_called_once_with("hello")
        assert result == "ctx"

    def test_async_method_does_not_exist(self, MemoryManager) -> None:
        assert not hasattr(MemoryManager, "_build_smart_context_async")


class TestSessionArchiveBudgetDefined:
    """Verify SESSION_ARCHIVE_BUDGET class attribute exists."""

    def test_class_attribute_exists(self, MemoryManager) -> None:
        assert hasattr(MemoryManager, "SESSION_ARCHIVE_BUDGET")

    def test_value_is_positive_int(self, MemoryManager) -> None:
        assert isinstance(MemoryManager.SESSION_ARCHIVE_BUDGET, int)
        assert MemoryManager.SESSION_ARCHIVE_BUDGET > 0


class TestContextTruncation:
    """Verify context text is truncated via truncate_text."""

    def test_long_context_is_truncated(self, MemoryManager) -> None:
        """Context exceeding MAX_CONTEXT_TOKENS*4 should be truncated."""
        with patch.object(MemoryManager, "__init__", lambda self, **kw: None):
            mm = MemoryManager()
            mm.working = MagicMock()
            mm.working.get_progressive_context.return_value = ""
            mm.working.get_turn_count.return_value = 0
            mm.session_archive = MagicMock()
            mm.session_archive.get_time_since_last_session.return_value = None
            mm.session_archive.get_recent_summaries.return_value = ""
            mm.memgpt = MagicMock()
            mm.memgpt.context_budget_select.return_value = ([], 0)
            mm.graph_rag = None
            mm.MAX_CONTEXT_TOKENS = 10  # 40 chars max
            mm.LONG_TERM_BUDGET = 100
            mm.SESSION_ARCHIVE_BUDGET = 100
            mm._build_time_context = MagicMock(return_value="x" * 200)

            result = mm._build_smart_context_sync("test")
            assert len(result) <= 40
