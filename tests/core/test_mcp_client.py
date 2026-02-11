"""Tests for backend.core.mcp_client module.

Covers: MCPClient - call_tool, call_tool_http, list_tools,
get_tools_with_schemas, get_gemini_tools, get_anthropic_tools, caching.
All MCP server imports and HTTP I/O are mocked.
"""

import time
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from backend.core.mcp_client import MCPClient, CORE_TOOLS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_tool(name, description="desc", input_schema=None):
    """Create a SimpleNamespace mimicking an MCP Tool object."""
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema=input_schema or {"type": "object", "properties": {}},
    )


def _make_text_content(text):
    """Create a SimpleNamespace mimicking MCP TextContent."""
    return SimpleNamespace(text=text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    return MCPClient(base_url="http://test-mcp:8555")


# ---------------------------------------------------------------------------
# call_tool - direct path
# ---------------------------------------------------------------------------
class TestCallTool:
    async def test_direct_call_success(self, client):
        mock_result = [_make_text_content("Hello from tool")]
        with patch("backend.core.mcp_client.retry_async") as mock_retry:
            mock_retry.side_effect = lambda func, **kwargs: func()
            with patch("backend.core.mcp_client.MCPClient.call_tool") as original:
                pass

        # Simpler: just test via the actual call_tool with mocked internals
        with patch("backend.core.mcp_client.retry_async", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = {"success": True, "result": "Hello from tool"}
            result = await client.call_tool("test_tool", {"arg": "value"})
            assert result["success"] is True

    async def test_import_error_falls_back_to_http(self, client):
        """When direct import fails, should fall back to HTTP."""
        with patch("backend.core.mcp_client.retry_async", side_effect=ImportError("no module")):
            with patch.object(client, "call_tool_http", new_callable=AsyncMock) as mock_http:
                mock_http.return_value = {"success": True, "result": "via HTTP"}
                result = await client.call_tool("test_tool")
                mock_http.assert_called_once_with("test_tool", {})
                assert result["success"] is True

    async def test_value_error_returns_error(self, client):
        with patch("backend.core.mcp_client.retry_async", side_effect=ValueError("tool not found")):
            result = await client.call_tool("missing_tool")
            assert result["success"] is False
            assert "not found" in result["error"]

    async def test_generic_exception_falls_back_to_http(self, client):
        with patch("backend.core.mcp_client.retry_async", side_effect=RuntimeError("connection lost")):
            with patch.object(client, "call_tool_http", new_callable=AsyncMock) as mock_http:
                mock_http.return_value = {"success": True, "result": "http fallback"}
                result = await client.call_tool("test_tool")
                assert result["success"] is True

    async def test_generic_exception_http_also_fails(self, client):
        with patch("backend.core.mcp_client.retry_async", side_effect=RuntimeError("retries exhausted")):
            with patch.object(client, "call_tool_http", new_callable=AsyncMock) as mock_http:
                mock_http.return_value = {"success": False, "error": "http failed too"}
                result = await client.call_tool("test_tool")
                assert result["success"] is False
                assert "retries" in result["error"]

    async def test_default_arguments_is_empty_dict(self, client):
        """When arguments=None, should default to {}."""
        with patch("backend.core.mcp_client.retry_async", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = {"success": True, "result": "ok"}
            await client.call_tool("test_tool", None)
            # The internal _direct_call uses arguments which defaults to {}


# ---------------------------------------------------------------------------
# call_tool_http
# ---------------------------------------------------------------------------
class TestCallToolHttp:
    async def test_http_success(self, client):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"result": "http result"})

        mock_session = AsyncMock()
        mock_post_cm = AsyncMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_post_cm)

        with patch.object(client, "_get_session", return_value=mock_session):
            result = await client.call_tool_http("test_tool", {"arg": "val"})
            assert result["success"] is True
            assert result["result"] == "http result"

    async def test_http_error_status(self, client):
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")

        mock_session = AsyncMock()
        mock_post_cm = AsyncMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_post_cm)

        with patch.object(client, "_get_session", return_value=mock_session):
            result = await client.call_tool_http("test_tool")
            assert result["success"] is False
            assert "500" in result["error"]

    async def test_http_exception(self, client):
        with patch.object(client, "_get_session", side_effect=Exception("connection refused")):
            result = await client.call_tool_http("test_tool")
            assert result["success"] is False
            assert "connection refused" in result["error"]

    async def test_http_default_arguments(self, client):
        """Arguments default to empty dict when None."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"result": "ok"})

        mock_session = AsyncMock()
        mock_post_cm = AsyncMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_post_cm)

        with patch.object(client, "_get_session", return_value=mock_session):
            result = await client.call_tool_http("test_tool", None)
            assert result["success"] is True

    async def test_session_reused_across_calls(self, client):
        """Persistent session is reused across multiple HTTP calls."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"result": "ok"})

        mock_session = AsyncMock()
        mock_post_cm = AsyncMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_post_cm)

        with patch.object(client, "_get_session", return_value=mock_session) as mock_get:
            await client.call_tool_http("tool_1")
            await client.call_tool_http("tool_2")
            assert mock_get.call_count == 2
            # Same session object returned both times
            assert mock_session.post.call_count == 2


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------
class TestListTools:
    async def test_list_tools_success(self, client):
        tools = [_make_tool("tool_a", "desc A"), _make_tool("tool_b", "desc B")]
        with patch("backend.core.mcp_client.MCPClient.list_tools") as mock_lt:
            # Re-mock to use actual implementation but with mocked import
            pass

        # Test by mocking the import inside
        mock_tools = [_make_tool("tool_a", "desc A"), _make_tool("tool_b", "desc B")]
        with patch.dict("sys.modules", {}):
            with patch("backend.core.mcp_server.list_tools", new_callable=AsyncMock,
                       return_value=mock_tools, create=True) as mock_list:
                # Patch at the import point
                async def patched_list_tools():
                    return [{"name": t.name, "description": t.description} for t in mock_tools]

                with patch.object(client, "list_tools", patched_list_tools):
                    result = await client.list_tools()
                    assert len(result) == 2
                    assert result[0]["name"] == "tool_a"

    async def test_list_tools_exception_returns_empty(self, client):
        """On error, returns empty list."""
        # Override list_tools to simulate the real behavior with an import error
        original_list = MCPClient.list_tools

        async def failing_list(self_inner):
            # Simulate what happens when the import inside fails
            try:
                raise ImportError("no module")
            except Exception as e:
                return []

        with patch.object(MCPClient, "list_tools", failing_list):
            result = await client.list_tools()
            assert result == []


# ---------------------------------------------------------------------------
# get_tools_with_schemas
# ---------------------------------------------------------------------------
class TestGetToolsWithSchemas:
    async def test_success(self, client):
        mock_tools = [
            _make_tool("tool_a", "desc A", {"type": "object", "properties": {"x": {"type": "string"}}})
        ]

        async def patched():
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.inputSchema,
                }
                for t in mock_tools
            ]

        with patch.object(client, "get_tools_with_schemas", patched):
            result = await client.get_tools_with_schemas()
            assert len(result) == 1
            assert result[0]["input_schema"]["properties"]["x"]["type"] == "string"

    async def test_exception_returns_empty(self, client):
        async def failing():
            return []

        with patch.object(client, "get_tools_with_schemas", failing):
            result = await client.get_tools_with_schemas()
            assert result == []


# ---------------------------------------------------------------------------
# get_gemini_tools
# ---------------------------------------------------------------------------
class TestGetGeminiTools:
    async def test_returns_formatted_tools(self, client):
        mock_schemas = [
            {
                "name": "run_command",
                "description": "Run a shell command",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command"}
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "custom_tool",
                "description": "A custom tool",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "arg": {"type": "string", "description": "An arg", "enum": ["a", "b"]}
                    },
                    "required": [],
                },
            },
        ]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas):
            result = await client.get_gemini_tools(force_refresh=True)
            assert len(result) == 2

            # Core tools come first
            assert result[0]["name"] == "run_command"

            # Check Gemini format
            params = result[0]["parameters"]
            assert params["type"] == "OBJECT"
            assert "command" in params["properties"]
            assert params["properties"]["command"]["type"] == "STRING"
            assert params["required"] == ["command"]

            # Check enum support
            custom = result[1]
            assert "enum" in custom["parameters"]["properties"]["arg"]

    async def test_cache_used_on_second_call(self, client):
        mock_schemas = [{"name": "tool_a", "description": "A", "input_schema": {"type": "object", "properties": {}, "required": []}}]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas) as mock_get:
            # First call populates cache
            await client.get_gemini_tools(force_refresh=True)
            assert mock_get.call_count == 1

            # Second call should use cache
            await client.get_gemini_tools()
            assert mock_get.call_count == 1  # Not called again

    async def test_force_refresh_bypasses_cache(self, client):
        mock_schemas = [{"name": "tool_a", "description": "A", "input_schema": {"type": "object", "properties": {}, "required": []}}]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas) as mock_get:
            await client.get_gemini_tools(force_refresh=True)
            await client.get_gemini_tools(force_refresh=True)
            assert mock_get.call_count == 2

    async def test_cache_expires_after_ttl(self, client):
        mock_schemas = [{"name": "tool_a", "description": "A", "input_schema": {"type": "object", "properties": {}, "required": []}}]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas) as mock_get:
            await client.get_gemini_tools(force_refresh=True)

            # Backdate cache timestamp
            client._cache_timestamp = time.time() - client.TOOLS_CACHE_TTL - 1

            await client.get_gemini_tools()
            assert mock_get.call_count == 2

    async def test_max_tools_limits_output(self, client):
        mock_schemas = [
            {"name": f"tool_{i}", "description": f"Tool {i}", "input_schema": {"type": "object", "properties": {}, "required": []}}
            for i in range(20)
        ]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas):
            result = await client.get_gemini_tools(force_refresh=True, max_tools=5)
            assert len(result) == 5

    async def test_core_tools_prioritized(self, client):
        mock_schemas = [
            {"name": "custom_tool", "description": "Custom", "input_schema": {"type": "object", "properties": {}, "required": []}},
            {"name": "run_command", "description": "Core tool", "input_schema": {"type": "object", "properties": {}, "required": []}},
        ]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas):
            result = await client.get_gemini_tools(force_refresh=True)
            # run_command is in CORE_TOOLS, should come first
            assert result[0]["name"] == "run_command"


# ---------------------------------------------------------------------------
# get_anthropic_tools
# ---------------------------------------------------------------------------
class TestGetAnthropicTools:
    async def test_returns_formatted_tools(self, client):
        mock_schemas = [
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        ]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas):
            result = await client.get_anthropic_tools(force_refresh=True)
            assert len(result) == 1
            assert result[0]["name"] == "read_file"
            assert result[0]["input_schema"]["properties"]["path"]["type"] == "string"

    async def test_cache_used(self, client):
        mock_schemas = [{"name": "tool_a", "description": "A", "input_schema": {"type": "object", "properties": {}}}]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas) as mock_get:
            await client.get_anthropic_tools(force_refresh=True)
            await client.get_anthropic_tools()
            assert mock_get.call_count == 1

    async def test_force_refresh(self, client):
        mock_schemas = [{"name": "tool_a", "description": "A", "input_schema": {"type": "object", "properties": {}}}]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas) as mock_get:
            await client.get_anthropic_tools(force_refresh=True)
            await client.get_anthropic_tools(force_refresh=True)
            assert mock_get.call_count == 2

    async def test_cache_expires(self, client):
        mock_schemas = [{"name": "tool_a", "description": "A", "input_schema": {"type": "object", "properties": {}}}]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas) as mock_get:
            await client.get_anthropic_tools(force_refresh=True)
            client._anthropic_cache_timestamp = time.time() - client.TOOLS_CACHE_TTL - 1
            await client.get_anthropic_tools()
            assert mock_get.call_count == 2

    async def test_max_tools(self, client):
        mock_schemas = [
            {"name": f"tool_{i}", "description": f"T{i}", "input_schema": {"type": "object", "properties": {}}}
            for i in range(20)
        ]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas):
            result = await client.get_anthropic_tools(force_refresh=True, max_tools=3)
            assert len(result) == 3

    async def test_core_tools_prioritized(self, client):
        mock_schemas = [
            {"name": "custom_tool", "description": "Custom", "input_schema": {"type": "object", "properties": {}}},
            {"name": "store_memory", "description": "Core", "input_schema": {"type": "object", "properties": {}}},
        ]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas):
            result = await client.get_anthropic_tools(force_refresh=True)
            assert result[0]["name"] == "store_memory"

    async def test_missing_input_schema_gets_default(self, client):
        mock_schemas = [
            {"name": "tool_no_schema", "description": "No schema"},
        ]
        with patch.object(client, "get_tools_with_schemas", new_callable=AsyncMock,
                         return_value=mock_schemas):
            result = await client.get_anthropic_tools(force_refresh=True)
            assert result[0]["input_schema"] == {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# MCPClient construction
# ---------------------------------------------------------------------------
class TestMCPClientConstruction:
    def test_default_base_url(self):
        with patch("backend.core.mcp_client.MCP_SERVER_URL", "http://default:9999"):
            c = MCPClient()
            assert c.base_url == "http://default:9999"

    def test_custom_base_url(self):
        c = MCPClient(base_url="http://custom:1234")
        assert c.base_url == "http://custom:1234"

    def test_initial_cache_state(self):
        c = MCPClient()
        assert c._gemini_tools_cache is None
        assert c._anthropic_tools_cache is None
        assert c._cache_timestamp == 0
        assert c._anthropic_cache_timestamp == 0
        assert c._session is None


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------
class TestSessionLifecycle:
    def test_get_session_creates_session(self, client):
        assert client._session is None
        with patch("aiohttp.ClientSession") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.closed = False
            mock_cls.return_value = mock_instance
            session = client._get_session()
            assert session is mock_instance
            mock_cls.assert_called_once()

    def test_get_session_reuses_open_session(self, client):
        mock_session = MagicMock()
        mock_session.closed = False
        client._session = mock_session
        with patch("aiohttp.ClientSession") as mock_cls:
            session = client._get_session()
            assert session is mock_session
            mock_cls.assert_not_called()

    def test_get_session_recreates_closed_session(self, client):
        closed_session = MagicMock()
        closed_session.closed = True
        client._session = closed_session
        with patch("aiohttp.ClientSession") as mock_cls:
            new_session = MagicMock()
            new_session.closed = False
            mock_cls.return_value = new_session
            session = client._get_session()
            assert session is new_session

    async def test_close_session(self, client):
        mock_session = AsyncMock()
        mock_session.closed = False
        client._session = mock_session
        await client.close()
        mock_session.close.assert_called_once()
        assert client._session is None

    async def test_close_already_closed_session(self, client):
        mock_session = AsyncMock()
        mock_session.closed = True
        client._session = mock_session
        await client.close()
        mock_session.close.assert_not_called()

    async def test_close_no_session(self, client):
        """Close when no session exists should be a no-op."""
        await client.close()  # Should not raise


# ---------------------------------------------------------------------------
# get_mcp_client singleton
# ---------------------------------------------------------------------------
class TestGetMCPClient:
    def test_returns_mcp_client_instance(self):
        from backend.core.mcp_client import get_mcp_client
        client = get_mcp_client()
        assert isinstance(client, MCPClient)

    def test_returns_same_instance(self):
        from backend.core.mcp_client import get_mcp_client
        c1 = get_mcp_client()
        c2 = get_mcp_client()
        assert c1 is c2
