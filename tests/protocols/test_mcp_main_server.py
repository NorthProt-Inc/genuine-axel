"""Tests for backend.protocols.mcp.server - MCPServer class.

Covers:
- Initialization and registration of resources/tools/prompts
- Request dispatching for all MCP message types
- Error handling for unknown methods, tools, resources
- Resource handler invocation (sync and async)
- Tool handler invocation (sync and async)
- Prompt generation
- Manifest generation
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.protocols.mcp.server import (
    MCPPrompt,
    MCPRequest,
    MCPResource,
    MCPResponse,
    MCPServer,
    MCPTool,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bare_server() -> MCPServer:
    """MCPServer with no backing managers (all None)."""
    return MCPServer()


@pytest.fixture
def full_server() -> MCPServer:
    """MCPServer with mocked managers wired up."""
    memory = MagicMock()
    memory.get_working_context.return_value = "working context text"
    memory.long_term = MagicMock()
    memory.long_term.get_stats.return_value = {"total": 42}
    memory.long_term.get_formatted_context.return_value = "memory result"
    memory.long_term.add.return_value = "doc-123"
    memory.get_stats.return_value = {"working": 10}
    memory.build_smart_context.return_value = "smart context"

    identity = MagicMock()
    identity.get_traits.return_value = ["curious", "friendly"]
    identity.get_mood.return_value = "happy"

    search = AsyncMock()
    search.search.return_value = "web search results"

    graph = MagicMock()
    graph.get_stats.return_value = {"nodes": 5}
    graph.query = AsyncMock()
    graph_result = MagicMock()
    graph_result.context = "graph context"
    graph.query.return_value = graph_result

    return MCPServer(
        memory_manager=memory,
        identity_manager=identity,
        search_agent=search,
        graph_rag=graph,
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestMCPServerInit:
    """Test server construction and internal registration."""

    def test_default_resources_registered(self, bare_server: MCPServer) -> None:
        assert "axnmihn://memory/working" in bare_server.resources
        assert "axnmihn://memory/long_term" in bare_server.resources
        assert "axnmihn://persona" in bare_server.resources
        assert "axnmihn://stats" in bare_server.resources
        assert len(bare_server.resources) == 4

    def test_default_tools_registered(self, bare_server: MCPServer) -> None:
        assert "search" in bare_server.tools
        assert "remember" in bare_server.tools
        assert "query_graph" in bare_server.tools
        assert len(bare_server.tools) == 3

    def test_default_prompts_registered(self, bare_server: MCPServer) -> None:
        assert "axnmihn_style" in bare_server.prompts
        assert "memory_context" in bare_server.prompts
        assert len(bare_server.prompts) == 2

    def test_resource_handlers_match_resources(self, bare_server: MCPServer) -> None:
        for uri in bare_server.resources:
            assert uri in bare_server.resource_handlers

    def test_tool_handlers_match_tools(self, bare_server: MCPServer) -> None:
        for name in bare_server.tools:
            assert name in bare_server.tool_handlers


# ---------------------------------------------------------------------------
# Custom registration
# ---------------------------------------------------------------------------


class TestRegistration:

    def test_register_custom_resource(self, bare_server: MCPServer) -> None:
        handler = MagicMock(return_value={"text": "custom"})
        resource = MCPResource(
            uri="axnmihn://custom/test",
            name="Custom",
            description="test resource",
        )
        bare_server.register_resource(resource, handler)

        assert "axnmihn://custom/test" in bare_server.resources
        assert bare_server.resource_handlers["axnmihn://custom/test"] is handler

    def test_register_custom_tool(self, bare_server: MCPServer) -> None:
        handler = MagicMock(return_value="done")
        tool = MCPTool(
            name="custom_tool",
            description="a custom tool",
            input_schema={"type": "object", "properties": {}},
        )
        bare_server.register_tool(tool, handler)

        assert "custom_tool" in bare_server.tools
        assert bare_server.tool_handlers["custom_tool"] is handler


# ---------------------------------------------------------------------------
# handle_request: initialize
# ---------------------------------------------------------------------------


class TestInitialize:

    async def test_initialize_returns_server_info(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="1", method="initialize")
        resp = await bare_server.handle_request(req)

        assert resp.id == "1"
        assert resp.error is None
        assert resp.result == MCPServer.SERVER_INFO
        assert resp.result["name"] == "axnmihn-mcp"


# ---------------------------------------------------------------------------
# handle_request: resources/list
# ---------------------------------------------------------------------------


class TestListResources:

    async def test_lists_all_resources(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="2", method="resources/list")
        resp = await bare_server.handle_request(req)

        assert resp.error is None
        resources = resp.result["resources"]
        assert len(resources) == 4
        uris = {r["uri"] for r in resources}
        assert "axnmihn://memory/working" in uris

    async def test_resource_shape(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="3", method="resources/list")
        resp = await bare_server.handle_request(req)

        resource = resp.result["resources"][0]
        assert "uri" in resource
        assert "name" in resource
        assert "description" in resource
        assert "mimeType" in resource


# ---------------------------------------------------------------------------
# handle_request: resources/read
# ---------------------------------------------------------------------------


class TestReadResource:

    async def test_read_working_memory_without_manager(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="4", method="resources/read", params={"uri": "axnmihn://memory/working"})
        resp = await bare_server.handle_request(req)

        assert resp.error is None
        content = resp.result["contents"][0]
        assert "Memory not available" in content["text"]

    async def test_read_working_memory_with_manager(self, full_server: MCPServer) -> None:
        req = MCPRequest(id="5", method="resources/read", params={"uri": "axnmihn://memory/working"})
        resp = await full_server.handle_request(req)

        assert resp.error is None
        content = resp.result["contents"][0]
        assert content["text"] == "working context text"

    async def test_read_long_term_memory_without_manager(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="6", method="resources/read", params={"uri": "axnmihn://memory/long_term"})
        resp = await bare_server.handle_request(req)

        content = resp.result["contents"][0]
        assert content["text"] == "{}"

    async def test_read_long_term_memory_with_manager(self, full_server: MCPServer) -> None:
        req = MCPRequest(id="7", method="resources/read", params={"uri": "axnmihn://memory/long_term"})
        resp = await full_server.handle_request(req)

        content = resp.result["contents"][0]
        data = json.loads(content["text"])
        assert data["total"] == 42

    async def test_read_persona_without_identity(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="8", method="resources/read", params={"uri": "axnmihn://persona"})
        resp = await bare_server.handle_request(req)

        content = resp.result["contents"][0]
        assert content["text"] == "{}"

    async def test_read_persona_with_identity(self, full_server: MCPServer) -> None:
        req = MCPRequest(id="9", method="resources/read", params={"uri": "axnmihn://persona"})
        resp = await full_server.handle_request(req)

        content = resp.result["contents"][0]
        data = json.loads(content["text"])
        assert data["name"] == "axnmihn"
        assert "curious" in data["traits"]
        assert data["mood"] == "happy"

    async def test_read_stats_with_managers(self, full_server: MCPServer) -> None:
        req = MCPRequest(id="10", method="resources/read", params={"uri": "axnmihn://stats"})
        resp = await full_server.handle_request(req)

        content = resp.result["contents"][0]
        data = json.loads(content["text"])
        assert "memory" in data
        assert "graph" in data

    async def test_read_stats_without_managers(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="11", method="resources/read", params={"uri": "axnmihn://stats"})
        resp = await bare_server.handle_request(req)

        content = resp.result["contents"][0]
        data = json.loads(content["text"])
        assert data == {}

    async def test_read_unknown_resource(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="12", method="resources/read", params={"uri": "axnmihn://nope"})
        resp = await bare_server.handle_request(req)

        assert resp.error is not None
        assert resp.error["code"] == -32602
        assert "Unknown resource" in resp.error["message"]

    async def test_read_resource_with_async_handler(self, bare_server: MCPServer) -> None:
        """Verify async resource handlers are awaited properly."""
        async def async_handler():
            return {"uri": "test://async", "text": "async result"}

        resource = MCPResource(uri="test://async", name="Async", description="test")
        bare_server.register_resource(resource, async_handler)

        req = MCPRequest(id="13", method="resources/read", params={"uri": "test://async"})
        resp = await bare_server.handle_request(req)

        assert resp.error is None
        assert resp.result["contents"][0]["text"] == "async result"


# ---------------------------------------------------------------------------
# handle_request: tools/list
# ---------------------------------------------------------------------------


class TestListTools:

    async def test_lists_all_tools(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="20", method="tools/list")
        resp = await bare_server.handle_request(req)

        assert resp.error is None
        tools = resp.result["tools"]
        assert len(tools) == 3
        names = {t["name"] for t in tools}
        assert names == {"search", "remember", "query_graph"}

    async def test_tool_shape(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="21", method="tools/list")
        resp = await bare_server.handle_request(req)

        tool = resp.result["tools"][0]
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool


# ---------------------------------------------------------------------------
# handle_request: tools/call
# ---------------------------------------------------------------------------


class TestCallTool:

    async def test_call_search_both(self, full_server: MCPServer) -> None:
        req = MCPRequest(
            id="30",
            method="tools/call",
            params={"name": "search", "arguments": {"query": "test"}},
        )
        resp = await full_server.handle_request(req)

        assert resp.error is None
        text = resp.result["content"][0]["text"]
        assert "[Web]" in text
        assert "[Memory]" in text

    async def test_call_search_web_only(self, full_server: MCPServer) -> None:
        req = MCPRequest(
            id="31",
            method="tools/call",
            params={"name": "search", "arguments": {"query": "test", "source": "web"}},
        )
        resp = await full_server.handle_request(req)

        text = resp.result["content"][0]["text"]
        assert "[Web]" in text
        assert "[Memory]" not in text

    async def test_call_search_memory_only(self, full_server: MCPServer) -> None:
        req = MCPRequest(
            id="32",
            method="tools/call",
            params={"name": "search", "arguments": {"query": "test", "source": "memory"}},
        )
        resp = await full_server.handle_request(req)

        text = resp.result["content"][0]["text"]
        assert "[Memory]" in text
        assert "[Web]" not in text

    async def test_call_search_no_backends(self, bare_server: MCPServer) -> None:
        req = MCPRequest(
            id="33",
            method="tools/call",
            params={"name": "search", "arguments": {"query": "test"}},
        )
        resp = await bare_server.handle_request(req)

        text = resp.result["content"][0]["text"]
        assert text == "No results"

    async def test_call_remember_success(self, full_server: MCPServer) -> None:
        req = MCPRequest(
            id="40",
            method="tools/call",
            params={
                "name": "remember",
                "arguments": {"content": "important fact", "type": "fact", "importance": 0.9},
            },
        )
        resp = await full_server.handle_request(req)

        text = resp.result["content"][0]["text"]
        assert "doc-123" in text
        full_server.memory.long_term.add.assert_called_once_with(
            content="important fact",
            memory_type="fact",
            importance=0.9,
            force=True,
        )

    async def test_call_remember_no_memory(self, bare_server: MCPServer) -> None:
        req = MCPRequest(
            id="41",
            method="tools/call",
            params={"name": "remember", "arguments": {"content": "test"}},
        )
        resp = await bare_server.handle_request(req)

        text = resp.result["content"][0]["text"]
        assert "Memory not available" in text

    async def test_call_query_graph_success(self, full_server: MCPServer) -> None:
        req = MCPRequest(
            id="50",
            method="tools/call",
            params={"name": "query_graph", "arguments": {"query": "people"}},
        )
        resp = await full_server.handle_request(req)

        text = resp.result["content"][0]["text"]
        assert "graph context" in text

    async def test_call_query_graph_no_graph(self, bare_server: MCPServer) -> None:
        req = MCPRequest(
            id="51",
            method="tools/call",
            params={"name": "query_graph", "arguments": {"query": "q"}},
        )
        resp = await bare_server.handle_request(req)

        text = resp.result["content"][0]["text"]
        assert "Graph RAG not available" in text

    async def test_call_query_graph_empty_context(self, full_server: MCPServer) -> None:
        empty_result = MagicMock()
        empty_result.context = ""
        full_server.graph.query.return_value = empty_result

        req = MCPRequest(
            id="52",
            method="tools/call",
            params={"name": "query_graph", "arguments": {"query": "q"}},
        )
        resp = await full_server.handle_request(req)

        text = resp.result["content"][0]["text"]
        assert "No graph results" in text

    async def test_call_unknown_tool(self, bare_server: MCPServer) -> None:
        req = MCPRequest(
            id="60",
            method="tools/call",
            params={"name": "does_not_exist", "arguments": {}},
        )
        resp = await bare_server.handle_request(req)

        assert resp.error is not None
        assert resp.error["code"] == -32602
        assert "Unknown tool" in resp.error["message"]

    async def test_call_sync_tool_handler(self, bare_server: MCPServer) -> None:
        """Register a sync handler and confirm it works through tools/call."""
        handler = MagicMock(return_value="sync result")
        tool = MCPTool(name="sync_test", description="sync", input_schema={"type": "object", "properties": {}})
        bare_server.register_tool(tool, handler)

        req = MCPRequest(
            id="61",
            method="tools/call",
            params={"name": "sync_test", "arguments": {}},
        )
        resp = await bare_server.handle_request(req)

        assert resp.error is None
        assert "sync result" in resp.result["content"][0]["text"]
        handler.assert_called_once()


# ---------------------------------------------------------------------------
# handle_request: prompts/list  &  prompts/get
# ---------------------------------------------------------------------------


class TestPrompts:

    async def test_list_prompts(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="70", method="prompts/list")
        resp = await bare_server.handle_request(req)

        assert resp.error is None
        prompts = resp.result["prompts"]
        assert len(prompts) == 2
        names = {p["name"] for p in prompts}
        assert names == {"axnmihn_style", "memory_context"}

    async def test_get_axnmihn_style_prompt(self, bare_server: MCPServer) -> None:
        req = MCPRequest(
            id="71",
            method="prompts/get",
            params={"name": "axnmihn_style", "arguments": {"message": "hello"}},
        )
        resp = await bare_server.handle_request(req)

        assert resp.error is None
        messages = resp.result["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "hello" in messages[0]["content"]["text"]

    async def test_get_memory_context_prompt_with_manager(self, full_server: MCPServer) -> None:
        req = MCPRequest(
            id="72",
            method="prompts/get",
            params={"name": "memory_context", "arguments": {"query": "who am I"}},
        )
        resp = await full_server.handle_request(req)

        messages = resp.result["messages"]
        assert "[Context]" in messages[0]["content"]["text"]
        assert "smart context" in messages[0]["content"]["text"]
        assert "who am I" in messages[0]["content"]["text"]

    async def test_get_memory_context_prompt_without_manager(self, bare_server: MCPServer) -> None:
        req = MCPRequest(
            id="73",
            method="prompts/get",
            params={"name": "memory_context", "arguments": {"query": "test"}},
        )
        resp = await bare_server.handle_request(req)

        messages = resp.result["messages"]
        assert "[Context]" in messages[0]["content"]["text"]

    async def test_get_unknown_prompt(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="74", method="prompts/get", params={"name": "nope"})
        resp = await bare_server.handle_request(req)

        assert resp.error is not None
        assert resp.error["code"] == -32602
        assert "Unknown prompt" in resp.error["message"]


# ---------------------------------------------------------------------------
# handle_request: unknown method
# ---------------------------------------------------------------------------


class TestUnknownMethod:

    async def test_unknown_method_returns_error(self, bare_server: MCPServer) -> None:
        req = MCPRequest(id="80", method="totally/unknown")
        resp = await bare_server.handle_request(req)

        assert resp.error is not None
        assert resp.error["code"] == -32601
        assert "Method not found" in resp.error["message"]


# ---------------------------------------------------------------------------
# handle_request: exception handling
# ---------------------------------------------------------------------------


class TestExceptionHandling:

    async def test_handler_exception_returns_internal_error(self, bare_server: MCPServer) -> None:
        """If a resource handler raises, the server wraps it in -32603."""

        def exploding_handler():
            raise RuntimeError("boom")

        resource = MCPResource(uri="test://explode", name="Explode", description="test")
        bare_server.register_resource(resource, exploding_handler)

        req = MCPRequest(id="90", method="resources/read", params={"uri": "test://explode"})
        resp = await bare_server.handle_request(req)

        assert resp.error is not None
        assert resp.error["code"] == -32603
        assert "boom" in resp.error["message"]

    async def test_tool_handler_exception_wrapped(self, bare_server: MCPServer) -> None:
        async def bad_tool(**kwargs):
            raise ValueError("bad input")

        tool = MCPTool(name="bad", description="bad", input_schema={"type": "object", "properties": {}})
        bare_server.register_tool(tool, bad_tool)

        req = MCPRequest(id="91", method="tools/call", params={"name": "bad", "arguments": {}})
        resp = await bare_server.handle_request(req)

        assert resp.error is not None
        assert resp.error["code"] == -32603
        assert "bad input" in resp.error["message"]


# ---------------------------------------------------------------------------
# get_manifest
# ---------------------------------------------------------------------------


class TestGetManifest:

    def test_manifest_structure(self, bare_server: MCPServer) -> None:
        manifest = bare_server.get_manifest()

        assert "server" in manifest
        assert "resources" in manifest
        assert "tools" in manifest
        assert "prompts" in manifest
        assert manifest["server"]["name"] == "axnmihn-mcp"

    def test_manifest_counts(self, bare_server: MCPServer) -> None:
        manifest = bare_server.get_manifest()

        assert len(manifest["resources"]) == 4
        assert len(manifest["tools"]) == 3
        assert len(manifest["prompts"]) == 2

    def test_manifest_resource_keys(self, bare_server: MCPServer) -> None:
        manifest = bare_server.get_manifest()
        resource = manifest["resources"][0]
        assert all(k in resource for k in ("uri", "name", "description", "mimeType"))

    def test_manifest_tool_keys(self, bare_server: MCPServer) -> None:
        manifest = bare_server.get_manifest()
        tool = manifest["tools"][0]
        assert all(k in tool for k in ("name", "description", "inputSchema"))

    def test_manifest_prompt_keys(self, bare_server: MCPServer) -> None:
        manifest = bare_server.get_manifest()
        prompt = manifest["prompts"][0]
        assert all(k in prompt for k in ("name", "description", "arguments"))


# ---------------------------------------------------------------------------
# Dataclass / enum basics
# ---------------------------------------------------------------------------


class TestDataclasses:

    def test_mcp_request_defaults(self) -> None:
        req = MCPRequest(id="x", method="test")
        assert req.params == {}

    def test_mcp_response_defaults(self) -> None:
        resp = MCPResponse(id="x")
        assert resp.result is None
        assert resp.error is None

    def test_mcp_resource_default_mime(self) -> None:
        r = MCPResource(uri="u", name="n", description="d")
        assert r.mime_type == "application/json"

    def test_mcp_tool_fields(self) -> None:
        t = MCPTool(name="t", description="d", input_schema={"type": "object"})
        assert t.name == "t"
        assert t.input_schema == {"type": "object"}

    def test_mcp_prompt_fields(self) -> None:
        p = MCPPrompt(name="p", description="d", arguments=[{"name": "a"}])
        assert p.name == "p"
        assert len(p.arguments) == 1
