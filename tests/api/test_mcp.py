"""Tests for backend.api.mcp -- MCP (Model Context Protocol) endpoints."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from backend.protocols.mcp.server import MCPServer, MCPResponse


# ---------------------------------------------------------------------------
# GET /mcp/status
# ---------------------------------------------------------------------------


class TestMCPStatus:

    def test_returns_server_info(self, no_auth_client, mock_state):
        resp = no_auth_client.get("/mcp/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"
        assert "server_info" in body
        assert body["server_info"]["name"] == "axnmihn-mcp"
        assert isinstance(body["resources"], int)
        assert isinstance(body["tools"], int)
        assert isinstance(body["prompts"], int)

    def test_lazily_creates_mcp_server(self, no_auth_client, mock_state):
        """First call should create the MCPServer on state.mcp_server."""
        mock_state.mcp_server = None
        resp = no_auth_client.get("/mcp/status")
        assert resp.status_code == 200
        # After the call, a real MCPServer should have been created
        body = resp.json()
        assert body["status"] == "running"


# ---------------------------------------------------------------------------
# GET /mcp/manifest
# ---------------------------------------------------------------------------


class TestMCPManifest:

    def test_returns_manifest(self, no_auth_client, mock_state):
        resp = no_auth_client.get("/mcp/manifest")
        assert resp.status_code == 200
        body = resp.json()
        assert "server" in body
        assert "resources" in body
        assert "tools" in body
        assert "prompts" in body

    def test_manifest_has_expected_tools(self, no_auth_client, mock_state):
        resp = no_auth_client.get("/mcp/manifest")
        body = resp.json()
        tool_names = {t["name"] for t in body["tools"]}
        assert "search" in tool_names
        assert "remember" in tool_names
        assert "query_graph" in tool_names

    def test_manifest_has_expected_resources(self, no_auth_client, mock_state):
        resp = no_auth_client.get("/mcp/manifest")
        body = resp.json()
        resource_uris = {r["uri"] for r in body["resources"]}
        assert "axnmihn://memory/working" in resource_uris
        assert "axnmihn://memory/long_term" in resource_uris
        assert "axnmihn://persona" in resource_uris
        assert "axnmihn://stats" in resource_uris

    def test_manifest_has_expected_prompts(self, no_auth_client, mock_state):
        resp = no_auth_client.get("/mcp/manifest")
        body = resp.json()
        prompt_names = {p["name"] for p in body["prompts"]}
        assert "axnmihn_style" in prompt_names
        assert "memory_context" in prompt_names


# ---------------------------------------------------------------------------
# POST /mcp/execute -- initialize
# ---------------------------------------------------------------------------


class TestMCPExecuteInitialize:

    def test_initialize(self, no_auth_client, mock_state):
        resp = no_auth_client.post("/mcp/execute", json={
            "id": "1",
            "method": "initialize",
            "params": {},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"] is None
        assert body["result"]["name"] == "axnmihn-mcp"


# ---------------------------------------------------------------------------
# POST /mcp/execute -- resources/list
# ---------------------------------------------------------------------------


class TestMCPExecuteResourcesList:

    def test_list_resources(self, no_auth_client, mock_state):
        resp = no_auth_client.post("/mcp/execute", json={
            "id": "2",
            "method": "resources/list",
            "params": {},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"] is None
        resources = body["result"]["resources"]
        assert len(resources) >= 4


# ---------------------------------------------------------------------------
# POST /mcp/execute -- resources/read
# ---------------------------------------------------------------------------


class TestMCPExecuteResourcesRead:

    def test_read_working_memory(self, no_auth_client, mock_state):
        resp = no_auth_client.post("/mcp/execute", json={
            "id": "3",
            "method": "resources/read",
            "params": {"uri": "axnmihn://memory/working"},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"] is None
        assert "contents" in body["result"]

    def test_read_unknown_resource(self, no_auth_client, mock_state):
        resp = no_auth_client.post("/mcp/execute", json={
            "id": "4",
            "method": "resources/read",
            "params": {"uri": "axnmihn://nonexistent"},
        })
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"] is not None
        assert body["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# POST /mcp/execute -- tools/list
# ---------------------------------------------------------------------------


class TestMCPExecuteToolsList:

    def test_list_tools(self, no_auth_client, mock_state):
        resp = no_auth_client.post("/mcp/execute", json={
            "id": "5",
            "method": "tools/list",
            "params": {},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"] is None
        tools = body["result"]["tools"]
        assert len(tools) >= 3
        tool_names = {t["name"] for t in tools}
        assert "search" in tool_names
        assert "remember" in tool_names


# ---------------------------------------------------------------------------
# POST /mcp/execute -- tools/call
# ---------------------------------------------------------------------------


class TestMCPExecuteToolsCall:

    def test_call_remember_tool(self, no_auth_client, mock_state):
        # Create a real MCPServer but with our mocked memory_manager
        mock_state.mcp_server = None

        resp = no_auth_client.post("/mcp/execute", json={
            "id": "6",
            "method": "tools/call",
            "params": {
                "name": "remember",
                "arguments": {"content": "User likes cats", "type": "fact"},
            },
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"] is None
        assert "content" in body["result"]

    def test_call_unknown_tool(self, no_auth_client, mock_state):
        resp = no_auth_client.post("/mcp/execute", json={
            "id": "7",
            "method": "tools/call",
            "params": {"name": "nonexistent", "arguments": {}},
        })
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# POST /mcp/execute -- prompts/list
# ---------------------------------------------------------------------------


class TestMCPExecutePromptsList:

    def test_list_prompts(self, no_auth_client, mock_state):
        resp = no_auth_client.post("/mcp/execute", json={
            "id": "8",
            "method": "prompts/list",
            "params": {},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"] is None
        prompts = body["result"]["prompts"]
        assert len(prompts) >= 2


# ---------------------------------------------------------------------------
# POST /mcp/execute -- prompts/get
# ---------------------------------------------------------------------------


class TestMCPExecutePromptsGet:

    def test_get_known_prompt(self, no_auth_client, mock_state):
        resp = no_auth_client.post("/mcp/execute", json={
            "id": "9",
            "method": "prompts/get",
            "params": {"name": "axnmihn_style", "arguments": {"message": "hello"}},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"] is None
        assert "messages" in body["result"]

    def test_get_unknown_prompt(self, no_auth_client, mock_state):
        resp = no_auth_client.post("/mcp/execute", json={
            "id": "10",
            "method": "prompts/get",
            "params": {"name": "nonexistent"},
        })
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# POST /mcp/execute -- unknown method
# ---------------------------------------------------------------------------


class TestMCPExecuteUnknownMethod:

    def test_unknown_method(self, no_auth_client, mock_state):
        resp = no_auth_client.post("/mcp/execute", json={
            "id": "11",
            "method": "bogus/method",
            "params": {},
        })
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# POST /mcp/execute -- exception handling
# ---------------------------------------------------------------------------


class TestMCPExecuteErrors:

    def test_internal_exception(self, no_auth_client, mock_state):
        """If MCPServer.handle_request raises, the endpoint returns 500."""
        server = MagicMock(spec=MCPServer)
        server.handle_request = AsyncMock(side_effect=RuntimeError("kaboom"))
        mock_state.mcp_server = server

        resp = no_auth_client.post("/mcp/execute", json={
            "id": "12",
            "method": "initialize",
            "params": {},
        })
        assert resp.status_code == 500
