"""Tests for backend.core.services.search_service."""

import pytest
from unittest.mock import AsyncMock, patch

from backend.core.services.search_service import (
    SearchService,
    SearchResult,
    _truncate_text,
)


# ── _truncate_text ───────────────────────────────────────────────────────


class TestTruncateText:
    def test_empty_text(self):
        assert _truncate_text("", 100) == ""

    def test_none_like_empty(self):
        """Empty string regardless of max_chars."""
        assert _truncate_text("", 0) == ""

    def test_no_truncation_needed(self):
        text = "hello world"
        assert _truncate_text(text, 100) == text

    def test_exact_length_no_truncation(self):
        text = "a" * 50
        assert _truncate_text(text, 50) == text

    def test_truncates_long_text(self):
        text = "a" * 200
        result = _truncate_text(text, 100, label="test")
        assert len(result) <= 100
        assert result.endswith("... (truncated)")

    def test_max_chars_zero(self):
        assert _truncate_text("hello", 0) == ""

    def test_very_small_max(self):
        """When max_chars is smaller than the suffix, keep <= max_chars."""
        result = _truncate_text("hello world", 5)
        # keep = 5 - len("\n... (truncated)") => negative, so text[:5]
        assert len(result) <= 5

    def test_max_chars_equal_to_suffix_length(self):
        suffix = "\n... (truncated)"
        result = _truncate_text("a" * 100, len(suffix))
        # keep = 0, so fallback to text[:max_chars]
        assert len(result) <= len(suffix)

    def test_preserves_content_before_suffix(self):
        text = "The quick brown fox jumps over the lazy dog"
        result = _truncate_text(text, 30)
        # Should contain start of original text
        assert result.startswith("The")

    def test_label_does_not_affect_output(self):
        text = "a" * 200
        r1 = _truncate_text(text, 100)
        r2 = _truncate_text(text, 100, label="section")
        assert r1 == r2


# ── SearchResult dataclass ───────────────────────────────────────────────


class TestSearchResult:
    def test_defaults(self):
        r = SearchResult(context="ctx", success=True)
        assert r.failed is False
        assert r.source == "tavily"
        assert r.elapsed_ms == 0.0

    def test_custom_fields(self):
        r = SearchResult(
            context="data",
            success=False,
            failed=True,
            source="custom",
            elapsed_ms=123.4,
        )
        assert r.context == "data"
        assert r.source == "custom"


# ── SearchService.search ─────────────────────────────────────────────────


class TestSearch:
    async def test_empty_query(self):
        svc = SearchService()
        result = await svc.search("")
        assert result.success is False
        assert result.failed is True
        assert result.context == ""

    @patch(
        "backend.core.services.search_service.rt",
    )
    async def test_success(self, mock_rt):
        mock_tavily = AsyncMock(return_value="Search result: Python is great.")

        with patch(
            "backend.protocols.mcp.research.search_engines.tavily_search",
            mock_tavily,
        ):
            svc = SearchService(max_results=3, search_depth="basic", max_context_chars=5000)
            result = await svc.search("python language")

        assert result.success is True
        assert result.failed is False
        assert "Python is great" in result.context
        assert result.elapsed_ms > 0

        mock_tavily.assert_awaited_once()
        call_kwargs = mock_tavily.call_args
        assert call_kwargs[1]["max_results"] == 3
        assert call_kwargs[1]["search_depth"] == "basic"

    @patch(
        "backend.core.services.search_service.rt",
    )
    async def test_returns_unavailable(self, mock_rt):
        """When tavily_search returns 검색 불가, result is failed."""
        mock_tavily = AsyncMock(
            return_value="Tavily 검색 불가: TAVILY_API_KEY가 설정되지 않았습니다."
        )

        with patch(
            "backend.protocols.mcp.research.search_engines.tavily_search",
            mock_tavily,
        ):
            svc = SearchService()
            result = await svc.search("anything")

        assert result.success is False
        assert result.failed is True
        assert result.context == ""

    @patch(
        "backend.core.services.search_service.rt",
    )
    async def test_returns_empty_context(self, mock_rt):
        """When tavily_search returns empty string, result is failed."""
        mock_tavily = AsyncMock(return_value="")
        with patch(
            "backend.protocols.mcp.research.search_engines.tavily_search",
            mock_tavily,
        ):
            svc = SearchService()
            result = await svc.search("query")

        assert result.success is False
        assert result.failed is True

    @patch(
        "backend.core.services.search_service.rt",
    )
    async def test_returns_none_context(self, mock_rt):
        """When tavily_search returns None, result is failed."""
        mock_tavily = AsyncMock(return_value=None)
        with patch(
            "backend.protocols.mcp.research.search_engines.tavily_search",
            mock_tavily,
        ):
            svc = SearchService()
            result = await svc.search("query")

        assert result.success is False
        assert result.failed is True

    async def test_exception(self):
        mock_tavily = AsyncMock(side_effect=RuntimeError("network error"))
        with patch(
            "backend.protocols.mcp.research.search_engines.tavily_search",
            mock_tavily,
        ):
            svc = SearchService()
            result = await svc.search("anything")

        assert result.success is False
        assert result.failed is True
        assert result.context == ""
        assert result.elapsed_ms >= 0

    @patch(
        "backend.core.services.search_service.rt",
    )
    async def test_truncation_applied(self, mock_rt):
        """Long search results should be truncated to max_context_chars."""
        long_text = "x" * 500
        mock_tavily = AsyncMock(return_value=long_text)
        with patch(
            "backend.protocols.mcp.research.search_engines.tavily_search",
            mock_tavily,
        ):
            svc = SearchService(max_context_chars=100)
            result = await svc.search("query")

        assert result.success is True
        assert len(result.context) <= 100


# ── SearchService.search_if_needed ───────────────────────────────────────


class TestSearchIfNeeded:
    async def test_false_skips_search(self):
        svc = SearchService()
        result = await svc.search_if_needed("something", should_search=False)
        assert result.success is False
        assert result.failed is False
        assert result.context == ""

    async def test_true_performs_search(self):
        mock_tavily = AsyncMock(return_value="found it")
        with patch(
            "backend.protocols.mcp.research.search_engines.tavily_search",
            mock_tavily,
        ), patch(
            "backend.core.services.search_service.rt",
        ):
            svc = SearchService(max_context_chars=5000)
            result = await svc.search_if_needed("query", should_search=True)

        assert result.success is True
        assert "found it" in result.context

    async def test_true_with_empty_query(self):
        """Even if should_search is True, empty query still fails."""
        svc = SearchService()
        result = await svc.search_if_needed("", should_search=True)
        assert result.success is False
        assert result.failed is True


# ── SearchService constructor defaults ───────────────────────────────────


class TestSearchServiceInit:
    def test_defaults(self):
        svc = SearchService()
        assert svc.max_results == 5
        assert svc.search_depth == "basic"
        # max_context_chars comes from config.MAX_SEARCH_CONTEXT_CHARS
        assert isinstance(svc.max_context_chars, int)

    def test_custom_values(self):
        svc = SearchService(max_results=10, search_depth="advanced", max_context_chars=1000)
        assert svc.max_results == 10
        assert svc.search_depth == "advanced"
        assert svc.max_context_chars == 1000
