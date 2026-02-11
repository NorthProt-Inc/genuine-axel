import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Sequence

_AXEL_ROOT_TEMP = Path(__file__).parent.parent.parent.parent.resolve()
# PERF-041: Check before inserting to avoid duplicates
if str(_AXEL_ROOT_TEMP) not in sys.path:
    sys.path.insert(0, str(_AXEL_ROOT_TEMP))

from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.types as types

from backend.core.filters import strip_xml_tags
from backend.core.logging import get_logger
from backend.core.utils.opus_shared import (
    build_context_block,
    run_claude_cli,
    safe_decode,
    DEFAULT_MODEL,
)

_log = get_logger("opus-bridge")

opus_server = Server("opus-bridge")


@opus_server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="run_opus_task",
            description="""Execute a coding task using Claude Opus via CLI.

This tool delegates complex coding tasks to Claude Opus, providing it with
file context and returning the generated code/response.

USE CASES:
- Complex code generation requiring deep reasoning
- Refactoring tasks with multiple files
- Debugging with full codebase context
- Writing tests for existing code
- Documentation generation

WORKFLOW:
1. Provide clear instruction describing the task
2. Optionally include relevant file paths for context
3. Opus processes the task and returns the result

IMPORTANT:
- File paths should be relative to project root
- Large files (>500KB) will be skipped
- Maximum 20 files per request
- Total context limited to 1MB

EXAMPLE:
{
    "instruction": "Add error handling to the process_data function",
    "file_paths": ["core/data_processor.py", "core/utils.py"]
}""",
            inputSchema={
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "Clear, detailed instruction for the coding task",
                    },
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths (relative to project root) to include as context",
                        "default": [],
                    },
                    "model": {
                        "type": "string",
                        "enum": ["opus", "sonnet"],
                        "description": "Model to use (default: opus, fallback: sonnet)",
                        "default": "opus",
                    },
                },
                "required": ["instruction"],
            },
        ),
        Tool(
            name="opus_health_check",
            description="""Check if the Claude CLI is available and working.

Returns the version and status of the claude CLI tool.
Use this to verify the Opus bridge is properly configured.""",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@opus_server.call_tool()
async def call_tool(name: str, arguments: dict) -> Sequence[types.TextContent]:
    _log.info(f"Tool called: {name}", args=str(arguments)[:200])

    try:
        if name == "run_opus_task":
            instruction = arguments.get("instruction", "")
            file_paths = arguments.get("file_paths", [])
            model = arguments.get("model", DEFAULT_MODEL)

            if not instruction:
                return [TextContent(type="text", text="Error: instruction is required")]

            context, included_files, context_errors = build_context_block(file_paths)

            result = await run_claude_cli(
                instruction=instruction,
                context=context,
                model=model,
            )

            result.files_included = included_files

            output_parts = []

            if context_errors:
                for err in context_errors:
                    output_parts.append(f"⚠ {err}")
                output_parts.append("")

            if result.success:
                cleaned = strip_xml_tags(result.output)
                output_parts.append(cleaned)
            else:
                output_parts.append(f"Error: {result.error or 'Unknown error'}")
                if result.output:
                    cleaned = strip_xml_tags(result.output)
                    output_parts.append(f"\nPartial output:\n{cleaned}")

            return [TextContent(type="text", text="\n".join(output_parts))]

        elif name == "opus_health_check":
            try:
                proc_result = await asyncio.to_thread(
                    subprocess.run,
                    ["claude", "--version"],
                    capture_output=True,
                    timeout=10,
                )

                if proc_result.returncode == 0:
                    version = safe_decode(proc_result.stdout).strip()
                    return [
                        TextContent(
                            type="text",
                            text=f"Healthy - Claude CLI {version}, model={DEFAULT_MODEL}",
                        )
                    ]
                else:
                    stderr = safe_decode(proc_result.stderr)
                    return [TextContent(type="text", text=f"Error: {stderr}")]

            except FileNotFoundError:
                return [
                    TextContent(
                        type="text",
                        text="Not available - Claude CLI not installed",
                    )
                ]

            except Exception as e:
                return [TextContent(type="text", text=f"Error: {str(e)}")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        _log.error(f"Tool {name} failed: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Tool execution failed: {str(e)}")]


async def run_stdio():
    from mcp.server.stdio import stdio_server

    _log.info("Starting Opus Bridge in stdio mode")

    async with stdio_server() as (read_stream, write_stream):
        await opus_server.run(
            read_stream,
            write_stream,
            opus_server.create_initialization_options(),
        )


async def run_sse(host: str = "0.0.0.0", port: int = 8766):
    from fastapi import FastAPI, Request
    from mcp.server.sse import SseServerTransport
    import uvicorn

    app = FastAPI(title="Opus Bridge MCP Server")
    sse = SseServerTransport("/messages/")

    @app.get("/sse")
    async def handle_sse(request: Request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await opus_server.run(
                streams[0],
                streams[1],
                opus_server.create_initialization_options(),
            )

    @app.post("/messages/")
    async def handle_messages(request: Request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    @app.get("/health")
    async def health():
        return {"status": "healthy", "server": "opus-bridge"}

    _log.info(f"Starting Opus Bridge in SSE mode on {host}:{port}")

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Opus Bridge MCP Server")
    parser.add_argument(
        "mode",
        nargs="?",
        default="stdio",
        choices=["stdio", "sse"],
        help="Server mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for SSE mode (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8766,
        help="Port for SSE mode (default: 8766)",
    )

    args = parser.parse_args()

    try:
        if args.mode == "stdio":
            asyncio.run(run_stdio())
        else:
            asyncio.run(run_sse(host=args.host, port=args.port))
    except KeyboardInterrupt:
        _log.info("Opus Bridge shutting down")


if __name__ == "__main__":
    main()
