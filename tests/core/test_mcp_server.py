"""Tests for backend.core.mcp_server module.

Covers: read_file_safe, list_resources, read_resource,
list_resource_templates, list_tools, call_tool, health_check.
All tool registry and transport layer dependencies are mocked.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# We need to mock heavy imports before importing the module
# Mock the tool registry and transport imports
_mock_tool_handlers = {}
_mock_tool_metadata = {}


def _mock_get_tool_handler(name):
    if name not in _mock_tool_handlers:
        raise ValueError(f"Unknown tool: '{name}'")
    return _mock_tool_handlers[name]


def _mock_is_tool_registered(name):
    return name in _mock_tool_handlers


def _mock_list_registered_tools():
    return sorted(_mock_tool_handlers.keys())


def _mock_get_tool_schemas():
    from mcp.types import Tool
    return [
        Tool(name=n, description=f"Tool {n}", inputSchema={"type": "object"})
        for n in _mock_tool_handlers
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_tool_handlers():
    """Reset mock handlers between tests."""
    _mock_tool_handlers.clear()
    yield
    _mock_tool_handlers.clear()


# ---------------------------------------------------------------------------
# read_file_safe
# ---------------------------------------------------------------------------
class TestReadFileSafe:
    async def test_reads_existing_file(self, tmp_path):
        from backend.core.mcp_server import read_file_safe

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world", encoding="utf-8")
        result = await read_file_safe(test_file)
        assert result == "hello world"

    async def test_returns_error_for_missing_file(self, tmp_path):
        from backend.core.mcp_server import read_file_safe

        missing = tmp_path / "does_not_exist.txt"
        result = await read_file_safe(missing)
        assert "Error: File not found" in result

    async def test_returns_error_on_read_exception(self, tmp_path):
        from backend.core.mcp_server import read_file_safe

        test_file = tmp_path / "test.txt"
        test_file.write_text("data", encoding="utf-8")

        with patch("asyncio.to_thread", side_effect=PermissionError("denied")):
            result = await read_file_safe(test_file)
            assert "Error reading file" in result


# ---------------------------------------------------------------------------
# list_resources
# ---------------------------------------------------------------------------
class TestListResources:
    async def test_returns_resources(self):
        from backend.core.mcp_server import list_resources

        resources = await list_resources()
        assert len(resources) >= 1
        names = [r.name for r in resources]
        assert "Axel Working Memory" in names

    async def test_working_memory_resource_uri(self):
        from backend.core.mcp_server import list_resources

        resources = await list_resources()
        uris = [str(r.uri) for r in resources]
        assert any("memory/working" in u for u in uris)


# ---------------------------------------------------------------------------
# read_resource
# ---------------------------------------------------------------------------
class TestReadResource:
    async def test_reads_working_memory(self):
        from backend.core.mcp_server import read_resource
        import mcp.types as types

        with patch("backend.core.mcp_server.read_file_safe", new_callable=AsyncMock,
                   return_value='{"status": "ok"}') as mock_read:
            result = await read_resource(types.AnyUrl("axel://memory/working"))
            assert result == '{"status": "ok"}'

    async def test_unknown_resource_raises(self):
        from backend.core.mcp_server import read_resource
        import mcp.types as types

        with pytest.raises(ValueError, match="Resource not found"):
            await read_resource(types.AnyUrl("axel://unknown/resource"))


# ---------------------------------------------------------------------------
# list_resource_templates
# ---------------------------------------------------------------------------
class TestListResourceTemplates:
    async def test_returns_empty_list(self):
        from backend.core.mcp_server import list_resource_templates

        templates = await list_resource_templates()
        assert templates == []


# ---------------------------------------------------------------------------
# list_tools (server-side)
# ---------------------------------------------------------------------------
class TestListToolsServer:
    async def test_returns_tool_schemas(self):
        from backend.core.mcp_server import list_tools

        with patch("backend.core.mcp_server.get_tool_schemas") as mock_schemas:
            mock_schemas.return_value = [
                SimpleNamespace(name="tool_a", description="Tool A"),
                SimpleNamespace(name="tool_b", description="Tool B"),
            ]
            result = await list_tools()
            assert len(result) == 2


# ---------------------------------------------------------------------------
# call_tool (server-side dispatch)
# ---------------------------------------------------------------------------
class TestCallToolServer:
    async def test_registered_tool_success(self):
        from backend.core.mcp_server import call_tool
        from mcp.types import TextContent

        mock_handler = AsyncMock(return_value=[TextContent(type="text", text="result")])

        with patch("backend.core.mcp_server.is_tool_registered", return_value=True):
            with patch("backend.core.mcp_server.get_tool_handler", return_value=mock_handler):
                result = await call_tool("test_tool", {"key": "value"})
                assert len(result) == 1
                assert result[0].text == "result"

    async def test_unregistered_tool_returns_error(self):
        from backend.core.mcp_server import call_tool

        with patch("backend.core.mcp_server.is_tool_registered", return_value=False):
            with patch("backend.core.mcp_server.list_registered_tools", return_value=["other_tool"]):
                result = await call_tool("missing_tool", {})
                assert len(result) == 1
                assert "Unknown tool" in result[0].text

    async def test_tool_timeout(self):
        from backend.core.mcp_server import call_tool

        async def slow_handler(args):
            await asyncio.sleep(10)
            return []

        with patch("backend.core.mcp_server.is_tool_registered", return_value=True):
            with patch("backend.core.mcp_server.get_tool_handler", return_value=slow_handler):
                with patch("backend.core.mcp_server.TIMEOUT_MCP_TOOL", 0.01):
                    result = await call_tool("slow_tool", {})
                    assert "timed out" in result[0].text

    async def test_none_arguments_defaults_to_empty(self):
        from backend.core.mcp_server import call_tool
        from mcp.types import TextContent

        mock_handler = AsyncMock(return_value=[TextContent(type="text", text="ok")])

        with patch("backend.core.mcp_server.is_tool_registered", return_value=True):
            with patch("backend.core.mcp_server.get_tool_handler", return_value=mock_handler):
                result = await call_tool("test_tool", None)
                mock_handler.assert_called_once_with({})
                assert result[0].text == "ok"

    async def test_value_error_in_dispatch(self):
        from backend.core.mcp_server import call_tool

        with patch("backend.core.mcp_server.is_tool_registered", side_effect=ValueError("bad dispatch")):
            result = await call_tool("test_tool", {})
            assert "bad dispatch" in result[0].text

    async def test_generic_exception_in_handler(self):
        from backend.core.mcp_server import call_tool

        mock_handler = AsyncMock(side_effect=RuntimeError("handler crash"))

        with patch("backend.core.mcp_server.is_tool_registered", return_value=True):
            with patch("backend.core.mcp_server.get_tool_handler", return_value=mock_handler):
                result = await call_tool("crashing_tool", {})
                assert "Error executing" in result[0].text
                assert "handler crash" in result[0].text


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------
class TestHealthCheck:
    async def test_health_check_response(self):
        from backend.core.mcp_server import health_check

        with patch("backend.core.mcp_server.get_connection_count", return_value=3):
            result = await health_check()
            assert result["status"] == "healthy"
            assert result["active_connections"] == 3
            assert result["server"] == "axel-mcp-server"


# ---------------------------------------------------------------------------
# Module-level objects
# ---------------------------------------------------------------------------
class TestModuleLevelObjects:
    def test_mcp_server_exists(self):
        from backend.core.mcp_server import mcp_server
        assert mcp_server is not None

    def test_app_exists(self):
        from backend.core.mcp_server import app
        assert app is not None
        assert app.title == "Axel MCP Server"
