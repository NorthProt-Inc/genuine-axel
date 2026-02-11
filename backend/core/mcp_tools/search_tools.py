"""Code search tools for MCP.

This module provides tools for searching the codebase with keywords and regex patterns.
"""

from typing import Any, Sequence
from mcp.types import TextContent
from . import register_tool
from backend.core.logging.logging import get_logger

_log = get_logger("mcp.search_tools")


@register_tool(
    "search_codebase",
    category="system",
    description="Search for keywords/patterns across Axel's codebase. Useful for finding function definitions, error patterns, or understanding how specific features are implemented.",
    input_schema={
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "String to search for (e.g., 'def process_', 'class ChatHandler', 'ERROR')"},
            "file_pattern": {"type": "string", "description": "File pattern to search (default: '*.py'). Use '*' for all files.", "default": "*.py"},
            "case_sensitive": {"type": "boolean", "description": "Whether search is case-sensitive (default: false)", "default": False},
            "max_results": {"type": "integer", "description": "Maximum results to return (default: 50)", "default": 50, "maximum": 100}
        },
        "required": ["keyword"]
    }
)
async def search_codebase_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Search for keywords across the codebase.

    Args:
        arguments: Dict with keyword, file_pattern, case_sensitive, max_results

    Returns:
        TextContent with formatted search results
    """
    keyword = arguments.get("keyword", "")
    file_pattern = arguments.get("file_pattern", "*.py")
    case_sensitive = arguments.get("case_sensitive", False)
    max_results = arguments.get("max_results", 50)
    _log.debug("TOOL invoke", fn="search_codebase", keyword=keyword[:50] if keyword else None, pattern=file_pattern)

    if not keyword:
        _log.warning("TOOL fail", fn="search_codebase", err="keyword required")
        return [TextContent(type="text", text="✗ Error: keyword is required")]

    if not isinstance(max_results, int) or max_results < 1 or max_results > 100:
        _log.warning("TOOL fail", fn="search_codebase", err="invalid max_results")
        return [TextContent(type="text", text="Error: max_results must be between 1 and 100")]

    try:
        from backend.core.tools.system_observer import (
            search_codebase,
            format_search_results
        )

        result = await search_codebase(
            keyword=keyword,
            file_pattern=file_pattern,
            case_sensitive=case_sensitive,
            max_results=max_results
        )

        _log.info("TOOL ok", fn="search_codebase", res_len=result.get('total_matches', 0) if isinstance(result, dict) else 0)
        return [TextContent(type="text", text=format_search_results(result))]

    except Exception as e:
        _log.error("TOOL fail", fn="search_codebase", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Search Error: {str(e)}")]


@register_tool(
    "search_codebase_regex",
    category="system",
    description=r"Search codebase using regex patterns (advanced). Use for complex pattern matching like 'def \w+\(' to find all function definitions.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "file_pattern": {"type": "string", "description": "File pattern to search (default: '*.py')", "default": "*.py"},
            "case_sensitive": {"type": "boolean", "description": "Whether search is case-sensitive (default: false)", "default": False}
        },
        "required": ["pattern"]
    }
)
async def search_codebase_regex_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Search codebase using regex patterns.

    Args:
        arguments: Dict with pattern, file_pattern, case_sensitive

    Returns:
        TextContent with formatted regex search results
    """
    pattern = arguments.get("pattern", "")
    file_pattern = arguments.get("file_pattern", "*.py")
    case_sensitive = arguments.get("case_sensitive", False)
    _log.debug("TOOL invoke", fn="search_codebase_regex", pattern=pattern[:50] if pattern else None, file_pattern=file_pattern)

    if not pattern:
        _log.warning("TOOL fail", fn="search_codebase_regex", err="pattern required")
        return [TextContent(type="text", text="✗ Error: pattern is required")]

    try:
        from backend.core.tools.system_observer import (
            search_codebase_regex,
            format_search_results
        )

        result = await search_codebase_regex(
            pattern=pattern,
            file_pattern=file_pattern,
            case_sensitive=case_sensitive
        )

        _log.info("TOOL ok", fn="search_codebase_regex", res_len=result.get('total_matches', 0) if isinstance(result, dict) else 0)
        return [TextContent(type="text", text=format_search_results(result))]

    except Exception as e:
        _log.error("TOOL fail", fn="search_codebase_regex", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Regex Search Error: {str(e)}")]


__all__ = ["search_codebase_tool", "search_codebase_regex_tool"]
