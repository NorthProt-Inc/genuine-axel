import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence

_AXEL_ROOT_TEMP = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(_AXEL_ROOT_TEMP))

from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.types as types

from backend.core.logging import get_logger
from backend.core.tools.opus_types import OpusResult
from backend.core.utils.opus_file_validator import (
    AXEL_ROOT,
    OPUS_ALLOWED_EXTENSIONS as ALLOWED_EXTENSIONS,
    OPUS_MAX_FILE_SIZE as MAX_FILE_SIZE,
    OPUS_MAX_FILES as MAX_FILES,
    OPUS_MAX_TOTAL_CONTEXT as MAX_TOTAL_CONTEXT,
    validate_opus_file_path as _validate_file_path,
    read_opus_file_content as _read_file_content,
)

logger = get_logger("opus-bridge")

DEFAULT_MODEL = "opus"

COMMAND_TIMEOUT = 600

def _build_context_block(file_paths: List[str]) -> tuple[str, List[str], List[str]]:

    if not file_paths:
        return "", [], []

    context_parts = []
    included = []
    errors = []
    total_size = 0

    for file_path in file_paths[:MAX_FILES]:
        is_valid, resolved, error = _validate_file_path(file_path)

        if not is_valid:
            errors.append(error)
            continue

        content = _read_file_content(resolved)
        content_size = len(content.encode('utf-8'))

        if total_size + content_size > MAX_TOTAL_CONTEXT:
            errors.append(f"Context limit reached, skipping: {file_path}")
            continue

        relative_path = str(resolved.relative_to(AXEL_ROOT))
        context_parts.append(f"### File: {relative_path}\n```\n{content}\n```\n")
        included.append(relative_path)
        total_size += content_size

    if len(file_paths) > MAX_FILES:
        errors.append(f"Too many files ({len(file_paths)}), limited to {MAX_FILES}")

    context_string = "\n".join(context_parts) if context_parts else ""
    return context_string, included, errors

def _safe_decode(data: bytes) -> str:

    for encoding in ["utf-8", "cp949", "latin-1"]:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")

def _generate_task_summary(instruction: str, max_length: int = 60) -> str:

    action_patterns = [
        (r'\b(refactor|rewrite)\b', 'Refactoring'),
        (r'\b(add|implement|create)\b', 'Implementing'),
        (r'\b(fix|debug|resolve)\b', 'Fixing'),
        (r'\b(update|modify|change)\b', 'Updating'),
        (r'\b(review|analyze)\b', 'Analyzing'),
        (r'\b(test|write test)\b', 'Writing tests for'),
        (r'\b(document|docstring)\b', 'Documenting'),
        (r'\b(optimize|improve)\b', 'Optimizing'),
    ]

    import re

    instruction_lower = instruction.lower()
    action_prefix = "Processing"

    for pattern, action in action_patterns:
        if re.search(pattern, instruction_lower):
            action_prefix = action
            break

    file_match = re.search(r'([a-zA-Z_][a-zA-Z0-9_/]*\.py)', instruction)
    func_match = re.search(r'(?:function|method|class)\s+[`"]?(\w+)[`"]?', instruction_lower)
    module_match = re.search(r'(?:module|component|system)\s+[`"]?(\w+)[`"]?', instruction_lower)

    subject = ""
    if file_match:
        subject = file_match.group(1)
    elif func_match:
        subject = f"`{func_match.group(1)}`"
    elif module_match:
        subject = f"{module_match.group(1)} module"
    else:

        first_line = instruction.split('\n')[0][:50].strip()
        if len(first_line) > 40:
            first_line = first_line[:37] + "..."
        subject = first_line

    summary = f"{action_prefix} {subject}"

    if len(summary) > max_length:
        summary = summary[:max_length-3] + "..."

    return summary

async def _run_claude_cli(
    instruction: str,
    context: str = "",
    model: str = DEFAULT_MODEL,
    timeout: int = COMMAND_TIMEOUT,
    _is_fallback: bool = False
) -> OpusResult:

    import time
    start_time = time.time()

    if model not in ("opus", "sonnet"):
        logger.warning(f"Model '{model}' not allowed, forcing opus")
        model = "opus"

    if context:
        full_prompt = f"""## Context Files

{context}

## Task

{instruction}"""
    else:
        full_prompt = instruction

    CLAUDE_CLI = os.path.expanduser("~/.local/bin/claude")
    command = [
        CLAUDE_CLI,
        "--print",
        "--dangerously-skip-permissions",
        "--model", model,
        "-",
    ]

    task_summary = _generate_task_summary(instruction)

    logger.info(
        f"🐍 [Opus] Executing: {task_summary}",
        model=model,
        prompt_chars=len(full_prompt),
        has_context=bool(context),
    )

    try:

        env = {**os.environ, "TERM": "dumb"}

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(AXEL_ROOT),
            env=env,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=full_prompt.encode('utf-8')),
                timeout=timeout
            )
        except asyncio.TimeoutError:

            process.kill()
            await process.wait()
            execution_time = time.time() - start_time
            logger.error(f"[Opus] Task timed out after {timeout}s: {task_summary}")
            return OpusResult(
                success=False,
                output="",
                error=f"Command timed out after {timeout} seconds",
                exit_code=-1,
                execution_time=execution_time
            )

        stdout = _safe_decode(stdout_bytes)
        stderr = _safe_decode(stderr_bytes)
        returncode = process.returncode

        execution_time = time.time() - start_time

        if returncode == 0:
            logger.info(
                f"✅ [Opus] Complete: {task_summary}",
                time=f"{execution_time:.1f}s",
                output_chars=len(stdout),
            )
            return OpusResult(
                success=True,
                output=stdout,
                exit_code=returncode,
                execution_time=execution_time
            )
        else:
            logger.warning(
                f"❌ [Opus] Failed: {task_summary}",
                exit_code=returncode,
                stderr_preview=stderr[:200] if stderr else None,
            )

            if model == "opus" and not _is_fallback:
                logger.info(f"🔄 [Opus] Retrying with sonnet: {task_summary}")
                return await _run_claude_cli(
                    instruction=instruction,
                    context=context,
                    model="sonnet",
                    timeout=timeout,
                    _is_fallback=True
                )

            return OpusResult(
                success=False,
                output=stdout,
                error=stderr or f"Command exited with code {returncode}",
                exit_code=returncode,
                execution_time=execution_time
            )

    except FileNotFoundError:
        logger.error("[Opus] CLI not found - ensure claude is installed")
        return OpusResult(
            success=False,
            output="",
            error="claude CLI not found. Install it with: npm install -g @anthropic-ai/claude-code",
            exit_code=-1
        )

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"[Opus] Error: {e}", exc_info=True)
        return OpusResult(
            success=False,
            output="",
            error=str(e),
            exit_code=-1,
            execution_time=execution_time
        )

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
                        "description": "Clear, detailed instruction for the coding task"
                    },
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths (relative to project root) to include as context",
                        "default": []
                    },
                    "model": {
                        "type": "string",
                        "enum": ["opus", "sonnet"],
                        "description": "Model to use (default: opus, fallback: sonnet)",
                        "default": "opus"
                    }
                },
                "required": ["instruction"]
            }
        ),
        Tool(
            name="opus_health_check",
            description="""Check if the Claude CLI is available and working.

Returns the version and status of the claude CLI tool.
Use this to verify the Opus bridge is properly configured.""",
            inputSchema={
                "type": "object",
                "properties": {},
            }
        ),
    ]

@opus_server.call_tool()
async def call_tool(name: str, arguments: dict) -> Sequence[types.TextContent]:

    logger.info(f"Tool called: {name}", args=str(arguments)[:200])

    try:
        if name == "run_opus_task":
            instruction = arguments.get("instruction", "")
            file_paths = arguments.get("file_paths", [])
            model = arguments.get("model", DEFAULT_MODEL)

            if not instruction:
                return [TextContent(type="text", text="Error: instruction is required")]

            context, included_files, context_errors = _build_context_block(file_paths)

            result = await _run_claude_cli(
                instruction=instruction,
                context=context,
                model=model
            )

            result.files_included = included_files

            output_parts = []

            if included_files:
                output_parts.append(f"## Context Files Included ({len(included_files)})")
                for f in included_files:
                    output_parts.append(f"- {f}")
                output_parts.append("")

            if context_errors:
                output_parts.append("## Context Warnings")
                for err in context_errors:
                    output_parts.append(f"- {err}")
                output_parts.append("")

            if result.success:
                output_parts.append("## Opus Response")
                output_parts.append(result.output)
            else:
                output_parts.append("## Error")
                output_parts.append(result.error or "Unknown error")
                if result.output:
                    output_parts.append("\n## Partial Output")
                    output_parts.append(result.output)

            output_parts.append(f"\n---\n*Execution time: {result.execution_time:.2f}s | Exit code: {result.exit_code}*")

            return [TextContent(type="text", text="\n".join(output_parts))]

        elif name == "opus_health_check":

            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["claude", "--version"],
                    capture_output=True,
                    timeout=10,
                )

                if result.returncode == 0:
                    version = _safe_decode(result.stdout).strip()
                    return [TextContent(
                        type="text",
                        text=f"## Opus Bridge Status: Healthy\n\n"
                             f"**Claude CLI Version:** {version}\n"
                             f"**Default Model:** {DEFAULT_MODEL}\n"
                             f"**Timeout:** {COMMAND_TIMEOUT}s\n"
                             f"**Max Context:** {MAX_TOTAL_CONTEXT // 1024}KB\n"
                             f"**Working Directory:** {AXEL_ROOT}"
                    )]
                else:
                    stderr = _safe_decode(result.stderr)
                    return [TextContent(
                        type="text",
                        text=f"## Opus Bridge Status: Error\n\n"
                             f"Claude CLI returned error:\n{stderr}"
                    )]

            except FileNotFoundError:
                return [TextContent(
                    type="text",
                    text="## Opus Bridge Status: Not Available\n\n"
                         "Claude CLI is not installed or not in PATH.\n\n"
                         "Install with: `npm install -g @anthropic-ai/claude-code`"
                )]

            except Exception as e:
                return [TextContent(
                    type="text",
                    text=f"## Opus Bridge Status: Error\n\n{str(e)}"
                )]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error(f"Tool {name} failed: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Tool execution failed: {str(e)}")]

async def run_stdio():

    from mcp.server.stdio import stdio_server

    logger.info("Starting Opus Bridge in stdio mode")

    async with stdio_server() as (read_stream, write_stream):
        await opus_server.run(
            read_stream,
            write_stream,
            opus_server.create_initialization_options()
        )

async def run_sse(host: str = "0.0.0.0", port: int = 8766):

    from fastapi import FastAPI, Request
    from sse_starlette.sse import EventSourceResponse
    from mcp.server.sse import SseServerTransport
    import uvicorn

    app = FastAPI(title="Opus Bridge MCP Server")
    sse = SseServerTransport("/messages/")

    @app.get("/sse")
    async def handle_sse(request: Request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await opus_server.run(
                streams[0],
                streams[1],
                opus_server.create_initialization_options()
            )

    @app.post("/messages/")
    async def handle_messages(request: Request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    @app.get("/health")
    async def health():
        return {"status": "healthy", "server": "opus-bridge"}

    logger.info(f"Starting Opus Bridge in SSE mode on {host}:{port}")

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
        help="Server mode (default: stdio)"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for SSE mode (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8766,
        help="Port for SSE mode (default: 8766)"
    )

    args = parser.parse_args()

    try:
        if args.mode == "stdio":
            asyncio.run(run_stdio())
        else:
            asyncio.run(run_sse(host=args.host, port=args.port))
    except KeyboardInterrupt:
        logger.info("Opus Bridge shutting down")

if __name__ == "__main__":
    main()
