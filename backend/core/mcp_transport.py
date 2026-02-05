"""
MCP Transport Layer - SSE and stdio transport handlers.

Provides:
- SSE transport configuration and handlers
- Connection state management
- stdio server mode
"""

import asyncio
from typing import TYPE_CHECKING

from backend.core.logging import get_logger
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from fastapi import Request
from starlette.applications import Starlette
from starlette.responses import Response as StarletteResponse
from starlette.routing import Route as StarletteRoute

if TYPE_CHECKING:
    from mcp.server import Server

_log = get_logger("core.mcp_transport")

# SSE Configuration
SSE_KEEPALIVE_INTERVAL = 15
SSE_CONNECTION_TIMEOUT = 600
SSE_RETRY_DELAY = 3000

# Connection state
active_connections: set = set()

# SSE transport instance
sse_transport = SseServerTransport("/messages")


def get_connection_count() -> int:
    """Return the number of active SSE connections."""
    return len(active_connections)


def create_sse_handlers(mcp_server: "Server"):
    """
    Create SSE request handlers bound to the given MCP server.

    Args:
        mcp_server: The MCP Server instance to run

    Returns:
        Tuple of (handle_sse, handle_messages) async functions
    """

    async def handle_sse_raw(request: Request):
        """Raw SSE handler that directly controls ASGI response."""
        connection_id = id(request.scope)
        active_connections.add(connection_id)
        _log.info("SSE conn opened", conn_id=connection_id)

        try:
            async with sse_transport.connect_sse(
                request.scope,
                request.receive,
                request._send
            ) as streams:
                await mcp_server.run(
                    streams[0],
                    streams[1],
                    mcp_server.create_initialization_options()
                )
        except asyncio.CancelledError:
            _log.info("SSE conn cancelled by client", conn_id=connection_id)
        except Exception as e:
            _log.error("SSE handler error", conn_id=connection_id, err=str(e)[:100], exc_info=True)
        finally:
            active_connections.discard(connection_id)
            _log.info("SSE conn closed", conn_id=connection_id, active=len(active_connections))

        return StarletteResponse()

    async def handle_messages_raw(request: Request):
        """Raw messages handler for MCP POST requests."""
        await sse_transport.handle_post_message(
            request.scope,
            request.receive,
            request._send
        )
        return StarletteResponse(status_code=202)

    return handle_sse_raw, handle_messages_raw


def create_sse_app(mcp_server: "Server") -> Starlette:
    """
    Create a Starlette sub-app for MCP SSE endpoints.

    Args:
        mcp_server: The MCP Server instance

    Returns:
        Starlette application with SSE routes
    """
    handle_sse, handle_messages = create_sse_handlers(mcp_server)

    return Starlette(routes=[
        StarletteRoute("/", endpoint=handle_sse, methods=["GET"]),
        StarletteRoute("/messages", endpoint=handle_messages, methods=["POST"]),
    ])


async def run_stdio_server(mcp_server: "Server"):
    """
    Run MCP server in stdio mode.

    Args:
        mcp_server: The MCP Server instance
    """
    _log.info("Starting MCP server in stdio mode...")

    async with stdio_server() as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options()
        )
