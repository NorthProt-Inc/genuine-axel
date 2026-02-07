"""Tests for BrowserManager."""

import time
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_browser_singleton():
    """Reset BrowserManager singleton between tests."""
    from backend.protocols.mcp.research.browser import BrowserManager

    BrowserManager._instance = None
    yield
    BrowserManager._instance = None


class TestBrowserManagerSingleton:
    """Tests for BrowserManager singleton behavior."""

    @pytest.mark.asyncio
    async def test_get_instance_returns_same_object(self):
        from backend.protocols.mcp.research.browser import BrowserManager

        inst1 = await BrowserManager.get_instance()
        inst2 = await BrowserManager.get_instance()
        assert inst1 is inst2

    @pytest.mark.asyncio
    async def test_get_browser_manager_unified(self):
        """get_browser_manager should use BrowserManager.get_instance()."""
        from backend.protocols.mcp.research.browser import get_browser_manager, BrowserManager

        manager = await get_browser_manager()
        assert isinstance(manager, BrowserManager)

        manager2 = await get_browser_manager()
        assert manager is manager2


class TestBrowserManagerRestart:
    """Tests for browser restart on max uses exceeded."""

    @pytest.mark.asyncio
    async def test_restarts_after_max_uses(self):
        from backend.protocols.mcp.research.browser import BrowserManager

        manager = await BrowserManager.get_instance()

        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.close = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.close = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        mock_pw = AsyncMock()
        mock_pw.chromium = AsyncMock()
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_pw.stop = AsyncMock()

        mock_pw_factory = AsyncMock()
        mock_pw_factory.start = AsyncMock(return_value=mock_pw)

        with patch(
            "backend.protocols.mcp.research.browser.async_playwright",
            return_value=mock_pw_factory,
        ):
            # Simulate having a browser that exceeded max uses
            manager._playwright = mock_pw
            manager._browser = mock_browser
            manager._context = mock_context
            manager._use_count = manager._max_uses  # at limit

            page = await manager.get_page()

            # Should have cleaned up old resources
            mock_context.close.assert_called()
            mock_browser.close.assert_called()
            mock_pw.stop.assert_called()


class TestBrowserManagerIdleTimeout:
    """Tests for idle timeout cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_on_idle(self):
        from backend.protocols.mcp.research.browser import BrowserManager

        manager = await BrowserManager.get_instance()

        mock_context = AsyncMock()
        mock_browser = AsyncMock()
        mock_pw = AsyncMock()

        manager._playwright = mock_pw
        manager._browser = mock_browser
        manager._context = mock_context
        manager._last_used = time.time() - 600  # 10 min ago
        manager._idle_timeout = 300  # 5 min

        # Simulate idle check
        await manager._cleanup_inner()

        assert manager._playwright is None
        assert manager._browser is None
        assert manager._context is None
        assert manager._use_count == 0


class TestBrowserManagerCleanup:
    """Tests for resource cleanup on errors."""

    @pytest.mark.asyncio
    async def test_cleanup_inner_handles_exception(self):
        from backend.protocols.mcp.research.browser import BrowserManager

        manager = await BrowserManager.get_instance()

        mock_context = AsyncMock()
        mock_context.close = AsyncMock(side_effect=RuntimeError("close failed"))
        mock_browser = AsyncMock()
        mock_pw = AsyncMock()

        manager._playwright = mock_pw
        manager._browser = mock_browser
        manager._context = mock_context

        # Should not raise, and should still null out references
        await manager._cleanup_inner()

        assert manager._playwright is None
        assert manager._browser is None
        assert manager._context is None

    @pytest.mark.asyncio
    async def test_close_delegates_to_cleanup(self):
        from backend.protocols.mcp.research.browser import BrowserManager

        manager = await BrowserManager.get_instance()

        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        manager._playwright = mock_pw
        manager._browser = mock_browser
        manager._context = mock_context

        await manager.close()

        assert manager._playwright is None
