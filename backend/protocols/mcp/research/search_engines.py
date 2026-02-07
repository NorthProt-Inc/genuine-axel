"""Web search functions: DuckDuckGo and Tavily."""

import asyncio
import os
import random
from urllib.parse import quote_plus

from backend.core.logging import get_logger
from backend.protocols.mcp.research.config import USER_AGENTS

_log = get_logger("research.search_engines")

# ---------------------------------------------------------------------------
# Tavily client singleton
# ---------------------------------------------------------------------------
TAVILY_API_KEY: str | None = os.getenv("TAVILY_API_KEY")


def _create_tavily_client():
    """Factory for Tavily client. Returns None if API key is missing."""
    if not TAVILY_API_KEY:
        return None
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=TAVILY_API_KEY)
        _log.info("Tavily client initialized")
        return client
    except Exception as e:
        _log.warning("Failed to init Tavily", error=str(e))
        return None


from backend.core.utils.lazy import Lazy

_tavily_client: Lazy = Lazy(_create_tavily_client)


def get_tavily_client():
    """Return the Tavily client singleton, creating it on first call.

    Returns:
        TavilyClient instance or None if API key is missing
    """
    return _tavily_client.get()


# ---------------------------------------------------------------------------
# DuckDuckGo search
# ---------------------------------------------------------------------------
async def search_duckduckgo(query: str, num_results: int = 5) -> list[dict]:
    """Search DuckDuckGo HTML endpoint and parse results.

    Args:
        query: Search query string
        num_results: Maximum number of results to return

    Returns:
        List of dicts with title, url, snippet keys
    """
    import aiohttp
    from bs4 import BeautifulSoup

    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    results: list[dict] = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, headers=headers, timeout=15) as response:
                if response.status != 200:
                    _log.error("DuckDuckGo search failed", status=response.status, query=query[:50])
                    return []

                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                for result in soup.select(".result")[:num_results]:
                    title_elem = result.select_one(".result__title a")
                    snippet_elem = result.select_one(".result__snippet")

                    if title_elem:
                        href = title_elem.get("href", "")
                        if "uddg=" in href:
                            import urllib.parse

                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                            actual_url = parsed.get("uddg", [href])[0]
                        else:
                            actual_url = href

                        results.append(
                            {
                                "title": title_elem.get_text(strip=True),
                                "url": actual_url,
                                "snippet": snippet_elem.get_text(strip=True) if snippet_elem else "",
                            }
                        )

    except asyncio.TimeoutError:
        _log.error("DuckDuckGo search timeout", query=query[:50])
    except Exception as e:
        _log.error("DuckDuckGo search error", query=query[:50], error=str(e))

    return results


# ---------------------------------------------------------------------------
# Web search (formatted markdown output)
# ---------------------------------------------------------------------------
async def web_search(query: str, num_results: int = 5) -> str:
    """Search the web and return formatted markdown results.

    Renamed from _google_search for clarity.

    Args:
        query: Search query string
        num_results: Maximum results

    Returns:
        Markdown-formatted search results
    """
    _log.info("DuckDuckGo search", query=query[:80], max_results=num_results)

    results = await search_duckduckgo(query, num_results)

    if not results:
        return f"No results found for query: {query}"

    output = f"## Search Results for: {query}\n\n"
    for i, r in enumerate(results, 1):
        output += f"### {i}. {r['title']}\n"
        output += f"**URL:** {r['url']}\n"
        if r["snippet"]:
            output += f"{r['snippet']}\n"
        output += "\n"

    return output


# ---------------------------------------------------------------------------
# Tavily search
# ---------------------------------------------------------------------------
async def tavily_search(query: str, max_results: int = 5, search_depth: str = "basic") -> str:
    """Search using Tavily API with AI-generated summary.

    Args:
        query: Search query
        max_results: Maximum number of results
        search_depth: "basic" or "advanced"

    Returns:
        Markdown-formatted results with AI summary
    """
    client = get_tavily_client()

    if not client:
        return " Tavily 검색 불가: TAVILY_API_KEY가 설정되지 않았습니다. web_search 또는 deep_research를 사용하세요."

    _log.info("Tavily search", query=query[:80], depth=search_depth, max_results=max_results)

    try:
        results = await asyncio.to_thread(
            client.search,
            query=query,
            max_results=max_results,
            include_answer=True,
            search_depth=search_depth,
        )

        output = f"## Tavily Search: {query}\n\n"

        if results.get("answer"):
            output += f"###  AI Summary\n{results['answer']}\n\n"

        output += "###  Sources\n\n"
        for i, r in enumerate(results.get("results", [])[:max_results], 1):
            output += f"**{i}. {r.get('title', 'N/A')}**\n"
            output += f"   URL: {r.get('url', 'N/A')}\n"
            content = r.get("content", "")[:300]
            if content:
                output += f"   {content}...\n"
            output += "\n"

        return output

    except Exception as e:
        _log.error("Tavily search failed", query=query[:50], error=str(e))
        return f" Tavily 검색 오류: {str(e)}"
