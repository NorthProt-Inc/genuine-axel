"""Tests for backend.core.mcp_tools.research_tools -- Research tool handlers.

Each tool is tested for:
  - Successful invocation with valid arguments
  - Missing/empty required parameters
  - Invalid parameter values
  - External dependency failure (exceptions)
  - Edge cases
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.core.mcp_tools.research_tools import (
    deep_research,
    list_artifacts_tool,
    read_artifact_tool,
    tavily_search,
    visit_webpage,
    web_search,
)


# ===========================================================================
# web_search
# ===========================================================================


class TestWebSearch:
    async def test_success(self, mock_web_search_engine):
        result = await web_search({"query": "python asyncio tutorial", "num_results": 3})
        text = result[0].text
        assert "Example Result" in text
        mock_web_search_engine.assert_awaited_once_with("python asyncio tutorial", 3)

    async def test_default_num_results(self, mock_web_search_engine):
        await web_search({"query": "test"})
        mock_web_search_engine.assert_awaited_once_with("test", 5)

    async def test_empty_query_returns_error(self):
        result = await web_search({"query": ""})
        assert "Error" in result[0].text
        assert "query parameter is required" in result[0].text

    async def test_missing_query_returns_error(self):
        result = await web_search({})
        assert "Error" in result[0].text

    async def test_num_results_below_one(self):
        result = await web_search({"query": "test", "num_results": 0})
        assert "Error" in result[0].text

    async def test_num_results_above_ten(self):
        result = await web_search({"query": "test", "num_results": 11})
        assert "Error" in result[0].text

    async def test_num_results_not_int(self):
        result = await web_search({"query": "test", "num_results": "five"})
        assert "Error" in result[0].text

    async def test_search_engine_exception(self):
        with patch(
            "backend.protocols.mcp.research.search_engines.web_search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DuckDuckGo down"),
        ):
            result = await web_search({"query": "test"})
        assert "Error" in result[0].text
        assert "DuckDuckGo down" in result[0].text


# ===========================================================================
# visit_webpage
# ===========================================================================


class TestVisitWebpage:
    async def test_success(self, mock_visit_page):
        result = await visit_webpage({"url": "https://example.com/article"})
        text = result[0].text
        assert "Page Title" in text
        mock_visit_page.assert_awaited_once_with("https://example.com/article")

    async def test_empty_url_returns_error(self):
        result = await visit_webpage({"url": ""})
        assert "Error" in result[0].text
        assert "url parameter is required" in result[0].text

    async def test_missing_url_returns_error(self):
        result = await visit_webpage({})
        assert "Error" in result[0].text

    async def test_invalid_scheme(self):
        result = await visit_webpage({"url": "ftp://example.com"})
        assert "Error" in result[0].text
        assert "http" in result[0].text.lower()

    async def test_no_scheme(self):
        result = await visit_webpage({"url": "example.com"})
        assert "Error" in result[0].text

    async def test_http_accepted(self, mock_visit_page):
        await visit_webpage({"url": "http://example.com"})
        mock_visit_page.assert_awaited_once_with("http://example.com")

    async def test_visitor_exception(self):
        with patch(
            "backend.protocols.mcp.research.page_visitor.visit_page",
            new_callable=AsyncMock,
            side_effect=TimeoutError("page load timeout"),
        ):
            result = await visit_webpage({"url": "https://example.com"})
        assert "Error" in result[0].text
        assert "page load timeout" in result[0].text


# ===========================================================================
# deep_research
# ===========================================================================


class TestDeepResearch:
    async def test_success(self, mock_deep_dive):
        result = await deep_research({"query": "How does GraphRAG work?"})
        text = result[0].text
        assert "Research Report" in text
        mock_deep_dive.assert_awaited_once_with("How does GraphRAG work?")

    async def test_empty_query_returns_error(self):
        result = await deep_research({"query": ""})
        assert "Error" in result[0].text

    async def test_missing_query_returns_error(self):
        result = await deep_research({})
        assert "Error" in result[0].text

    async def test_deep_dive_exception(self):
        with patch(
            "backend.protocols.mcp.research.page_visitor.deep_dive",
            new_callable=AsyncMock,
            side_effect=RuntimeError("playwright crashed"),
        ):
            result = await deep_research({"query": "test"})
        assert "Error" in result[0].text
        assert "playwright crashed" in result[0].text


# ===========================================================================
# tavily_search
# ===========================================================================


class TestTavilySearch:
    async def test_success(self, mock_tavily_search_engine):
        result = await tavily_search({
            "query": "AI news",
            "max_results": 3,
            "search_depth": "advanced",
        })
        text = result[0].text
        assert "Tavily" in text
        mock_tavily_search_engine.assert_awaited_once_with(
            query="AI news",
            max_results=3,
            search_depth="advanced",
        )

    async def test_default_values(self, mock_tavily_search_engine):
        await tavily_search({"query": "test"})
        mock_tavily_search_engine.assert_awaited_once_with(
            query="test",
            max_results=5,
            search_depth="basic",
        )

    async def test_empty_query_returns_error(self):
        result = await tavily_search({"query": ""})
        assert "Error" in result[0].text

    async def test_missing_query_returns_error(self):
        result = await tavily_search({})
        assert "Error" in result[0].text

    async def test_invalid_max_results_zero(self):
        result = await tavily_search({"query": "test", "max_results": 0})
        assert "Error" in result[0].text

    async def test_invalid_max_results_over_ten(self):
        result = await tavily_search({"query": "test", "max_results": 11})
        assert "Error" in result[0].text

    async def test_invalid_max_results_not_int(self):
        result = await tavily_search({"query": "test", "max_results": "five"})
        assert "Error" in result[0].text

    async def test_invalid_search_depth(self):
        result = await tavily_search({"query": "test", "search_depth": "deep"})
        assert "Error" in result[0].text

    async def test_tavily_exception(self):
        with patch(
            "backend.protocols.mcp.research.search_engines.tavily_search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API key invalid"),
        ):
            result = await tavily_search({"query": "test"})
        assert "Error" in result[0].text
        assert "API key invalid" in result[0].text


# ===========================================================================
# read_artifact_tool
# ===========================================================================


class TestReadArtifactTool:
    async def test_success(self, mock_read_artifact):
        result = await read_artifact_tool({"path": "/artifacts/example.md"})
        text = result[0].text
        assert "Artifact Content" in text
        assert "Full artifact content here" in text
        mock_read_artifact.assert_called_once_with("/artifacts/example.md")

    async def test_empty_path_returns_error(self):
        result = await read_artifact_tool({"path": ""})
        assert "Error" in result[0].text
        assert "path parameter is required" in result[0].text

    async def test_missing_path_returns_error(self):
        result = await read_artifact_tool({})
        assert "Error" in result[0].text

    async def test_artifact_not_found(self):
        with patch("backend.core.research_artifacts.read_artifact", return_value=None):
            result = await read_artifact_tool({"path": "/missing/artifact.md"})
        assert "not found" in result[0].text.lower()

    async def test_read_exception(self):
        with patch(
            "backend.core.research_artifacts.read_artifact",
            side_effect=IOError("disk error"),
        ):
            result = await read_artifact_tool({"path": "/some/path.md"})
        assert "Error" in result[0].text
        assert "disk error" in result[0].text


# ===========================================================================
# list_artifacts_tool
# ===========================================================================


class TestListArtifactsTool:
    async def test_success(self, mock_list_artifacts):
        result = await list_artifacts_tool({"limit": 10})
        text = result[0].text
        assert "Research Artifacts" in text
        assert "example.com" in text
        assert "4,096 bytes" in text
        mock_list_artifacts.assert_called_once_with(10)

    async def test_default_limit(self, mock_list_artifacts):
        await list_artifacts_tool({})
        mock_list_artifacts.assert_called_once_with(20)

    async def test_empty_list(self):
        with patch("backend.core.research_artifacts.list_artifacts", return_value=[]):
            result = await list_artifacts_tool({})
        assert "No research artifacts found" in result[0].text

    async def test_invalid_limit_zero(self):
        result = await list_artifacts_tool({"limit": 0})
        assert "Error" in result[0].text

    async def test_invalid_limit_over_100(self):
        result = await list_artifacts_tool({"limit": 101})
        assert "Error" in result[0].text

    async def test_invalid_limit_not_int(self):
        result = await list_artifacts_tool({"limit": "twenty"})
        assert "Error" in result[0].text

    async def test_list_exception(self):
        with patch(
            "backend.core.research_artifacts.list_artifacts",
            side_effect=IOError("disk error"),
        ):
            result = await list_artifacts_tool({})
        assert "Error" in result[0].text
        assert "disk error" in result[0].text

    async def test_multiple_artifacts_formatted(self):
        artifacts = [
            {
                "path": "/artifacts/a.md",
                "url": "https://a.com",
                "saved_at": "2025-01-01",
                "size": 1024,
            },
            {
                "path": "/artifacts/b.md",
                "url": "https://b.com",
                "saved_at": "2025-01-02",
                "size": 2048,
            },
        ]
        with patch("backend.core.research_artifacts.list_artifacts", return_value=artifacts):
            result = await list_artifacts_tool({})
        text = result[0].text
        assert "a.com" in text
        assert "b.com" in text
        assert "1,024 bytes" in text
        assert "2,048 bytes" in text
