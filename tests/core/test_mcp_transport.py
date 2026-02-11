"""Tests for backend.core.mcp_transport module.

Covers: get_connection_count, create_sse_handlers, create_sse_app,
run_stdio_server, active_connections management. All I/O is mocked.
"""

import asyncio
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock

import pytest

from backend.core.mcp_transport import (
    get_connection_count,
    active_connections,
    create_sse_handlers,
    create_sse_app,
    run_stdio_server,
    sse_transport,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_connections():
    """Ensure active_connections is clean between tests."""
    active_connections.clear()
    yield
    active_connections.clear()


def _make_mock_server():
    """Create a mock MCP Server."""
    server = MagicMock()
    server.run = AsyncMock()
    server.create_initialization_options = MagicMock(return_value={})
    return server


def _make_mock_request(scope_id=12345):
    """Create a mock Starlette Request."""
    request = MagicMock()
    request.scope = {"type": "http", "id": scope_id}
    request.receive = AsyncMock()
    request._send = AsyncMock()
    return request


# ---------------------------------------------------------------------------
# get_connection_count
# ---------------------------------------------------------------------------
class TestGetConnectionCount:
    def test_empty(self):
        assert get_connection_count() == 0

    def test_with_connections(self):
        active_connections.add(1)
        active_connections.add(2)
        active_connections.add(3)
        assert get_connection_count() == 3

    def test_after_add_and_remove(self):
        active_connections.add(1)
        active_connections.add(2)
        active_connections.discard(1)
        assert get_connection_count() == 1


# ---------------------------------------------------------------------------
# create_sse_handlers
# ---------------------------------------------------------------------------
class TestCreateSseHandlers:
    def test_returns_two_handlers(self):
        server = _make_mock_server()
        handle_sse, handle_messages = create_sse_handlers(server)
        assert callable(handle_sse)
        assert callable(handle_messages)

    async def test_handle_sse_adds_and_removes_connection(self):
        server = _make_mock_server()
        handle_sse, _ = create_sse_handlers(server)
        request = _make_mock_request()

        # Mock SSE transport connect_sse
        mock_streams = (AsyncMock(), AsyncMock())
        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_streams)
        mock_connect.__aexit__ = AsyncMock(return_value=False)

        with patch.object(sse_transport, "connect_sse", return_value=mock_connect):
            await handle_sse(request)

        # After completion, connection should be removed
        assert len(active_connections) == 0

    async def test_handle_sse_cleans_up_on_cancellation(self):
        server = _make_mock_server()
        server.run = AsyncMock(side_effect=asyncio.CancelledError())
        handle_sse, _ = create_sse_handlers(server)
        request = _make_mock_request()

        mock_streams = (AsyncMock(), AsyncMock())
        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_streams)
        mock_connect.__aexit__ = AsyncMock(return_value=False)

        with patch.object(sse_transport, "connect_sse", return_value=mock_connect):
            await handle_sse(request)

        assert len(active_connections) == 0

    async def test_handle_sse_cleans_up_on_error(self):
        server = _make_mock_server()
        server.run = AsyncMock(side_effect=RuntimeError("SSE error"))
        handle_sse, _ = create_sse_handlers(server)
        request = _make_mock_request()

        mock_streams = (AsyncMock(), AsyncMock())
        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_streams)
        mock_connect.__aexit__ = AsyncMock(return_value=False)

        with patch.object(sse_transport, "connect_sse", return_value=mock_connect):
            await handle_sse(request)

        assert len(active_connections) == 0

    async def test_handle_messages_delegates_to_transport(self):
        server = _make_mock_server()
        _, handle_messages = create_sse_handlers(server)
        request = _make_mock_request()

        with patch.object(sse_transport, "handle_post_message", new_callable=AsyncMock) as mock_post:
            response = await handle_messages(request)
            mock_post.assert_called_once_with(
                request.scope,
                request.receive,
                request._send,
            )


# ---------------------------------------------------------------------------
# create_sse_app
# ---------------------------------------------------------------------------
class TestCreateSseApp:
    def test_returns_starlette_app(self):
        server = _make_mock_server()
        app = create_sse_app(server)
        from starlette.applications import Starlette
        assert isinstance(app, Starlette)

    def test_has_two_routes(self):
        server = _make_mock_server()
        app = create_sse_app(server)
        assert len(app.routes) == 2

    def test_routes_have_correct_paths(self):
        server = _make_mock_server()
        app = create_sse_app(server)
        paths = [r.path for r in app.routes]
        assert "/" in paths
        assert "/messages" in paths


# ---------------------------------------------------------------------------
# run_stdio_server
# ---------------------------------------------------------------------------
class TestRunStdioServer:
    async def test_runs_server_with_stdio_streams(self):
        server = _make_mock_server()

        mock_read_stream = AsyncMock()
        mock_write_stream = AsyncMock()

        mock_stdio_ctx = AsyncMock()
        mock_stdio_ctx.__aenter__ = AsyncMock(return_value=(mock_read_stream, mock_write_stream))
        mock_stdio_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.core.mcp_transport.stdio_server", return_value=mock_stdio_ctx):
            await run_stdio_server(server)

        server.run.assert_called_once_with(
            mock_read_stream,
            mock_write_stream,
            server.create_initialization_options(),
        )

    async def test_creates_initialization_options(self):
        server = _make_mock_server()

        mock_stdio_ctx = AsyncMock()
        mock_stdio_ctx.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
        mock_stdio_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.core.mcp_transport.stdio_server", return_value=mock_stdio_ctx):
            await run_stdio_server(server)

        server.create_initialization_options.assert_called()


# ---------------------------------------------------------------------------
# sse_transport module-level instance
# ---------------------------------------------------------------------------
class TestSseTransportInstance:
    def test_sse_transport_exists(self):
        assert sse_transport is not None

    def test_sse_transport_has_connect_sse(self):
        assert hasattr(sse_transport, "connect_sse")

    def test_sse_transport_has_handle_post_message(self):
        assert hasattr(sse_transport, "handle_post_message")


# ---------------------------------------------------------------------------
# active_connections module-level set
# ---------------------------------------------------------------------------
class TestActiveConnectionsSet:
    def test_is_a_set(self):
        assert isinstance(active_connections, set)

    def test_add_and_discard(self):
        active_connections.add(999)
        assert 999 in active_connections
        active_connections.discard(999)
        assert 999 not in active_connections

    def test_discard_nonexistent_no_error(self):
        active_connections.discard(99999)  # No KeyError
