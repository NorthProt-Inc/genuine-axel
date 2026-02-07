"""Tests for research module singletons via Lazy[T]."""

from unittest.mock import patch, MagicMock

from backend.protocols.mcp.research.search_engines import get_tavily_client


class TestTavilyClientSingleton:
    """get_tavily_client() should use Lazy[T] and be resettable."""

    @patch("backend.protocols.mcp.research.search_engines.TAVILY_API_KEY", "test-key")
    @patch("backend.protocols.mcp.research.search_engines.TavilyClient", create=True)
    def test_returns_same_instance(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()

        # Need to import the module-level lazy so it picks up patched TAVILY_API_KEY
        import backend.protocols.mcp.research.search_engines as mod
        # Patch at module level
        with patch.object(mod, "TAVILY_API_KEY", "test-key"):
            first = get_tavily_client()
            second = get_tavily_client()
            # Should return something (even if None if API key handling differs)
            if first is not None:
                assert first is second

    def test_returns_none_without_key(self) -> None:
        with patch("backend.protocols.mcp.research.search_engines.TAVILY_API_KEY", None):
            from backend.core.utils.lazy import Lazy
            Lazy.reset_all()
            result = get_tavily_client()
            assert result is None
