"""
Tool execution service for ChatHandler.

Handles MCP tool calls and deferred tool execution.
"""

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Tuple, Dict, Any, Optional

from backend.core.logging import get_logger

if TYPE_CHECKING:
    from backend.core.mcp_client import MCPClient

_log = get_logger("services.tool")


@dataclass
class ToolResult:
    """Result from a tool execution."""
    name: str
    output: str
    success: bool
    error: Optional[str] = None


@dataclass
class ToolExecutionResult:
    """Combined result from executing multiple tools."""
    results: List[ToolResult] = field(default_factory=list)
    deferred_tools: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    observation: str = ""


class ToolExecutionService:
    """Service for executing MCP tools."""

    FIRE_AND_FORGET_TOOLS = frozenset({
        "store_memory",
        "add_memory",
    })

    def __init__(self, mcp_client: Optional['MCPClient'] = None):
        """Initialize tool service.

        Args:
            mcp_client: MCP client for tool execution
        """
        self.mcp_client = mcp_client

    def is_fire_and_forget(self, tool_name: str) -> bool:
        """Check if a tool should be executed in background."""
        return tool_name in self.FIRE_AND_FORGET_TOOLS

    async def execute_tools(
        self,
        function_calls: List[Dict[str, Any]],
        event_callback: Optional[Any] = None
    ) -> ToolExecutionResult:
        """
        Execute a list of tool calls.

        Args:
            function_calls: List of function call dicts with name and args
            event_callback: Optional async callback for tool events

        Returns:
            ToolExecutionResult with results and deferred tools
        """
        if not self.mcp_client:
            _log.error("No MCP client available for tool execution")
            return ToolExecutionResult()

        results = []
        deferred_tools = []
        tool_outputs = []

        for fc in function_calls:
            tool_name = fc["name"]
            tool_args = fc.get("args", {})

            # Check if fire-and-forget
            if self.is_fire_and_forget(tool_name):
                deferred_tools.append((tool_name, tool_args))
                tool_outputs.append(f"✓ {tool_name}: (queued for background execution)")
                results.append(ToolResult(
                    name=tool_name,
                    output="(deferred)",
                    success=True
                ))
                _log.debug("TOOL deferred", name=tool_name)
                continue

            # Execute tool
            try:
                result = await self.mcp_client.call_tool(tool_name, tool_args)
                success = result.get("success", False)
                output_text = result.get("result", "")

                log_msg = f" {tool_name}: {output_text}"
                tool_outputs.append(log_msg)
                results.append(ToolResult(
                    name=tool_name,
                    output=output_text,
                    success=success
                ))
                _log.info("TOOL exec", name=tool_name, success=success)

            except Exception as e:
                error_msg = f" {tool_name} Error: {str(e)}"
                tool_outputs.append(error_msg)
                results.append(ToolResult(
                    name=tool_name,
                    output="",
                    success=False,
                    error=str(e)
                ))
                _log.error("TOOL fail", name=tool_name, error=str(e))

        # Build observation string
        observation = "\n".join(tool_outputs) if tool_outputs else ""

        return ToolExecutionResult(
            results=results,
            deferred_tools=deferred_tools,
            observation=observation
        )

    async def execute_deferred_tools(
        self,
        tools: List[Tuple[str, Dict[str, Any]]]
    ) -> None:
        """
        Execute deferred (fire-and-forget) tools.

        Args:
            tools: List of (tool_name, tool_args) tuples
        """
        if not self.mcp_client:
            _log.warning("No MCP client for deferred tools")
            return

        for tool_name, tool_args in tools:
            try:
                result = await self.mcp_client.call_tool(tool_name, tool_args)
                success = result.get("success", False)
                if success:
                    _log.info("BG TOOL ok", name=tool_name)
                else:
                    _log.warning(
                        "BG TOOL fail",
                        name=tool_name,
                        error=result.get("error", "unknown")[:100]
                    )
            except Exception as e:
                _log.warning("BG TOOL error", name=tool_name, error=str(e)[:100])

    def spawn_deferred_task(
        self,
        tools: List[Tuple[str, Dict[str, Any]]],
        background_tasks: List,
        done_callback: Optional[Any] = None
    ) -> Optional[asyncio.Task]:
        """
        Spawn a background task for deferred tool execution.

        Args:
            tools: List of deferred tools
            background_tasks: List to track background tasks
            done_callback: Optional callback when task completes

        Returns:
            Created asyncio.Task or None
        """
        if not tools:
            return None

        task = asyncio.create_task(self.execute_deferred_tools(tools))

        if isinstance(background_tasks, list):
            background_tasks.append(task)

        def _done(t: asyncio.Task):
            if isinstance(background_tasks, list):
                try:
                    background_tasks.remove(t)
                except ValueError:
                    pass
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                _log.warning("BG deferred tools fail", error=str(exc))
            if done_callback:
                done_callback(t)

        task.add_done_callback(_done)
        return task
