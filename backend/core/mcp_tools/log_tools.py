"""Log reading and analysis tools for MCP.

This module provides tools for reading system logs, listing available logs,
and analyzing errors/warnings in log files.
"""

from typing import Any, Sequence
from mcp.types import TextContent
from . import register_tool
from backend.core.logging.logging import get_logger

_log = get_logger("mcp.log_tools")


@register_tool(
    "read_system_logs",
    category="system",
    description="Read Axel's backend logs for self-debugging. Allows reading last N lines with optional keyword filtering. Security: Only reads from designated log directory.",
    input_schema={
        "type": "object",
        "properties": {
            "log_file": {
                "type": "string",
                "description": "Log file to read: 'backend' (default), 'backend_error', 'mcp', 'mcp_error', 'main', or full filename",
                "default": "backend.log"
            },
            "lines": {
                "type": "integer",
                "description": "Number of lines to read from the end (default: 50, max: 1000)",
                "default": 50,
                "minimum": 1,
                "maximum": 1000
            },
            "filter_keyword": {
                "type": "string",
                "description": "Optional keyword to filter logs (e.g., 'ERROR', 'WARNING', 'request_id')"
            }
        },
        "required": []
    }
)
async def read_system_logs(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Read backend logs with optional filtering.

    Args:
        arguments: Dict with log_file, lines, filter_keyword

    Returns:
        TextContent with log content
    """
    log_file = arguments.get("log_file", "backend.log")
    lines = arguments.get("lines", 50)
    filter_keyword = arguments.get("filter_keyword")
    _log.debug("TOOL invoke", fn="read_system_logs", log_file=log_file, lines=lines, filter_keyword=filter_keyword)

    if not isinstance(lines, int) or lines < 1 or lines > 1000:
        _log.warning("TOOL fail", fn="read_system_logs", err="invalid lines")
        return [TextContent(type="text", text="Error: lines must be between 1 and 1000")]

    try:
        from backend.core.tools.system_observer import read_logs

        result = await read_logs(
            log_file=log_file,
            lines=lines,
            filter_keyword=filter_keyword
        )

        if result.success:
            _log.info("TOOL ok", fn="read_system_logs", log_file=log_file, lines_read=result.lines_read)
            header = f"✓ Log: {result.file_path} ({result.lines_read} lines)"
            if result.filter_applied:
                header += f" [filter: {result.filter_applied}]"
            return [TextContent(type="text", text=f"{header}\n{'─' * 50}\n{result.content}")]
        else:
            _log.warning("TOOL partial", fn="read_system_logs", err=result.error[:100] if result.error else None)
            return [TextContent(type="text", text=f"✗ Log Error: {result.error}")]

    except Exception as e:
        _log.error("TOOL fail", fn="read_system_logs", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Log Read Error: {str(e)}")]


@register_tool(
    "list_available_logs",
    category="system",
    description="List all log files available for Axel to read. Use this to discover what logs exist.",
    input_schema={
        "type": "object",
        "properties": {},
        "required": []
    }
)
async def list_available_logs_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """List all available log files.

    Returns:
        TextContent with log files and aliases
    """
    _log.debug("TOOL invoke", fn="list_available_logs")

    try:
        from backend.core.tools.system_observer import list_available_logs

        result = await list_available_logs()

        if result.get("success"):
            logs = result.get("logs", [])
            aliases = result.get("aliases", {})

            _log.info("TOOL ok", fn="list_available_logs", res_len=len(logs))
            output = ["✓ Available Log Files:", ""]
            for log in logs:
                output.append(f"  • {log['name']} ({log['size_kb']} KB)")

            output.append("")
            output.append("Aliases:")
            for alias, filename in aliases.items():
                output.append(f"  • {alias} -> {filename}")

            return [TextContent(type="text", text="\n".join(output))]
        else:
            _log.warning("TOOL partial", fn="list_available_logs", err="failed to list logs")
            return [TextContent(type="text", text="✗ Failed to list logs")]

    except Exception as e:
        _log.error("TOOL fail", fn="list_available_logs", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Error: {str(e)}")]


@register_tool(
    "analyze_log_errors",
    category="system",
    description="Analyze recent logs for errors and warnings. Returns categorized error summary.",
    input_schema={
        "type": "object",
        "properties": {
            "log_file": {
                "type": "string",
                "description": "Log file to analyze (default: backend.log)",
                "default": "backend.log"
            },
            "lines": {
                "type": "integer",
                "description": "Number of recent lines to analyze (default: 500)",
                "default": 500
            }
        },
        "required": []
    }
)
async def analyze_log_errors(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Analyze logs for errors and warnings.

    Args:
        arguments: Dict with log_file and lines

    Returns:
        TextContent with categorized error summary
    """
    log_file = arguments.get("log_file", "backend.log")
    lines = arguments.get("lines", 500)
    _log.debug("TOOL invoke", fn="analyze_log_errors", log_file=log_file, lines=lines)

    if not isinstance(lines, int) or lines < 1 or lines > 5000:
        _log.warning("TOOL fail", fn="analyze_log_errors", err="invalid lines")
        return [TextContent(type="text", text="Error: lines must be between 1 and 5000")]

    try:
        from backend.core.tools.system_observer import analyze_recent_errors

        result = await analyze_recent_errors(
            log_file=log_file,
            lines=lines
        )

        if result.get("success"):
            errors = result.get("errors", [])
            warnings = result.get("warnings", [])
            summary = result.get("summary", "")

            _log.info("TOOL ok", fn="analyze_log_errors", err_cnt=len(errors), warn_cnt=len(warnings))
            output = [f"✓ Error Analysis ({log_file})", ""]

            if errors:
                output.append(f"Errors ({len(errors)}):")
                for err in errors[:10]:
                    output.append(f"  - {err}")

            if warnings:
                output.append(f"\nWarnings ({len(warnings)}):")
                for warn in warnings[:10]:
                    output.append(f"  - {warn}")

            if summary:
                output.append(f"\nSummary:\n{summary}")

            if not errors and not warnings:
                output.append("No errors or warnings found.")

            return [TextContent(type="text", text="\n".join(output))]
        else:
            _log.warning("TOOL partial", fn="analyze_log_errors", err=result.get('error', 'unknown')[:100])
            return [TextContent(type="text", text=f"✗ Analysis failed: {result.get('error')}")]

    except Exception as e:
        _log.error("TOOL fail", fn="analyze_log_errors", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Analysis Error: {str(e)}")]


__all__ = [
    "read_system_logs",
    "list_available_logs_tool",
    "analyze_log_errors",
]
