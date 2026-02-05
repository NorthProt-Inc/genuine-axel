"""
Axel MCP Server - Model Context Protocol server for Axel AI assistant.

This module provides:
- MCP Server instance with tool and resource handlers
- FastAPI application for SSE transport
- Entry points for SSE and stdio modes
"""

import sys
import os
try:
    if sys.path[0] == os.path.dirname(os.path.abspath(__file__)):
        sys.path.pop(0)
except Exception:
    pass

import asyncio
from pathlib import Path
from typing import Any, Sequence

from backend.core.logging import get_logger
from mcp.server import Server
from mcp.types import Resource, Tool, TextContent, TextResourceContents
import mcp.types as types
from fastapi import FastAPI
import uvicorn

_log = get_logger("core.mcp_server")

# Path setup
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.config import (
    PROJECT_ROOT as AXEL_ROOT,
    WORKING_MEMORY_PATH,
)

from dotenv import load_dotenv
load_dotenv(AXEL_ROOT / ".env")

# Import tool registry
from backend.core.mcp_tools import (
    get_tool_handler,
    is_tool_registered,
    list_tools as list_registered_tools,
    get_tool_schemas,
)

# Import transport layer
from backend.core.mcp_transport import (
    SSE_CONNECTION_TIMEOUT,
    create_sse_app,
    run_stdio_server,
    get_connection_count,
)

# =============================================================================
# MCP Server Instance
# =============================================================================

mcp_server = Server("axel-mcp-server")


# =============================================================================
# Resource Handlers
# =============================================================================

async def read_file_safe(path: Path) -> str:
    """Safely read a file with async I/O."""
    if not path.exists():
        return f"Error: File not found at {path}"
    try:
        return await asyncio.to_thread(path.read_text, encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {str(e)}"


@mcp_server.list_resources()
async def list_resources() -> list[Resource]:
    """List available MCP resources."""
    return [
        Resource(
            uri=types.AnyUrl("axel://memory/working"),
            name="Axel Working Memory",
            description="Axel's short-term working memory log",
            mimeType="application/json",
        ),
    ]


@mcp_server.read_resource()
async def read_resource(uri: types.AnyUrl) -> str | bytes | TextResourceContents:
    """Read a specific MCP resource."""
    uri_str = str(uri)
    if uri_str == "axel://memory/working":
        return await read_file_safe(WORKING_MEMORY_PATH)
    raise ValueError(f"Resource not found: {uri}")


@mcp_server.list_resource_templates()
async def list_resource_templates() -> list[types.ResourceTemplate]:
    """List available resource templates."""
    return []


# =============================================================================
# Tool Handlers
# =============================================================================

@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """Return all registered tool schemas from the tool registry."""
    return get_tool_schemas()


@mcp_server.call_tool()
async def call_tool(
    name: str,
    arguments: Any
) -> Sequence[TextContent | types.ImageContent | types.EmbeddedResource]:
    """
    Execute a tool by name with robust error handling.

    This is the central dispatch point for all MCP tool calls.
    """
    _log.info("TOOL call recv", tool=name, args_keys=list(arguments.keys()) if arguments else [])

    try:
        if arguments is None:
            arguments = {}

        if is_tool_registered(name):
            handler = get_tool_handler(name)

            try:
                result = await asyncio.wait_for(
                    handler(arguments),
                    timeout=300.0  # 5 minute max for any tool
                )
                _log.info("TOOL exec done", tool=name, result_cnt=len(result) if result else 0)
                return result

            except asyncio.TimeoutError:
                _log.error("TOOL timeout", tool=name)
                return [TextContent(type="text", text=f"Error: Tool '{name}' timed out after 300 seconds")]

        _log.error("Tool not found in registry", tool=name, available=list_registered_tools()[:10])
        return [TextContent(type="text", text=f"Error: Unknown tool '{name}'.")]

    except ValueError as e:
        _log.error("Tool dispatch error", tool=name, err=str(e)[:100])
        return [TextContent(type="text", text=f"Error: {str(e)}")]

    except Exception as e:
        _log.error("Tool exec failed", tool=name, err=str(e)[:100], exc_info=True)
        return [TextContent(type="text", text=f"Error executing {name}: {str(e)}")]


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(title="Axel MCP Server", version="1.1.0")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "active_connections": get_connection_count(),
        "server": "axel-mcp-server"
    }


# Mount SSE sub-app
app.mount("/sse", create_sse_app(mcp_server))


# =============================================================================
# Entry Points
# =============================================================================

def run_sse_server(host: str = "0.0.0.0", port: int = 8555):
    """Start the MCP server in SSE mode."""
    _log.info("Starting MCP server in SSE mode", host=host, port=port)
    uvicorn.run(
        app,
        host=host,
        port=port,
        timeout_keep_alive=SSE_CONNECTION_TIMEOUT,
        log_level="info"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Axel MCP Server")
    parser.add_argument("--stdio", action="store_true", help="Use stdio transport (fallback)")
    parser.add_argument("--host", default="0.0.0.0", help="SSE server host")
    parser.add_argument("--port", type=int, default=8555, help="SSE server port")

    args = parser.parse_args()

    if args.stdio:
        asyncio.run(run_stdio_server(mcp_server))
    else:
        run_sse_server(args.host, args.port)
