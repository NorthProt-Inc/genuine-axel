"""Tests for page visitor functions."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestVisitPage:
    """Tests for visit_page function."""

    @pytest.mark.asyncio
    async def test_normal_page_load(self):
        from backend.protocols.mcp.research.page_visitor import visit_page

        mock_page = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body><p>Hello World</p></body></html>")
        mock_page.title = AsyncMock(return_value="Test Page")
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.close = AsyncMock()

        mock_manager = AsyncMock()
        mock_manager.get_page = AsyncMock(return_value=mock_page)

        with patch(
            "backend.protocols.mcp.research.page_visitor.get_browser_manager",
            new_callable=AsyncMock,
            return_value=mock_manager,
        ), patch(
            "backend.protocols.mcp.research.page_visitor.process_content_for_artifact",
            side_effect=lambda url, content: content,
        ):
            result = await visit_page("https://example.com/page")

        assert "Test Page" in result
        assert "Hello World" in result
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_url_scheme(self):
        from backend.protocols.mcp.research.page_visitor import visit_page

        result = await visit_page("ftp://invalid.com/file")
        assert "Error" in result
        assert "Invalid URL scheme" in result

    @pytest.mark.asyncio
    async def test_timeout_returns_partial_content(self):
        from backend.protocols.mcp.research.page_visitor import visit_page

        mock_page = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()
        mock_page.goto = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_page.content = AsyncMock(return_value="<html><body><p>Partial content here that is long enough</p>" + "x" * 200 + "</body></html>")
        mock_page.title = AsyncMock(return_value="Partial")
        mock_page.close = AsyncMock()

        mock_manager = AsyncMock()
        mock_manager.get_page = AsyncMock(return_value=mock_page)

        with patch(
            "backend.protocols.mcp.research.page_visitor.get_browser_manager",
            new_callable=AsyncMock,
            return_value=mock_manager,
        ), patch(
            "backend.protocols.mcp.research.page_visitor.process_content_for_artifact",
            side_effect=lambda url, content: content,
        ):
            result = await visit_page("https://example.com/slow")

        assert "Partial" in result
        assert "timed out" in result.lower() or "partial" in result.lower()

    @pytest.mark.asyncio
    async def test_page_close_failure_is_handled(self):
        from backend.protocols.mcp.research.page_visitor import visit_page

        mock_page = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body><p>Content</p></body></html>")
        mock_page.title = AsyncMock(return_value="Test")
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.close = AsyncMock(side_effect=RuntimeError("close failed"))

        mock_manager = AsyncMock()
        mock_manager.get_page = AsyncMock(return_value=mock_page)

        with patch(
            "backend.protocols.mcp.research.page_visitor.get_browser_manager",
            new_callable=AsyncMock,
            return_value=mock_manager,
        ), patch(
            "backend.protocols.mcp.research.page_visitor.process_content_for_artifact",
            side_effect=lambda url, content: content,
        ):
            # Should not raise even though page.close() fails
            result = await visit_page("https://example.com/page")

        assert "Test" in result


class TestDeepDive:
    """Tests for deep_dive function."""

    @pytest.mark.asyncio
    async def test_search_then_visit(self):
        from backend.protocols.mcp.research.page_visitor import deep_dive

        mock_results = [
            {"title": "R1", "url": "https://example.com/1", "snippet": "S1"},
            {"title": "R2", "url": "https://example.com/2", "snippet": "S2"},
            {"title": "R3", "url": "https://example.com/3", "snippet": "S3"},
        ]

        with patch(
            "backend.protocols.mcp.research.page_visitor.search_duckduckgo",
            new_callable=AsyncMock,
            return_value=mock_results,
        ), patch(
            "backend.protocols.mcp.research.page_visitor.visit_page",
            new_callable=AsyncMock,
            return_value="# Page\n\nContent body here",
        ):
            result = await deep_dive("test research query")

        assert "Deep Dive Research" in result
        assert "Phase 1" in result
        assert "Phase 2" in result
        assert "Phase 3" in result
        assert "Sources Analyzed" in result

    @pytest.mark.asyncio
    async def test_no_search_results_early_return(self):
        from backend.protocols.mcp.research.page_visitor import deep_dive

        with patch(
            "backend.protocols.mcp.research.page_visitor.search_duckduckgo",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await deep_dive("nothing found")

        assert "failed" in result.lower() or "No search results" in result

    @pytest.mark.asyncio
    async def test_artifact_handling(self):
        from backend.protocols.mcp.research.page_visitor import deep_dive

        mock_results = [
            {"title": "R1", "url": "https://example.com/1", "snippet": "S1"},
        ]

        artifact_content = "[ARTIFACT SAVED]\nPath: /tmp/artifacts/test.md\nSummary of content"

        with patch(
            "backend.protocols.mcp.research.page_visitor.search_duckduckgo",
            new_callable=AsyncMock,
            return_value=mock_results,
        ), patch(
            "backend.protocols.mcp.research.page_visitor.visit_page",
            new_callable=AsyncMock,
            return_value=artifact_content,
        ):
            result = await deep_dive("artifact query")

        assert "ARTIFACT SAVED" in result
        assert "Saved Artifacts" in result
