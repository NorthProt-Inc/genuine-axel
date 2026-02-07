import aiohttp
import os
import time
from typing import Any, Dict, List, Optional
from backend.core.logging import get_logger
from backend.config import MCP_MAX_TOOL_RETRIES, MCP_TOOL_RETRY_DELAY, MCP_MAX_TOOLS
from backend.core.utils.retry import RetryConfig, retry_async

_log = get_logger("core.mcp_client")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8555")

MCP_RETRY_CONFIG = RetryConfig(
    max_retries=MCP_MAX_TOOL_RETRIES,
    base_delay=MCP_TOOL_RETRY_DELAY,
    max_delay=30.0,
    jitter=0.3,
    retryable_patterns={
        "connection", "timeout", "busy", "port",
        "address already in use", "temporarily unavailable",
        "resource exhausted",
    },
)

CORE_TOOLS = [

    "run_command",
    "read_file",
    "list_directory",
    "delegate_to_opus",
    "retrieve_context",
    "store_memory",
    "tavily_search",
    "google_deep_research",
    "hass_control_light",
    "hass_control_device",
    "web_search",
    "visit_webpage",
    "deep_research",
]
MAX_TOOLS = MCP_MAX_TOOLS

class MCPClient:

    TOOLS_CACHE_TTL = 300

    def __init__(self, base_url: str = None):
        self.base_url = base_url or MCP_SERVER_URL
        self._gemini_tools_cache: Optional[List[dict]] = None
        self._cache_timestamp: float = 0
        self._anthropic_tools_cache: Optional[List[dict]] = None
        self._anthropic_cache_timestamp: float = 0

    async def call_tool(self, name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute an MCP tool with retry logic and fallback mechanisms.

        Uses retry_async for transient errors (connection, timeout, etc.).
        ImportError -> HTTP fallback, ValueError -> immediate error return.
        """
        arguments = arguments or {}

        async def _direct_call() -> Dict[str, Any]:
            from backend.core.mcp_server import call_tool as mcp_call_tool
            result = await mcp_call_tool(name, arguments)
            texts = [r.text for r in result if hasattr(r, "text")]
            return {"success": True, "result": "\n".join(texts)}

        try:
            return await retry_async(_direct_call, config=MCP_RETRY_CONFIG)

        except ImportError as e:
            _log.warning("MCP import failed, trying HTTP", tool=name, error=str(e))
            return await self.call_tool_http(name, arguments)

        except ValueError as e:
            _log.error("Tool not found", tool=name, error=str(e))
            return {"success": False, "error": f"Tool '{name}' not found: {str(e)}"}

        except Exception as e:
            _log.warning("Direct call exhausted, trying HTTP fallback", tool=name)
            http_result = await self.call_tool_http(name, arguments)
            if http_result.get("success"):
                return http_result
            return {
                "success": False,
                "error": f"Tool call failed after {MCP_RETRY_CONFIG.max_retries} retries: {str(e)}",
            }

    async def call_tool_http(self, name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute an MCP tool via HTTP fallback.

        Args:
            name: Tool name to execute
            arguments: Tool arguments dict

        Returns:
            Dict with success status and result or error message
        """
        arguments = arguments or {}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/mcp/execute",
                    json={
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments}
                    },
                    headers={"Content-Type": "application/json"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {"success": True, "result": data.get("result")}
                    else:
                        error = await resp.text()
                        return {"success": False, "error": f"HTTP {resp.status}: {error}"}
        except Exception as e:
            _log.error("MCP HTTP call failed", tool=name, error=str(e))
            return {"success": False, "error": str(e)}

    async def list_tools(self) -> list:
        """Retrieve available MCP tools with basic info.

        Returns:
            List of dicts with name and description for each tool
        """
        try:
            from backend.core.mcp_server import list_tools as mcp_list_tools
            tools = await mcp_list_tools()
            return [{"name": t.name, "description": t.description} for t in tools]
        except Exception as e:
            _log.error("MCP list_tools failed", error=str(e))
            return []

    async def get_tools_with_schemas(self) -> list:
        """Retrieve MCP tools with full input schemas.

        Returns:
            List of dicts with name, description, and input_schema
        """
        try:
            from backend.core.mcp_server import list_tools as mcp_list_tools
            tools = await mcp_list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.inputSchema
                }
                for t in tools
            ]
        except Exception as e:
            _log.error("MCP get_tools_with_schemas failed", error=str(e))
            return []

    async def get_gemini_tools(self, force_refresh: bool = False, max_tools: int = None) -> list:
        """Get MCP tools formatted for Gemini function calling.

        Converts tool schemas to Gemini-compatible format with caching.
        Prioritizes core tools over others when limiting count.

        Args:
            force_refresh: Bypass cache and refresh tools
            max_tools: Maximum number of tools to return

        Returns:
            List of Gemini-formatted function declarations
        """
        max_tools = max_tools or MAX_TOOLS

        now = time.time()
        if (not force_refresh
            and self._gemini_tools_cache is not None
            and (now - self._cache_timestamp) < self.TOOLS_CACHE_TTL):
            _log.debug("Using cached gemini tools", age_seconds=int(now - self._cache_timestamp))
            return self._gemini_tools_cache[:max_tools]

        _log.info("Refreshing gemini tools cache", max_tools=max_tools)
        tools = await self.get_tools_with_schemas()

        core_tools = [t for t in tools if t["name"] in CORE_TOOLS]
        other_tools = [t for t in tools if t["name"] not in CORE_TOOLS]
        prioritized_tools = core_tools + other_tools

        _log.info("Tool prioritization",
                    total=len(tools),
                    core=len(core_tools),
                    limited=min(max_tools, len(prioritized_tools)))

        gemini_functions = []

        for tool in prioritized_tools:
            schema = tool.get("input_schema", {})
            properties = schema.get("properties", {})
            required = schema.get("required", [])

            gemini_properties = {}
            for prop_name, prop_def in properties.items():
                gemini_prop = {
                    "type": prop_def.get("type", "string").upper(),
                    "description": prop_def.get("description", ""),
                }

                if "enum" in prop_def:
                    gemini_prop["enum"] = prop_def["enum"]
                gemini_properties[prop_name] = gemini_prop

            gemini_functions.append({
                "name": tool["name"],
                "description": tool["description"],
                "parameters": {
                    "type": "OBJECT",
                    "properties": gemini_properties,
                    "required": required,
                }
            })

        self._gemini_tools_cache = gemini_functions
        self._cache_timestamp = now
        _log.info("Gemini tools cache updated", tool_count=len(gemini_functions))

        return gemini_functions[:max_tools]

    async def get_anthropic_tools(self, force_refresh: bool = False, max_tools: int | None = None) -> list:
        """Get MCP tools formatted for Anthropic Claude API.

        Uses input_schema directly from MCP tool definitions.
        Prioritizes core tools over others when limiting count.

        Args:
            force_refresh: Bypass cache and refresh tools
            max_tools: Maximum number of tools to return

        Returns:
            List of Anthropic-formatted tool definitions
        """
        max_tools = max_tools or MAX_TOOLS

        now = time.time()
        if (not force_refresh
            and self._anthropic_tools_cache is not None
            and (now - self._anthropic_cache_timestamp) < self.TOOLS_CACHE_TTL):
            _log.debug("Using cached anthropic tools", age_seconds=int(now - self._anthropic_cache_timestamp))
            return self._anthropic_tools_cache[:max_tools]

        _log.info("Refreshing anthropic tools cache", max_tools=max_tools)
        tools = await self.get_tools_with_schemas()

        core_tools = [t for t in tools if t["name"] in CORE_TOOLS]
        other_tools = [t for t in tools if t["name"] not in CORE_TOOLS]
        prioritized_tools = core_tools + other_tools

        _log.info("Anthropic tool prioritization",
                   total=len(tools),
                   core=len(core_tools),
                   limited=min(max_tools, len(prioritized_tools)))

        anthropic_tools = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool.get("input_schema", {"type": "object", "properties": {}}),
            }
            for tool in prioritized_tools
        ]

        self._anthropic_tools_cache = anthropic_tools
        self._anthropic_cache_timestamp = now
        _log.info("Anthropic tools cache updated", tool_count=len(anthropic_tools))

        return anthropic_tools[:max_tools]

from backend.core.utils.lazy import Lazy

_client: Lazy[MCPClient] = Lazy(MCPClient)


def get_mcp_client() -> MCPClient:
    """Get the singleton MCP client instance."""
    return _client.get()
