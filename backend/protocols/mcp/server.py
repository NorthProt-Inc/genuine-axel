import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

from backend.core.logging import get_logger

_log = get_logger("protocols.mcp_server")

class MCPMessageType(Enum):
    INITIALIZE = "initialize"
    LIST_RESOURCES = "resources/list"
    READ_RESOURCE = "resources/read"
    LIST_TOOLS = "tools/list"
    CALL_TOOL = "tools/call"
    LIST_PROMPTS = "prompts/list"
    GET_PROMPT = "prompts/get"

    RESOURCE_UPDATED = "notifications/resources/updated"
    TOOL_RESULT = "notifications/tools/result"

@dataclass
class MCPResource:
    uri: str
    name: str
    description: str
    mime_type: str = "application/json"

@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict

@dataclass
class MCPPrompt:
    name: str
    description: str
    arguments: List[Dict]

@dataclass
class MCPRequest:
    id: str
    method: str
    params: Dict = field(default_factory=dict)

@dataclass
class MCPResponse:
    id: str
    result: Optional[Any] = None
    error: Optional[Dict] = None

class MCPServer:
    SERVER_INFO = {
        "name": "axnmihn-mcp",
        "version": "1.0.0",
        "protocol_version": "2026-01-20",
        "capabilities": {
            "resources": {"listChanged": True},
            "tools": {},
            "prompts": {},
        }
    }

    def __init__(
        self,
        memory_manager=None,
        identity_manager=None,
        search_agent=None,
        graph_rag=None,
    ):
        self.memory = memory_manager
        self.identity = identity_manager
        self.search = search_agent
        self.graph = graph_rag

        self.resources: Dict[str, MCPResource] = {}
        self.resource_handlers: Dict[str, Callable] = {}

        self.tools: Dict[str, MCPTool] = {}
        self.tool_handlers: Dict[str, Callable] = {}

        self.prompts: Dict[str, MCPPrompt] = {}

        # PERF-032: Cache manifest
        self._cached_manifest: Optional[Dict] = None

        self._setup_resources()
        self._setup_tools()
        self._setup_prompts()

    def _setup_resources(self):
        self.register_resource(
            MCPResource(
                uri="axnmihn://memory/working",
                name="Working Memory",
                description="현재 대화 컨텍스트 (최근 8턴)",
                mime_type="text/plain"
            ),
            self._get_working_memory
        )

        self.register_resource(
            MCPResource(
                uri="axnmihn://memory/long_term",
                name="Long-term Memory",
                description="영구 저장된 사실, 인사이트, 선호도",
                mime_type="application/json"
            ),
            self._get_long_term_memory
        )

        self.register_resource(
            MCPResource(
                uri="axnmihn://persona",
                name="Current Persona",
                description="axnmihn의 현재 페르소나 및 성격",
                mime_type="application/json"
            ),
            self._get_persona
        )

        self.register_resource(
            MCPResource(
                uri="axnmihn://stats",
                name="System Stats",
                description="메모리 및 시스템 통계",
                mime_type="application/json"
            ),
            self._get_stats
        )

    def _setup_tools(self):
        self.register_tool(
            MCPTool(
                name="search",
                description="웹 또는 메모리에서 정보 검색",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "검색 쿼리"},
                        "source": {
                            "type": "string",
                            "enum": ["web", "memory", "both"],
                            "default": "both"
                        }
                    },
                    "required": ["query"]
                }
            ),
            self._tool_search
        )

        self.register_tool(
            MCPTool(
                name="remember",
                description="장기 메모리에 정보 저장",
                input_schema={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "저장할 내용"},
                        "type": {
                            "type": "string",
                            "enum": ["fact", "insight", "preference"],
                            "default": "fact"
                        },
                        "importance": {"type": "number", "default": 0.7}
                    },
                    "required": ["content"]
                }
            ),
            self._tool_remember
        )

        self.register_tool(
            MCPTool(
                name="query_graph",
                description="지식 그래프에서 관계 탐색",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "검색 쿼리"},
                        "max_depth": {"type": "integer", "default": 2}
                    },
                    "required": ["query"]
                }
            ),
            self._tool_query_graph
        )

    def _setup_prompts(self):
        self.prompts["axnmihn_style"] = MCPPrompt(
            name="axnmihn_style",
            description="axnmihn 스타일 응답 생성",
            arguments=[
                {"name": "message", "description": "응답할 메시지", "required": True}
            ]
        )

        self.prompts["memory_context"] = MCPPrompt(
            name="memory_context",
            description="메모리 컨텍스트 포함 프롬프트",
            arguments=[
                {"name": "query", "description": "사용자 쿼리", "required": True}
            ]
        )

    def register_resource(self, resource: MCPResource, handler: Callable):
        """Register resource and invalidate manifest cache."""
        self.resources[resource.uri] = resource
        self.resource_handlers[resource.uri] = handler
        self._cached_manifest = None  # PERF-032: Invalidate cache
        _log.debug("Resource reg", uri=resource.uri)

    def register_tool(self, tool: MCPTool, handler: Callable):
        """Register tool and invalidate manifest cache."""
        self.tools[tool.name] = tool
        self.tool_handlers[tool.name] = handler
        self._cached_manifest = None  # PERF-032: Invalidate cache
        _log.debug("Tool reg", name=tool.name)

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Handle MCP request."""
        # PERF-032: Use module-level time import
        start_time = time.time()
        _log.info("REQ handling", method=request.method, params=list(request.params.keys()) if request.params else [])

        try:
            method = request.method

            if method == "initialize":
                return MCPResponse(id=request.id, result=self.SERVER_INFO)

            elif method == "resources/list":
                resources = [
                    {
                        "uri": r.uri,
                        "name": r.name,
                        "description": r.description,
                        "mimeType": r.mime_type
                    }
                    for r in self.resources.values()
                ]
                return MCPResponse(id=request.id, result={"resources": resources})

            elif method == "resources/read":
                uri = request.params.get("uri")
                if uri not in self.resource_handlers:
                    return MCPResponse(
                        id=request.id,
                        error={"code": -32602, "message": f"Unknown resource: {uri}"}
                    )

                handler = self.resource_handlers[uri]
                if asyncio.iscoroutinefunction(handler):
                    content = await handler()
                else:
                    content = handler()

                return MCPResponse(id=request.id, result={"contents": [content]})

            elif method == "tools/list":
                tools = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.input_schema
                    }
                    for t in self.tools.values()
                ]
                return MCPResponse(id=request.id, result={"tools": tools})

            elif method == "tools/call":
                tool_name = request.params.get("name")
                arguments = request.params.get("arguments", {})

                if tool_name not in self.tool_handlers:
                    return MCPResponse(
                        id=request.id,
                        error={"code": -32602, "message": f"Unknown tool: {tool_name}"}
                    )

                handler = self.tool_handlers[tool_name]
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(**arguments)
                else:
                    result = handler(**arguments)

                dur_ms = int((time.time() - start_time) * 1000)
                _log.info("RES complete", tool=tool_name, dur_ms=dur_ms)
                return MCPResponse(id=request.id, result={"content": [{"type": "text", "text": str(result)}]})

            elif method == "prompts/list":
                prompts = [
                    {
                        "name": p.name,
                        "description": p.description,
                        "arguments": p.arguments
                    }
                    for p in self.prompts.values()
                ]
                return MCPResponse(id=request.id, result={"prompts": prompts})

            elif method == "prompts/get":
                prompt_name = request.params.get("name")
                if prompt_name not in self.prompts:
                    return MCPResponse(
                        id=request.id,
                        error={"code": -32602, "message": f"Unknown prompt: {prompt_name}"}
                    )

                messages = self._generate_prompt_messages(prompt_name, request.params.get("arguments", {}))
                return MCPResponse(id=request.id, result={"messages": messages})

            else:
                _log.warning("Unknown method", method=method)
                return MCPResponse(
                    id=request.id,
                    error={"code": -32601, "message": f"Method not found: {method}"}
                )

        except Exception as e:
            _log.error("REQ error", method=request.method, error=str(e))
            return MCPResponse(
                id=request.id,
                error={"code": -32603, "message": str(e)}
            )

    def _get_working_memory(self) -> Dict:
        if not self.memory:
            return {"uri": "axnmihn://memory/working", "text": "Memory not available"}

        context = self.memory.get_working_context()
        return {
            "uri": "axnmihn://memory/working",
            "mimeType": "text/plain",
            "text": context or "No current conversation"
        }

    def _get_long_term_memory(self) -> Dict:
        if not self.memory or not self.memory.long_term:
            return {"uri": "axnmihn://memory/long_term", "text": "{}"}

        stats = self.memory.long_term.get_stats()
        return {
            "uri": "axnmihn://memory/long_term",
            "mimeType": "application/json",
            "text": json.dumps(stats, ensure_ascii=False)
        }

    def _get_persona(self) -> Dict:
        if not self.identity:
            return {"uri": "axnmihn://persona", "text": "{}"}

        persona = {
            "name": "axnmihn",
            "traits": self.identity.get_traits() if hasattr(self.identity, 'get_traits') else [],
            "mood": self.identity.get_mood() if hasattr(self.identity, 'get_mood') else "neutral"
        }
        return {
            "uri": "axnmihn://persona",
            "mimeType": "application/json",
            "text": json.dumps(persona, ensure_ascii=False)
        }

    def _get_stats(self) -> Dict:
        stats = {}
        if self.memory:
            stats["memory"] = self.memory.get_stats()
        if self.graph:
            stats["graph"] = self.graph.get_stats()

        return {
            "uri": "axnmihn://stats",
            "mimeType": "application/json",
            "text": json.dumps(stats, ensure_ascii=False, default=str)
        }

    async def _tool_search(self, query: str, source: str = "both") -> str:
        """Search web and/or memory."""
        # PERF-032: Parallelize web and memory search
        tasks = []

        if source in ["web", "both"] and self.search:
            tasks.append(("web", self.search.search(query, max_results=3)))

        if source in ["memory", "both"] and self.memory and self.memory.long_term:
            async def get_memory():
                return self.memory.long_term.get_formatted_context(query, max_items=3)
            tasks.append(("memory", get_memory()))

        if not tasks:
            return "No results"

        results = []
        gathered = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

        for (label, _), result in zip(tasks, gathered):
            if not isinstance(result, Exception) and result:
                results.append(f"[{label.title()}]\n{result}")

        return "\n\n".join(results) if results else "No results"

    def _tool_remember(self, content: str, type: str = "fact", importance: float = 0.7) -> str:
        if not self.memory or not self.memory.long_term:
            return "Memory not available"

        doc_id = self.memory.long_term.add(
            content=content,
            memory_type=type,
            importance=importance,
            force=True
        )

        return f"Saved to long-term memory (ID: {doc_id})"

    async def _tool_query_graph(self, query: str, max_depth: int = 2) -> str:
        if not self.graph:
            return "Graph RAG not available"

        result = await self.graph.query(query, max_depth=max_depth)
        return result.context if result.context else "No graph results"

    def _generate_prompt_messages(self, prompt_name: str, arguments: Dict) -> List[Dict]:
        if prompt_name == "axnmihn_style":
            return [{
                "role": "user",
                "content": {
                    "type": "text",
                    "text": f"axnmihn 스타일로 응답해줘: {arguments.get('message', '')}"
                }
            }]

        elif prompt_name == "memory_context":
            query = arguments.get("query", "")
            context = ""
            if self.memory:
                context = self.memory.build_smart_context_sync(query)

            return [{
                "role": "user",
                "content": {
                    "type": "text",
                    "text": f"[Context]\n{context}\n\n[Query]\n{query}"
                }
            }]

        return []

    def get_manifest(self) -> Dict:
        """Get server manifest (cached after first call - PERF-032)."""
        if self._cached_manifest is not None:
            return self._cached_manifest

        self._cached_manifest = {
            "server": self.SERVER_INFO,
            "resources": [
                {
                    "uri": r.uri,
                    "name": r.name,
                    "description": r.description,
                    "mimeType": r.mime_type,
                }
                for r in self.resources.values()
            ],
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                }
                for t in self.tools.values()
            ],
            "prompts": [
                {
                    "name": p.name,
                    "description": p.description,
                    "arguments": p.arguments,
                }
                for p in self.prompts.values()
            ]
        }
        return self._cached_manifest

__all__ = [
    "MCPServer",
    "MCPRequest",
    "MCPResponse",
    "MCPResource",
    "MCPTool",
    "MCPPrompt",
]
