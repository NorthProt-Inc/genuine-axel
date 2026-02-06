from typing import Any, Sequence
from mcp.types import TextContent
from . import register_tool
from backend.core.logging.logging import get_logger

_log = get_logger("mcp.opus_tools")

@register_tool(
    "delegate_to_opus",
    category="delegation",
    description="Delegate coding tasks to Claude Opus. Specify instruction and file paths.",
    input_schema={
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "Clear, detailed instruction for the coding task"
            },
            "file_paths": {
                "type": "string",
                "description": "Comma-separated file paths (e.g., 'core/main.py,core/utils.py')"
            },
            "model": {
                "type": "string",
                "enum": ["opus", "sonnet", "haiku"],
                "description": "Model to use: opus=best quality, sonnet=balanced, haiku=fast",
                "default": "opus"
            }
        },
        "required": ["instruction"]
    }
)
async def delegate_to_opus_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Delegate a coding task to Claude Opus via Silent Intern.

    Args:
        arguments: Dict with instruction, file_paths, and model

    Returns:
        TextContent with execution result or error
    """
    instruction = arguments.get("instruction", "")
    file_paths_raw = arguments.get("file_paths", "")
    model = arguments.get("model", "opus")
    _log.debug("TOOL invoke", fn="delegate_to_opus", model=model, instruction_len=len(instruction) if instruction else 0)

    if not instruction:
        _log.warning("TOOL fail", fn="delegate_to_opus", err="instruction parameter required")
        return [TextContent(type="text", text="Error: instruction parameter is required")]

    if model not in ["opus", "sonnet", "haiku"]:
        _log.warning("TOOL fail", fn="delegate_to_opus", err="invalid model")
        return [TextContent(type="text", text="Error: model must be 'opus', 'sonnet', or 'haiku'")]

    file_paths = [p.strip() for p in file_paths_raw.split(",") if p.strip()] if file_paths_raw else []

    try:
        from backend.core.tools.opus_executor import _generate_task_summary
        task_summary = _generate_task_summary(instruction)
    except ImportError:
        task_summary = instruction[:50] + "..." if len(instruction) > 50 else instruction

    try:
        from backend.core.tools.opus_executor import delegate_to_opus

        result = await delegate_to_opus(
            instruction=instruction,
            file_paths=file_paths,
            model=model
        )

        if result.success:
            _log.info("TOOL ok", fn="delegate_to_opus", model=model, time_s=result.execution_time, files=len(result.files_included))

            output_parts = ["Opus Task Completed", ""]
            if result.files_included:
                output_parts.append(f"**Context Files:** {', '.join(result.files_included)}")
            output_parts.append(f"**Execution Time:** {result.execution_time:.2f}s")
            output_parts.append("")
            output_parts.append("## Response")
            output_parts.append(result.response)
            return [TextContent(type="text", text="\n".join(output_parts))]
        else:
            _log.warning("TOOL partial", fn="delegate_to_opus", model=model, err=result.error[:100] if result.error else None)
            return [TextContent(type="text", text=f"Opus Error: {result.error}\n\n{result.response}")]

    except Exception as e:
        _log.error("TOOL fail", fn="delegate_to_opus", err=str(e)[:100])
        return [TextContent(type="text", text=f"Opus Error: {str(e)}")]

@register_tool(
    "google_deep_research",
    category="delegation",
    description="Premium research via Gemini API. Async by default, saves to storage/research/.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Research query - be specific and detailed for best results"
            },
            "depth": {
                "type": "integer",
                "description": "Research depth 1-5 (optional, default: 3). Higher = more thorough analysis.",
                "minimum": 1,
                "maximum": 5,
                "default": 3
            },
            "async_mode": {
                "type": "boolean",
                "description": "Run in background (default: true). Set false to wait for results.",
                "default": True
            }
        },
        "required": ["query"]
    }
)
async def google_deep_research_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Execute deep research using Google Gemini Interactions API.

    Args:
        arguments: Dict with query, depth, and async_mode

    Returns:
        TextContent with research results or async task confirmation
    """
    query = arguments.get("query", "")
    depth = arguments.get("depth", 3)
    async_mode = arguments.get("async_mode", True)
    _log.debug("TOOL invoke", fn="google_deep_research", query=query[:50] if query else None, depth=depth, async_mode=async_mode)

    if not query:
        _log.warning("TOOL fail", fn="google_deep_research", err="query parameter required")
        return [TextContent(type="text", text="Error: query parameter is required")]

    if depth is not None:
        if not isinstance(depth, int) or depth < 1 or depth > 5:
            _log.warning("TOOL fail", fn="google_deep_research", err="invalid depth")
            return [TextContent(type="text", text="Error: depth must be between 1 and 5")]

    try:
        if async_mode:
            from backend.protocols.mcp.async_research import dispatch_async_research
            result = dispatch_async_research(query, "google", depth)
            _log.info("TOOL ok", fn="google_deep_research", mode="async", res_len=len(result))
            return [TextContent(type="text", text=result)]
        else:
            from backend.protocols.mcp.async_research import run_research_sync
            result = await run_research_sync(query, "google", depth)
            _log.info("TOOL ok", fn="google_deep_research", mode="sync", res_len=len(result))
            return [TextContent(type="text", text=result)]

    except Exception as e:
        _log.error("TOOL fail", fn="google_deep_research", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Google Research Error: {str(e)}")]
