"""Tests for MCPClient.call_tool() retry behaviour.

The MCPClient.call_tool() method uses retry_async to wrap an internal
_direct_call() closure that does a deferred ``from backend.core.mcp_server
import call_tool``.  Tests inject a mock module into *sys.modules* so the
deferred import resolves to our mock without requiring the real MCP server
module (which has heavy dependencies).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.mcp_client import MCPClient


def _text_result(text: str) -> list:
    """Build a fake MCP tool result list."""
    return [SimpleNamespace(text=text)]


@pytest.fixture()
def _no_retry_sleep():
    """Eliminate actual sleeping inside retry_async."""
    with patch("backend.core.utils.retry.asyncio.sleep", new_callable=AsyncMock):
        yield


@pytest.fixture()
def mock_mcp_call():
    """Provide a controllable mock for ``backend.core.mcp_server.call_tool``.

    Injects a mock module into ``sys.modules`` so the deferred import
    inside ``MCPClient._direct_call`` resolves to our mock function.
    """
    mock_fn = AsyncMock()
    mock_module = MagicMock()
    mock_module.call_tool = mock_fn
    with patch.dict(sys.modules, {"backend.core.mcp_server": mock_module}):
        yield mock_fn


class TestMCPClientRetry:

    @pytest.fixture()
    def client(self) -> MCPClient:
        return MCPClient(base_url="http://localhost:8555")

    # ---- success path ----

    @pytest.mark.usefixtures("_no_retry_sleep")
    async def test_call_tool_success_first_attempt(
        self, client: MCPClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = _text_result("hello")
        result = await client.call_tool("test_tool", {"key": "val"})
        assert result["success"] is True
        assert result["result"] == "hello"

    # ---- retryable errors ----

    @pytest.mark.usefixtures("_no_retry_sleep")
    async def test_call_tool_retries_on_connection_error(
        self, client: MCPClient, mock_mcp_call: AsyncMock
    ) -> None:
        call_count = 0

        async def _side_effect(name: str, args: dict) -> list:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("connection refused")
            return _text_result("recovered")

        mock_mcp_call.side_effect = _side_effect
        result = await client.call_tool("test_tool")
        assert result["success"] is True
        assert call_count == 3

    @pytest.mark.usefixtures("_no_retry_sleep")
    async def test_call_tool_retries_on_timeout(
        self, client: MCPClient, mock_mcp_call: AsyncMock
    ) -> None:
        call_count = 0

        async def _side_effect(name: str, args: dict) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("timeout waiting for response")
            return _text_result("ok")

        mock_mcp_call.side_effect = _side_effect
        result = await client.call_tool("test_tool")
        assert result["success"] is True
        assert call_count == 2

    # ---- non-retryable errors ----

    @pytest.mark.usefixtures("_no_retry_sleep")
    async def test_call_tool_no_retry_on_value_error(
        self, client: MCPClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.side_effect = ValueError("Tool 'bad' not found")
        result = await client.call_tool("bad")
        assert result["success"] is False
        assert "not found" in result["error"]

    # ---- ImportError → HTTP fallback ----

    @pytest.mark.usefixtures("_no_retry_sleep")
    async def test_call_tool_import_error_falls_to_http(
        self, client: MCPClient
    ) -> None:
        """ImportError during deferred import triggers HTTP fallback."""
        with (
            patch.dict(sys.modules, {"backend.core.mcp_server": None}),
            patch.object(
                client,
                "call_tool_http",
                new_callable=AsyncMock,
                return_value={"success": True, "result": "via http"},
            ) as mock_http,
        ):
            result = await client.call_tool("test_tool")
        assert result["success"] is True
        assert result["result"] == "via http"
        mock_http.assert_called_once()

    # ---- retries exhausted → HTTP fallback ----

    @pytest.mark.usefixtures("_no_retry_sleep")
    async def test_call_tool_retries_exhausted_falls_to_http(
        self, client: MCPClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.side_effect = OSError("connection refused")
        with patch.object(
            client,
            "call_tool_http",
            new_callable=AsyncMock,
            return_value={"success": True, "result": "http fallback"},
        ) as mock_http:
            result = await client.call_tool("test_tool")
        assert result["success"] is True
        mock_http.assert_called_once()

    # ---- non-retryable exception (not ValueError/ImportError) ----

    @pytest.mark.usefixtures("_no_retry_sleep")
    async def test_call_tool_non_retryable_error_no_retry(
        self, client: MCPClient, mock_mcp_call: AsyncMock
    ) -> None:
        """A random non-retryable error should fall through to HTTP fallback."""
        call_count = 0

        async def _side_effect(name: str, args: dict) -> list:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("something completely unexpected")

        mock_mcp_call.side_effect = _side_effect
        with patch.object(
            client,
            "call_tool_http",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "also failed"},
        ):
            result = await client.call_tool("test_tool")
        # Non-retryable → should only call once, then fall to HTTP
        assert call_count == 1
        assert result["success"] is False
