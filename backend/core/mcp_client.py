import aiohttp
import asyncio
import os
import time
from typing import Any, Dict, List, Optional
from backend.core.logging import get_logger

_log = get_logger("core.mcp_client")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8555")

# Retry configuration for resilient tool calls
MAX_TOOL_RETRIES = 3
TOOL_RETRY_DELAY = 0.5

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
]
MAX_TOOLS = 10

class MCPClient:

    TOOLS_CACHE_TTL = 300

    def __init__(self, base_url: str = None):
        self.base_url = base_url or MCP_SERVER_URL
        self._gemini_tools_cache: Optional[List[dict]] = None
        self._cache_timestamp: float = 0

    async def call_tool(self, name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute an MCP tool with retry logic and fallback mechanisms.

        This method ensures tool calls are always executed reliably, even during
        transient failures (e.g., port conflicts, temporary unavailability).
        """
        arguments = arguments or {}
        last_error = None

        for attempt in range(1, MAX_TOOL_RETRIES + 1):
            try:
                # Primary path: direct import call (fastest, no network overhead)
                from backend.core.mcp_server import call_tool as mcp_call_tool
                result = await mcp_call_tool(name, arguments)

                texts = []
                for r in result:
                    if hasattr(r, 'text'):
                        texts.append(r.text)

                _log.debug("TOOL exec success", tool=name, attempt=attempt)
                return {"success": True, "result": "\n".join(texts)}

            except ImportError as e:
                # MCP server module not available, try HTTP fallback
                _log.warning("MCP import failed, trying HTTP", tool=name, error=str(e))
                return await self.call_tool_http(name, arguments)

            except ValueError as e:
                # Tool not found - don't retry, it won't suddenly appear
                _log.error("Tool not found", tool=name, error=str(e))
                return {"success": False, "error": f"Tool '{name}' not found: {str(e)}"}

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Check if error is retryable
                is_retryable = any(x in error_str for x in [
                    'connection', 'timeout', 'busy', 'port', 'address already in use',
                    'temporarily unavailable', 'resource exhausted'
                ])

                if is_retryable and attempt < MAX_TOOL_RETRIES:
                    delay = TOOL_RETRY_DELAY * (2 ** (attempt - 1))
                    _log.warning("Tool call failed, retrying",
                                tool=name,
                                attempt=attempt,
                                delay_s=delay,
                                error=str(e)[:100])
                    await asyncio.sleep(delay)
                    continue

                # Non-retryable error or retries exhausted
                _log.error("MCP tool call failed",
                          tool=name,
                          attempt=attempt,
                          error=str(e)[:200])
                break

        # All retries failed, try HTTP as last resort
        _log.warning("Direct call exhausted, trying HTTP fallback", tool=name)
        http_result = await self.call_tool_http(name, arguments)

        if http_result.get("success"):
            return http_result

        # Both methods failed
        return {
            "success": False,
            "error": f"Tool call failed after {MAX_TOOL_RETRIES} retries: {str(last_error)}"
        }

    async def call_tool_http(self, name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:

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

        try:
            from backend.core.mcp_server import list_tools as mcp_list_tools
            tools = await mcp_list_tools()
            return [{"name": t.name, "description": t.description} for t in tools]
        except Exception as e:
            _log.error("MCP list_tools failed", error=str(e))
            return []

    async def get_tools_with_schemas(self) -> list:

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
        limited_tools = prioritized_tools[:max_tools]

        _log.info("Tool prioritization",
                    total=len(tools),
                    core=len(core_tools),
                    limited=len(limited_tools))

        gemini_functions = []

        for tool in limited_tools:
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

        return gemini_functions

_client: Optional[MCPClient] = None

def get_mcp_client() -> MCPClient:

    global _client
    if _client is None:
        _client = MCPClient()
    return _client
