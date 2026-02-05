from typing import Any, Sequence
from mcp.types import TextContent
from . import register_tool
from backend.core.logging.logging import get_logger

_log = get_logger("mcp.research_tools")

@register_tool(
    "web_search",
    category="research",
    description="""Search the web using DuckDuckGo. Returns titles, URLs, and snippets.

Use this for:
- Quick fact-checking
- Finding authoritative sources
- Getting URLs to visit for deeper research

For comprehensive research, use 'deep_research' instead.""",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (be specific for better results)"},
            "num_results": {"type": "integer", "description": "Number of results (default: 5, max: 10)", "default": 5, "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }
)
async def web_search(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Search the web using DuckDuckGo.

    Args:
        arguments: Dict with query and num_results

    Returns:
        TextContent with titles, URLs, and snippets
    """
    query = arguments.get("query", "")
    num_results = arguments.get("num_results", 5)
    _log.debug("TOOL invoke", fn="web_search", query=query[:50] if query else None, num_results=num_results)

    if not query:
        _log.warning("TOOL fail", fn="web_search", err="query parameter required")
        return [TextContent(type="text", text="Error: query parameter is required")]

    if not isinstance(num_results, int) or num_results < 1 or num_results > 10:
        _log.warning("TOOL fail", fn="web_search", err="invalid num_results")
        return [TextContent(type="text", text="Error: num_results must be between 1 and 10")]

    try:
        from backend.protocols.mcp.research_server import _google_search

        result = await _google_search(query, num_results)
        _log.info("TOOL ok", fn="web_search", res_len=len(result))
        return [TextContent(type="text", text=result)]

    except Exception as e:
        _log.error("TOOL fail", fn="web_search", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Search Error: {str(e)}")]

@register_tool(
    "visit_webpage",
    category="research",
    description="""Visit a URL with headless browser and extract content as Markdown.

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
- Any JavaScript-heavy site""",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to visit (must start with http:// or https://)"}
        },
        "required": ["url"]
    }
)
async def visit_webpage(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Visit URL with headless browser and extract markdown content.

    Args:
        arguments: Dict with url

    Returns:
        TextContent with page content as markdown
    """
    url = arguments.get("url", "")
    _log.debug("TOOL invoke", fn="visit_webpage", url=url[:80] if url else None)

    if not url:
        _log.warning("TOOL fail", fn="visit_webpage", err="url parameter required")
        return [TextContent(type="text", text="Error: url parameter is required")]

    if not url.startswith(("http://", "https://")):
        _log.warning("TOOL fail", fn="visit_webpage", err="invalid url scheme")
        return [TextContent(type="text", text="Error: url must start with http:// or https://")]

    try:
        from backend.protocols.mcp.research_server import _visit_page

        result = await _visit_page(url)
        _log.info("TOOL ok", fn="visit_webpage", res_len=len(result))
        return [TextContent(type="text", text=result)]

    except Exception as e:
        _log.error("TOOL fail", fn="visit_webpage", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Visit Error: {str(e)}")]

@register_tool(
    "deep_research",
    category="research",
    description="""무료 웹 리서치 (DuckDuckGo + Playwright 브라우저).

[필수 사용 조건] 사용자가 다음 키워드 언급 시 반드시 이 도구 호출:
- "검색해줘", "찾아줘", "리서치해줘" (o4/OpenAI 언급 없이)
- "웹에서 찾아", "인터넷 검색"
- "deep_research" (도구 이름 직접 언급)

[동작]
1. DuckDuckGo 검색 실행
2. 상위 3개 페이지 방문 (Playwright 브라우저)
3. 내용 추출 및 리포트 생성

[용도]
- 일반적인 정보 검색
- 뉴스/블로그 조사
- 무료 리서치 (유료 API 아님)

프리미엄 리서치는 google_deep_research 사용.""",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Research query - be specific and detailed for best results"}
        },
        "required": ["query"]
    }
)
async def deep_research(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Execute free web research using DuckDuckGo and Playwright.

    Args:
        arguments: Dict with query

    Returns:
        TextContent with research report from top pages
    """
    query = arguments.get("query", "")
    _log.debug("TOOL invoke", fn="deep_research", query=query[:50] if query else None)

    if not query:
        _log.warning("TOOL fail", fn="deep_research", err="query parameter required")
        return [TextContent(type="text", text="Error: query parameter is required")]

    try:
        from backend.protocols.mcp.research_server import _deep_dive

        result = await _deep_dive(query)
        _log.info("TOOL ok", fn="deep_research", res_len=len(result))
        return [TextContent(type="text", text=result)]

    except Exception as e:
        _log.error("TOOL fail", fn="deep_research", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Research Error: {str(e)}")]

@register_tool(
    "tavily_search",
    category="research",
    description="""Tavily 빠른 검색 (AI 요약 포함).

[필수 사용 조건] 사용자가 다음 키워드 언급 시 반드시 이 도구 호출:
- "Tavily로 검색", "빠른 검색"
- "tavily_search" (도구 이름 직접 언급)

[특징]
- AI가 검색 결과 요약해서 제공
- deep_research보다 빠름
- 간단한 팩트 체크에 적합

[파라미터]
- query: 검색어
- search_depth: basic(빠름) / advanced(상세)

TAVILY_API_KEY 필요.""",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Number of results (default: 5)", "default": 5, "minimum": 1, "maximum": 10},
            "search_depth": {"type": "string", "enum": ["basic", "advanced"], "description": "basic=fast, advanced=thorough", "default": "basic"}
        },
        "required": ["query"]
    }
)
async def tavily_search(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Execute Tavily AI-powered search with summary.

    Args:
        arguments: Dict with query, max_results, search_depth

    Returns:
        TextContent with AI-summarized search results
    """
    query = arguments.get("query", "")
    max_results = arguments.get("max_results", 5)
    search_depth = arguments.get("search_depth", "basic")
    _log.debug("TOOL invoke", fn="tavily_search", query=query[:50] if query else None, depth=search_depth)

    if not query:
        _log.warning("TOOL fail", fn="tavily_search", err="query parameter required")
        return [TextContent(type="text", text="Error: query parameter is required")]

    if not isinstance(max_results, int) or max_results < 1 or max_results > 10:
        _log.warning("TOOL fail", fn="tavily_search", err="invalid max_results")
        return [TextContent(type="text", text="Error: max_results must be between 1 and 10")]

    if search_depth not in ["basic", "advanced"]:
        _log.warning("TOOL fail", fn="tavily_search", err="invalid search_depth")
        return [TextContent(type="text", text="Error: search_depth must be 'basic' or 'advanced'")]

    try:
        from backend.protocols.mcp.research_server import _tavily_search

        result = await _tavily_search(
            query=query,
            max_results=max_results,
            search_depth=search_depth
        )
        _log.info("TOOL ok", fn="tavily_search", res_len=len(result))
        return [TextContent(type="text", text=result)]

    except Exception as e:
        _log.error("TOOL fail", fn="tavily_search", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Tavily Error: {str(e)}")]

@register_tool(
    "read_artifact",
    category="research",
    description="""Read the full content of a saved research artifact.

When deep_research or visit_webpage saves large content (>2000 chars) as an artifact,
only a summary is returned. Use this tool to retrieve the complete content.

WHEN TO USE:
- When you see "[ARTIFACT SAVED]" in research results
- When you need detailed information from a saved source
- When the summary isn't enough to answer the user's question

The artifact path is provided in the research output (look for "Path: ...").""",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the artifact file (from the research output)"
            }
        },
        "required": ["path"]
    }
)
async def read_artifact_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Read full content of a saved research artifact.

    Args:
        arguments: Dict with path to artifact file

    Returns:
        TextContent with artifact content
    """
    path = arguments.get("path", "")
    _log.debug("TOOL invoke", fn="read_artifact", path=path[:80] if path else None)

    if not path:
        _log.warning("TOOL fail", fn="read_artifact", err="path parameter required")
        return [TextContent(type="text", text="Error: path parameter is required")]

    try:
        from backend.core.research_artifacts import read_artifact

        content = read_artifact(path)

        if content:
            _log.info("TOOL ok", fn="read_artifact", res_len=len(content))
            return [TextContent(type="text", text=f"## Artifact Content\n\n{content}")]
        else:
            _log.warning("TOOL fail", fn="read_artifact", err="artifact not found")
            return [TextContent(type="text", text=f"✗ Artifact not found: {path}")]

    except Exception as e:
        _log.error("TOOL fail", fn="read_artifact", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Artifact Error: {str(e)}")]

@register_tool(
    "list_artifacts",
    category="research",
    description="""List recently saved research artifacts.

Shows saved artifacts with their URLs, timestamps, and file sizes.
Use this to find artifacts from previous research sessions.

Each artifact entry includes:
- File path (use with read_artifact)
- Source URL
- Save timestamp
- File size in bytes""",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of artifacts to list (default: 20)",
                "default": 20,
                "minimum": 1,
                "maximum": 100
            }
        },
        "required": []
    }
)
async def list_artifacts_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """List recently saved research artifacts.

    Args:
        arguments: Dict with optional limit

    Returns:
        TextContent with artifact list including paths and metadata
    """
    limit = arguments.get("limit", 20)
    _log.debug("TOOL invoke", fn="list_artifacts", limit=limit)

    if not isinstance(limit, int) or limit < 1 or limit > 100:
        _log.warning("TOOL fail", fn="list_artifacts", err="invalid limit")
        return [TextContent(type="text", text="Error: limit must be between 1 and 100")]

    try:
        from backend.core.research_artifacts import list_artifacts

        artifacts = list_artifacts(limit)

        if artifacts:
            _log.info("TOOL ok", fn="list_artifacts", res_len=len(artifacts))
            output = ["✓ Saved Research Artifacts", ""]
            for a in artifacts:
                output.append(f"**{a['path']}**")
                output.append(f"  - URL: {a['url']}")
                output.append(f"  - Saved: {a['saved_at']}")
                output.append(f"  - Size: {a['size']:,} bytes")
                output.append("")
            return [TextContent(type="text", text="\n".join(output))]
        else:
            _log.info("TOOL ok", fn="list_artifacts", res_len=0)
            return [TextContent(type="text", text="✓ No research artifacts found.")]

    except Exception as e:
        _log.error("TOOL fail", fn="list_artifacts", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Artifacts Error: {str(e)}")]
