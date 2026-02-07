"""Integration tests for research module refactoring."""

import pytest
from unittest.mock import AsyncMock, patch


class TestModuleImports:
    """Verify all modules are importable via the new paths."""

    def test_import_config(self):
        from backend.protocols.mcp.research.config import (
            BROWSER_MAX_USES,
            BROWSER_IDLE_TIMEOUT,
            SELECTOR_TIMEOUT_MS,
            PAGE_TIMEOUT_MS,
            NAVIGATION_TIMEOUT_MS,
            MAX_CONTENT_LENGTH,
            EXCLUDED_TAGS,
            AD_PATTERNS,
            USER_AGENTS,
        )

    def test_import_html_processor(self):
        from backend.protocols.mcp.research.html_processor import clean_html, html_to_markdown

    def test_import_search_engines(self):
        from backend.protocols.mcp.research.search_engines import (
            search_duckduckgo,
            web_search,
            tavily_search,
            get_tavily_client,
        )

    def test_import_browser(self):
        from backend.protocols.mcp.research.browser import BrowserManager, get_browser_manager

    def test_import_page_visitor(self):
        from backend.protocols.mcp.research.page_visitor import visit_page, deep_dive

    def test_import_via_package_init(self):
        from backend.protocols.mcp.research import (
            BrowserManager,
            get_browser_manager,
            clean_html,
            html_to_markdown,
            search_duckduckgo,
            web_search,
            tavily_search,
            get_tavily_client,
            visit_page,
            deep_dive,
        )

    def test_backward_compat_aliases_in_research_server(self):
        """Backward-compatible aliases still importable from research_server."""
        from backend.protocols.mcp.research_server import (
            _google_search,
            _tavily_search,
            _visit_page,
            _deep_dive,
            web_search,
        )

    def test_backward_compat_from_mcp_init(self):
        """mcp/__init__.py still exports the old names."""
        from backend.protocols.mcp import (
            search_duckduckgo,
            _visit_page,
            _deep_dive,
            _tavily_search,
        )


class TestMcpToolSchema:
    """Verify MCP server lists the correct tools."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_six(self):
        from backend.protocols.mcp.research_server import list_tools

        tools = await list_tools()
        assert len(tools) == 6

        tool_names = {t.name for t in tools}
        assert tool_names == {
            "google_search",
            "visit_page",
            "deep_dive",
            "tavily_search",
            "read_artifact",
            "list_artifacts",
        }

    @pytest.mark.asyncio
    async def test_call_tool_dispatches_web_search(self):
        from backend.protocols.mcp.research_server import call_tool

        with patch(
            "backend.protocols.mcp.research_server.web_search",
            new_callable=AsyncMock,
            return_value="## Search Results for: test\n\n",
        ):
            result = await call_tool("google_search", {"query": "test"})

        assert len(result) == 1
        assert "Search Results" in result[0].text

    @pytest.mark.asyncio
    async def test_call_tool_dispatches_visit_page(self):
        from backend.protocols.mcp.research_server import call_tool

        with patch(
            "backend.protocols.mcp.research_server.visit_page",
            new_callable=AsyncMock,
            return_value="# Page Title\n\nContent",
        ):
            result = await call_tool("visit_page", {"url": "https://example.com"})

        assert len(result) == 1
        assert "Page Title" in result[0].text

    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool(self):
        from backend.protocols.mcp.research_server import call_tool

        result = await call_tool("nonexistent_tool", {})
        assert "Unknown tool" in result[0].text


class TestResearchToolsImports:
    """Verify research_tools.py uses new import paths."""

    def test_web_search_tool_imports_correctly(self):
        """research_tools web_search should import from new module."""
        from backend.core.mcp_tools.research_tools import web_search

        assert callable(web_search)

    def test_visit_webpage_tool_imports_correctly(self):
        from backend.core.mcp_tools.research_tools import visit_webpage

        assert callable(visit_webpage)

    def test_deep_research_tool_imports_correctly(self):
        from backend.core.mcp_tools.research_tools import deep_research

        assert callable(deep_research)

    def test_tavily_search_tool_imports_correctly(self):
        from backend.core.mcp_tools.research_tools import tavily_search

        assert callable(tavily_search)
