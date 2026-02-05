"""
Web search service for ChatHandler.

Handles web search operations using Tavily API.
"""

import time
from dataclasses import dataclass
from typing import Optional

from backend.core.logging import get_logger, request_tracker as rt
from backend.config import MAX_SEARCH_CONTEXT_CHARS

_log = get_logger("services.search")


def _truncate_text(text: str, max_chars: int, label: str = "") -> str:
    """Truncate text to max_chars with suffix indicator."""
    if not text:
        return ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    suffix = "\n... (truncated)"
    keep = max_chars - len(suffix)
    if keep <= 0:
        return text[:max_chars]
    if label:
        _log.debug("truncate", section=label, chars=len(text), limit=max_chars)
    return text[:keep].rstrip() + suffix


@dataclass
class SearchResult:
    """Result from a web search operation."""

    context: str
    success: bool
    failed: bool = False
    source: str = "tavily"
    elapsed_ms: float = 0.0


class SearchService:
    """Web search service using Tavily API."""

    def __init__(
        self,
        max_results: int = 5,
        search_depth: str = "basic",
        max_context_chars: int = MAX_SEARCH_CONTEXT_CHARS
    ):
        """Initialize search service.

        Args:
            max_results: Maximum number of search results
            search_depth: Tavily search depth ("basic" or "advanced")
            max_context_chars: Maximum characters for search context
        """
        self.max_results = max_results
        self.search_depth = search_depth
        self.max_context_chars = max_context_chars

    async def search(self, query: str) -> SearchResult:
        """
        Perform web search and return formatted context.

        Args:
            query: Search query string

        Returns:
            SearchResult with context and status
        """
        if not query:
            return SearchResult(context="", success=False, failed=True)

        _log.debug("SEARCH start", query=query[:50])
        start_time = time.perf_counter()

        try:
            from backend.protocols.mcp.research_server import _tavily_search

            search_context = await _tavily_search(
                query,
                max_results=self.max_results,
                search_depth=self.search_depth
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if search_context and "검색 불가" not in search_context:
                # Truncate if needed
                search_context = _truncate_text(
                    search_context,
                    self.max_context_chars,
                    label="search_context"
                )

                _log.debug(
                    "SEARCH done",
                    chars=len(search_context),
                    dur_ms=round(elapsed_ms, 1)
                )

                rt.log_search(
                    query=query[:50],
                    results=1,
                    elapsed_ms=elapsed_ms
                )

                return SearchResult(
                    context=search_context,
                    success=True,
                    failed=False,
                    elapsed_ms=elapsed_ms
                )

            return SearchResult(
                context="",
                success=False,
                failed=True,
                elapsed_ms=elapsed_ms
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            _log.warning("SEARCH fail", error=str(e))
            return SearchResult(
                context="",
                success=False,
                failed=True,
                elapsed_ms=elapsed_ms
            )

    async def search_if_needed(
        self,
        query: str,
        should_search: bool
    ) -> SearchResult:
        """
        Conditionally perform search based on flag.

        Args:
            query: Search query
            should_search: Whether to actually perform search

        Returns:
            SearchResult (empty if not searching)
        """
        if not should_search:
            return SearchResult(context="", success=False, failed=False)
        return await self.search(query)
