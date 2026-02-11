"""MCP Research Server — schema and transport layer.

All business logic has been extracted to backend.protocols.mcp.research.*:
  - browser.py:        BrowserManager (headless Playwright)
  - html_processor.py: clean_html, html_to_markdown
  - search_engines.py: search_duckduckgo, web_search, tavily_search
  - page_visitor.py:   visit_page, deep_dive
  - config.py:         constants (timeouts, user agents, etc.)
"""

import asyncio
import sys
import time
from pathlib import Path

AXEL_ROOT = Path(__file__).resolve().parents[3]
# PERF-041: Check before inserting to avoid duplicates
if str(AXEL_ROOT) not in sys.path:
    sys.path.insert(0, str(AXEL_ROOT))

from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.types as types

from backend.core.logging import get_logger
from backend.core.research_artifacts import read_artifact, list_artifacts

from backend.protocols.mcp.research.browser import BrowserManager, get_browser_manager
from backend.protocols.mcp.research.search_engines import (
    web_search,
    tavily_search,
)
from backend.protocols.mcp.research.page_visitor import visit_page, deep_dive

# Backward-compatible aliases for callers using old names
_google_search = web_search
_tavily_search = tavily_search
_visit_page = visit_page
_deep_dive = deep_dive

_log = get_logger("protocols.research")

research_server = Server("research-mcp")

# PERF-041: Define tool schemas at module level to avoid rebuilding on every list_tools call
_RESEARCH_TOOLS = [
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


@research_server.list_tools()
async def list_tools() -> list[Tool]:
    """Return pre-defined tool schemas."""
    return _RESEARCH_TOOLS


@research_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    start_time = time.time()
    _log.info("REQ handling", tool=name, params=list(arguments.keys()))

    try:
        if name == "google_search":
            result = await web_search(
                query=arguments["query"],
                num_results=arguments.get("num_results", 5)
            )
        elif name == "visit_page":
            result = await visit_page(url=arguments["url"])
        elif name == "deep_dive":
            result = await deep_dive(query=arguments["query"])
        elif name == "tavily_search":
            result = await tavily_search(
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
    from mcp.server.sse import SseServerTransport
    import uvicorn

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield
        manager = await get_browser_manager()
        await manager.close()

    _log.info("MCP server starting", mode="sse", host=host, port=port, tools=6)
    app = FastAPI(title="Research MCP Server", lifespan=_lifespan)
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

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def cleanup():
    try:
        manager = await BrowserManager.get_instance()
        if manager._playwright is not None:
            _log.info("MCP server shutdown", action="browser_close")
            await manager.close()
    except Exception:
        pass


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
