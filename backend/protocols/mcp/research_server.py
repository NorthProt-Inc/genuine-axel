import asyncio
import json
import random
import re
import sys
import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus, urljoin, urlparse

AXEL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AXEL_ROOT))

from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.types as types

from backend.core.logging import get_logger
from backend.core.research_artifacts import (
    process_content_for_artifact,
    read_artifact,
    should_save_as_artifact,
    list_artifacts,
    ARTIFACT_THRESHOLD,
)

_log = get_logger("protocols.research")

import os
from dotenv import load_dotenv
load_dotenv(AXEL_ROOT / ".env")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
_tavily_client = None

def get_tavily_client():

    global _tavily_client
    if _tavily_client is None and TAVILY_API_KEY:
        try:
            from tavily import TavilyClient
            _tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
            _log.info("Tavily client initialized")
        except Exception as e:
            _log.warning("Failed to init Tavily", error=str(e))
    return _tavily_client

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

PAGE_TIMEOUT_MS = 240000
NAVIGATION_TIMEOUT_MS = 600000

MAX_CONTENT_LENGTH = 75000
EXCLUDED_TAGS = [
    'script', 'style', 'noscript', 'iframe', 'svg', 'path', 'meta', 'link',
    'header', 'footer', 'nav', 'aside', 'advertisement', 'ads', 'ad-container',
    'cookie-banner', 'cookie-consent', 'popup', 'modal', 'sidebar'
]

research_server = Server("research-mcp")

class BrowserManager:

    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._use_count = 0
        self._max_uses = 50

    @classmethod
    async def get_instance(cls) -> "BrowserManager":

        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def get_page(self):

        from playwright.async_api import async_playwright

        async with self._lock:

            if self._browser and self._use_count >= self._max_uses:
                _log.info("Browser restart needed", uses=self._use_count, max_uses=self._max_uses)
                await self._cleanup()

            if self._playwright is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-gpu',
                        '--disable-extensions',
                    ]
                )
                self._context = await self._browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US',
                    timezone_id='America/New_York',
                )

                await self._context.route("**/*.{png,jpg,jpeg,gif,svg,ico,webp,woff,woff2,ttf}",
                                          lambda route: route.abort())
                _log.info("Browser launched successfully")

            self._use_count += 1
            return await self._context.new_page()

    async def _cleanup(self):

        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            _log.error("Browser cleanup error", error=str(e))
        finally:
            self._playwright = None
            self._browser = None
            self._context = None
            self._use_count = 0

    async def close(self):

        async with self._lock:
            await self._cleanup()

browser_manager: Optional[BrowserManager] = None

async def get_browser_manager() -> BrowserManager:

    global browser_manager
    if browser_manager is None:
        browser_manager = await BrowserManager.get_instance()
    return browser_manager

def clean_html(html: str) -> str:

    from bs4 import BeautifulSoup, Comment

    soup = BeautifulSoup(html, 'html.parser')

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    for tag in EXCLUDED_TAGS:
        for element in soup.find_all(tag):
            element.decompose()

    ad_patterns = [
        'ad', 'ads', 'advert', 'advertisement', 'banner', 'popup', 'modal',
        'cookie', 'consent', 'newsletter', 'subscribe', 'sidebar', 'related',
        'recommended', 'sponsored', 'promo', 'social-share', 'share-buttons'
    ]

    for pattern in ad_patterns:

        for element in soup.find_all(class_=re.compile(pattern, re.I)):
            element.decompose()

        for element in soup.find_all(id=re.compile(pattern, re.I)):
            element.decompose()

    for element in soup.find_all(style=re.compile(r'display:\s*none', re.I)):
        element.decompose()

    return str(soup)

def html_to_markdown(html: str, base_url: str = "") -> str:

    from markdownify import markdownify, MarkdownConverter

    cleaned_html = clean_html(html)

    class CustomConverter(MarkdownConverter):
        def convert_a(self, el, text, convert_as_inline):

            href = el.get('href', '')
            if href and not href.startswith(('http://', 'https://', 'mailto:', '#')):
                href = urljoin(base_url, href)
            if not text.strip():
                return ''
            return f'[{text}]({href})' if href else text

        def convert_img(self, el, text, convert_as_inline):

            return ''

    markdown = markdownify(
        cleaned_html,
        heading_style="ATX",
        bullets="-",
        strip=['script', 'style', 'noscript', 'iframe']
    )

    markdown = re.sub(r'\n{3,}', '\n\n', markdown)
    markdown = re.sub(r' {2,}', ' ', markdown)
    markdown = markdown.strip()

    if len(markdown) > MAX_CONTENT_LENGTH:
        markdown = markdown[:MAX_CONTENT_LENGTH] + "\n\n[Content truncated due to length...]"

    return markdown

async def search_duckduckgo(query: str, num_results: int = 5) -> list[dict]:

    import aiohttp
    from bs4 import BeautifulSoup

    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    results = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, headers=headers, timeout=15) as response:
                if response.status != 200:
                    _log.error("DuckDuckGo search failed", status=response.status, query=query[:50])
                    return []

                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                for result in soup.select('.result')[:num_results]:
                    title_elem = result.select_one('.result__title a')
                    snippet_elem = result.select_one('.result__snippet')

                    if title_elem:

                        href = title_elem.get('href', '')

                        if 'uddg=' in href:
                            import urllib.parse
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                            actual_url = parsed.get('uddg', [href])[0]
                        else:
                            actual_url = href

                        results.append({
                            'title': title_elem.get_text(strip=True),
                            'url': actual_url,
                            'snippet': snippet_elem.get_text(strip=True) if snippet_elem else '',
                        })

    except asyncio.TimeoutError:
        _log.error("DuckDuckGo search timeout", query=query[:50])
    except Exception as e:
        _log.error("DuckDuckGo search error", query=query[:50], error=str(e))

    return results

async def _google_search(query: str, num_results: int = 5) -> str:

    _log.info("DuckDuckGo search", query=query[:80], max_results=num_results)

    results = await search_duckduckgo(query, num_results)

    if not results:
        return f"No results found for query: {query}"

    output = f"## Search Results for: {query}\n\n"
    for i, r in enumerate(results, 1):
        output += f"### {i}. {r['title']}\n"
        output += f"**URL:** {r['url']}\n"
        if r['snippet']:
            output += f"{r['snippet']}\n"
        output += "\n"

    return output

async def _tavily_search(query: str, max_results: int = 5, search_depth: str = "basic") -> str:

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
            content = r.get('content', '')[:300]
            if content:
                output += f"   {content}...\n"
            output += "\n"

        return output

    except Exception as e:
        _log.error("Tavily search failed", query=query[:50], error=str(e))
        return f" Tavily 검색 오류: {str(e)}"

async def _visit_page(url: str) -> str:

    import time
    start_time = time.time()
    _log.info("Page visit starting", url=url[:100])

    parsed = urlparse(url)
    if not parsed.scheme in ('http', 'https'):
        return f"Error: Invalid URL scheme. Only http/https supported: {url}"

    page = None
    try:
        manager = await get_browser_manager()
        page = await manager.get_page()

        page.set_default_timeout(PAGE_TIMEOUT_MS)
        page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)

        response = await page.goto(url, wait_until='networkidle')

        if response is None or response.status >= 400:
            status = response.status if response else 'unknown'
            return f"Error: Failed to load page. Status: {status}"

        await page.wait_for_load_state('networkidle')

        try:
            await page.wait_for_selector('article, main, .content, #content, .post, .entry',
                                         timeout=5000)
        except (asyncio.TimeoutError, Exception):
            pass

        html = await page.content()
        title = await page.title()

        markdown = html_to_markdown(html, url)

        output = f"# {title}\n\n"
        output += f"**Source:** {url}\n\n"
        output += "---\n\n"
        output += markdown

        dur_ms = int((time.time() - start_time) * 1000)
        _log.info("Page visit complete", url=url[:80], dur_ms=dur_ms, content_len=len(output))
        return process_content_for_artifact(url, output)

    except asyncio.TimeoutError:
        dur_ms = int((time.time() - start_time) * 1000)
        _log.error("Page visit timeout", url=url[:80], dur_ms=dur_ms)
        return f"Error: Page load timed out after {NAVIGATION_TIMEOUT_MS/1000}s: {url}"
    except Exception as e:
        dur_ms = int((time.time() - start_time) * 1000)
        _log.error("Page visit error", url=url[:80], dur_ms=dur_ms, error=str(e))
        return f"Error visiting page: {str(e)}"
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass

async def _deep_dive(query: str) -> str:

    import time
    start_time = time.time()
    _log.info("Deep dive starting", query=query[:80])

    output = f"# Deep Dive Research: {query}\n\n"
    output += "## Phase 1: Search Results\n\n"

    results = await search_duckduckgo(query, num_results=5)

    if not results:
        return f"Deep dive failed: No search results for '{query}'"

    for i, r in enumerate(results, 1):
        output += f"{i}. **{r['title']}**\n   {r['url']}\n\n"

    output += "---\n\n## Phase 2: Content Extraction\n\n"

    visited_content = []
    urls_to_visit = [r['url'] for r in results[:3]]

    tasks = [_visit_page(url) for url in urls_to_visit]
    page_contents = await asyncio.gather(*tasks, return_exceptions=True)

    artifact_paths = []

    for i, (url, content) in enumerate(zip(urls_to_visit, page_contents), 1):
        output += f"### Source {i}: {url}\n\n"

        if isinstance(content, Exception):
            output += f"*Failed to retrieve: {str(content)}*\n\n"
        else:

            is_artifact = content.strip().startswith("[ARTIFACT SAVED]")

            if is_artifact:

                visited_content.append({
                    'url': url,
                    'content': content,
                    'is_artifact': True
                })
                output += f"{content}\n\n"

                path_match = re.search(r'Path: ([^\n]+)', content)
                if path_match:
                    artifact_paths.append(path_match.group(1))
            else:

                content_lines = content.split('\n')
                content_body = '\n'.join(content_lines[4:])[:4000]

                if content_body.strip():
                    visited_content.append({
                        'url': url,
                        'content': content_body,
                        'is_artifact': False
                    })
                    output += f"{content_body}\n\n"
                else:
                    output += "*No meaningful content extracted*\n\n"

        output += "---\n\n"

    output += "## Phase 3: Research Summary\n\n"
    output += f"**Query:** {query}\n"
    output += f"**Sources Analyzed:** {len(visited_content)}/{len(urls_to_visit)}\n"

    total_chars = sum(
        len(c['content']) if not c.get('is_artifact') else ARTIFACT_THRESHOLD
        for c in visited_content
    )
    output += f"**Total Content Length:** {total_chars:,} characters\n\n"

    if visited_content:
        output += "**Key Sources:**\n"
        for vc in visited_content:
            artifact_marker = " (artifact)" if vc.get('is_artifact') else ""
            output += f"- {vc['url']}{artifact_marker}\n"

    if artifact_paths:
        output += "\n**Saved Artifacts:**\n"
        for path in artifact_paths:
            output += f"- `{path}`\n"
        output += "\n_Use `read_artifact` tool to retrieve full content from saved artifacts._\n"

    dur_ms = int((time.time() - start_time) * 1000)
    _log.info("Deep dive complete", query=query[:50], dur_ms=dur_ms, sources=len(visited_content), artifacts=len(artifact_paths))
    return output

@research_server.list_tools()
async def list_tools() -> list[Tool]:

    return [
        Tool(
            name="google_search",
            description="""Search the web using DuckDuckGo. Returns titles, URLs, and snippets.

Use this for:
- Quick fact-checking
- Finding authoritative sources
- Getting URLs to visit for deeper research

Note: For deep research, use 'deep_dive' instead which combines search + page visits.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (be specific for better results)"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5, max: 10)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="visit_page",
            description="""Visit a URL with a headless browser and extract content as Markdown.

CAPABILITIES:
- Renders JavaScript (handles dynamic/SPA sites)
- Waits for network idle (loads AJAX content)
- Strips ads, navigation, and other noise
- Converts to clean, readable Markdown

IDEAL FOR:
- Documentation pages
- News articles
- Blog posts
- Technical references
- Any JavaScript-heavy site

LIMITATIONS:
- May be blocked by aggressive anti-bot protections
- Large pages are truncated to ~50K chars""",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL to visit (must start with http:// or https://)"
                    }
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="deep_dive",
            description="""Comprehensive research tool: Search -> Visit top pages -> Compile findings.

This is your PRIMARY research tool. It:
1. Searches the web for your query
2. Visits the top 3 most relevant pages
3. Extracts and formats content from each
4. Provides a structured research report

USE THIS WHEN:
- User asks for research on a topic
- You need comprehensive information
- A single search isn't enough
- You need to verify facts across sources

OUTPUT INCLUDES:
- Search results overview
- Full content from top 3 sources
- Research summary with key sources""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Research query - be specific and detailed for best results"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="tavily_search",
            description=""" FAST search using Tavily API with AI-generated summary.

BEST FOR:
- Quick fact-checking (fastest option)
- Questions needing brief, accurate answers
- When you need AI-summarized results

FEATURES:
- AI-generated answer summary
- High-quality curated results
- Very fast response time

REQUIRES: TAVILY_API_KEY (will error if not set)

Use 'search_depth=advanced' for more thorough results (slower).""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results (default: 5)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10
                    },
                    "search_depth": {
                        "type": "string",
                        "enum": ["basic", "advanced"],
                        "description": "basic=fast, advanced=thorough",
                        "default": "basic"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="read_artifact",
            description="""Read the full content of a saved research artifact.

When deep_dive or visit_page saves large content (>2000 chars) as an artifact,
only a summary is returned. Use this tool to retrieve the complete content.

WHEN TO USE:
- When you see "[ARTIFACT SAVED]" in research results
- When you need detailed information from a saved source
- When the summary isn't enough to answer the user's question

The artifact path is provided in the research output.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the artifact file (from the research output)"
                    }
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="list_artifacts",
            description="""List recently saved research artifacts.

Shows saved artifacts with their URLs, timestamps, and file sizes.
Use this to find artifacts from previous research sessions.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of artifacts to list (default: 20)",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 100
                    }
                }
            }
        ),
    ]

@research_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:

    import time
    start_time = time.time()
    _log.info("REQ handling", tool=name, params=list(arguments.keys()))

    try:
        if name == "google_search":
            result = await _google_search(
                query=arguments["query"],
                num_results=arguments.get("num_results", 5)
            )
        elif name == "visit_page":
            result = await _visit_page(url=arguments["url"])
        elif name == "deep_dive":
            result = await _deep_dive(query=arguments["query"])
        elif name == "tavily_search":
            result = await _tavily_search(
                query=arguments["query"],
                max_results=arguments.get("max_results", 5),
                search_depth=arguments.get("search_depth", "basic")
            )
        elif name == "read_artifact":
            content = read_artifact(arguments["path"])
            if content:
                result = f"## Artifact Content\n\n{content}"
            else:
                result = f"Artifact not found: {arguments['path']}"
        elif name == "list_artifacts":
            artifacts = list_artifacts(arguments.get("limit", 20))
            if artifacts:
                result = "## Saved Research Artifacts\n\n"
                for a in artifacts:
                    result += f"- **{a['path']}**\n"
                    result += f"  - URL: {a['url']}\n"
                    result += f"  - Saved: {a['saved_at']}\n"
                    result += f"  - Size: {a['size']:,} bytes\n\n"
            else:
                result = "No research artifacts found."
        else:
            _log.warning("Unknown tool", tool=name)
            result = f"Unknown tool: {name}"

        dur_ms = int((time.time() - start_time) * 1000)
        _log.info("RES complete", tool=name, dur_ms=dur_ms)
        return [TextContent(type="text", text=result)]

    except Exception as e:
        dur_ms = int((time.time() - start_time) * 1000)
        _log.error("Tool failed", tool=name, dur_ms=dur_ms, error=str(e))
        return [TextContent(type="text", text=f"Tool execution failed: {str(e)}")]

async def run_stdio():

    from mcp.server.stdio import stdio_server

    _log.info("MCP server starting", mode="stdio", tools=6)
    async with stdio_server() as (read_stream, write_stream):
        await research_server.run(
            read_stream,
            write_stream,
            research_server.create_initialization_options()
        )

async def run_sse(host: str = "0.0.0.0", port: int = 8765):

    from fastapi import FastAPI, Request
    from sse_starlette.sse import EventSourceResponse
    from mcp.server.sse import SseServerTransport
    import uvicorn

    _log.info("MCP server starting", mode="sse", host=host, port=port, tools=6)
    app = FastAPI(title="Research MCP Server")
    sse = SseServerTransport("/messages/")

    @app.get("/sse")
    async def handle_sse(request: Request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await research_server.run(
                streams[0],
                streams[1],
                research_server.create_initialization_options()
            )

    @app.post("/messages/")
    async def handle_messages(request: Request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    @app.get("/health")
    async def health():
        return {"status": "healthy", "server": "research-mcp"}

    @app.on_event("shutdown")
    async def shutdown():
        global browser_manager
        if browser_manager:
            await browser_manager.close()

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def cleanup():

    global browser_manager
    if browser_manager:
        _log.info("MCP server shutdown", action="browser_close")
        await browser_manager.close()

def main():

    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "stdio"

    try:
        if mode == "stdio":
            asyncio.run(run_stdio())
        elif mode == "sse":
            port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
            asyncio.run(run_sse(port=port))
        else:
            print(f"Usage: {sys.argv[0]} [stdio|sse] [port]")
            sys.exit(1)
    except KeyboardInterrupt:
        _log.info("Server interrupted")
    finally:
        asyncio.run(cleanup())

if __name__ == "__main__":
    main()
