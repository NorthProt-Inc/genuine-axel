import asyncio
import subprocess
from typing import Any, Dict, List, Optional

from backend.core.filters import strip_xml_tags
from backend.core.logging import get_logger
from backend.core.tools.opus_types import DelegationResult, OpusHealthStatus, OpusResult
from backend.core.utils.opus_file_validator import (
    AXEL_ROOT,
    OPUS_ALLOWED_EXTENSIONS as ALLOWED_EXTENSIONS,
    OPUS_MAX_FILE_SIZE as MAX_FILE_SIZE,
    OPUS_MAX_FILES as MAX_FILES,
    OPUS_MAX_TOTAL_CONTEXT as MAX_TOTAL_CONTEXT,
)
from backend.core.utils.opus_shared import (
    build_context_block,
    generate_task_summary,
    run_claude_cli,
    DEFAULT_MODEL,
    COMMAND_TIMEOUT,
)

logger = get_logger("opus-executor")


async def delegate_to_opus(
    instruction: str,
    file_paths: Optional[List[str]] = None,
    model: str = "opus",
) -> DelegationResult:
    """Delegate a coding task to Claude Opus via CLI.

    Args:
        instruction: The coding task instruction.
        file_paths: Optional list of file paths for context.
        model: Model name ('opus' or 'sonnet').

    Returns:
        DelegationResult with execution outcome.
    """
    file_paths = file_paths or []

    if model not in ("opus", "sonnet"):
        model = "opus"

    try:
        context, included_files, context_errors = build_context_block(file_paths)

        result = await run_claude_cli(
            instruction=instruction,
            context=context,
            model=model,
        )

        if result.success:
            response_parts = []
            if included_files:
                response_parts.append(f"Files included: {', '.join(included_files)}")
            if context_errors:
                response_parts.append(f"Warnings: {'; '.join(context_errors)}")
            cleaned_output = strip_xml_tags(result.output)
            response_parts.append(cleaned_output)

            return DelegationResult(
                success=True,
                response="\n\n".join(response_parts),
                files_included=included_files,
                execution_time=result.execution_time,
            )
        else:
            cleaned_output = strip_xml_tags(result.output) if result.output else ""
            return DelegationResult(
                success=False,
                response=cleaned_output,
                error=result.error,
                files_included=included_files,
                execution_time=result.execution_time,
            )

    except Exception as e:
        return DelegationResult(
            success=False,
            response="",
            error=f"Execution error: {str(e)}",
        )


async def check_opus_health(timeout: int = 10) -> OpusHealthStatus:
    """Check if the Claude CLI is available and working.

    Args:
        timeout: Timeout in seconds for the health check.

    Returns:
        OpusHealthStatus with availability info.
    """
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["claude", "--version"],
            capture_output=True,
            timeout=timeout,
        )

        if result.returncode == 0:
            version = result.stdout.decode("utf-8", errors="replace").strip()
            return OpusHealthStatus(
                available=True,
                message="Claude CLI available",
                version=version,
                details={
                    "default_model": DEFAULT_MODEL,
                    "timeout": COMMAND_TIMEOUT,
                    "max_context_kb": MAX_TOTAL_CONTEXT // 1024,
                    "working_directory": str(AXEL_ROOT),
                },
            )
        else:
            return OpusHealthStatus(
                available=False,
                message="Claude CLI returned error",
            )
    except FileNotFoundError:
        return OpusHealthStatus(
            available=False,
            message="Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
        )
    except Exception as e:
        return OpusHealthStatus(
            available=False,
            message=f"Health check failed: {str(e)}",
        )


async def list_opus_capabilities() -> Dict[str, Any]:
    """Return Opus delegation capabilities and limits.

    Returns:
        Dict with tools, limits, and supported extensions.
    """
    return {
        "tools": [
            {
                "name": "delegate_to_opus",
                "description": "Delegate complex coding tasks to Claude Opus",
                "parameters": {
                    "instruction": "The coding task instruction (required)",
                    "file_paths": "List of files to include as context (optional)",
                    "model": "Model to use: opus (default), sonnet (fallback). haiku not allowed.",
                },
            }
        ],
        "limits": {
            "max_files": MAX_FILES,
            "max_file_size_kb": MAX_FILE_SIZE // 1024,
            "max_total_context_kb": MAX_TOTAL_CONTEXT // 1024,
            "timeout_seconds": COMMAND_TIMEOUT,
        },
        "supported_extensions": list(ALLOWED_EXTENSIONS),
    }


def get_mcp_tool_definition() -> Dict[str, Any]:
    """Return the MCP tool definition schema for delegate_to_opus.

    Returns:
        Dict conforming to the MCP tool schema.
    """
    return {
        "name": "delegate_to_opus",
        "description": """Delegate complex coding tasks to Claude Opus (Worker AI).

PROJECT OUROBOROS: This tool enables Axel to orchestrate Claude Opus for
autonomous code generation. Use this for tasks that benefit from deep
reasoning and careful code generation.

IDEAL USE CASES:
- Complex refactoring across multiple files
- Writing comprehensive test suites
- Implementing new features with multiple components
- Debugging complex issues with full context
- Code review and improvement suggestions

WORKFLOW:
1. Provide a clear, detailed instruction
2. Include relevant file paths for context
3. Opus processes the task autonomously
4. Returns generated code/analysis

BEST PRACTICES:
- Be specific about requirements and constraints
- Include all relevant files for context
- Specify desired output format (code, analysis, etc.)
- For large tasks, break into smaller subtasks

EXAMPLE:
{
    "instruction": "Refactor the authentication module to use JWT tokens...",
    "file_paths": ["auth/handler.py", "auth/models.py", "config.py"]
}""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "Clear, detailed instruction for the coding task",
                },
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths (relative to project root) to include as context",
                    "default": [],
                },
                "model": {
                    "type": "string",
                    "enum": ["opus", "sonnet"],
                    "description": "Model to use. opus=best quality (default), sonnet=fallback. haiku not allowed.",
                    "default": "opus",
                },
            },
            "required": ["instruction"],
        },
    }


__all__ = [
    "delegate_to_opus",
    "check_opus_health",
    "list_opus_capabilities",
    "DelegationResult",
    "OpusHealthStatus",
    "OpusResult",
    "get_mcp_tool_definition",
    "generate_task_summary",
    "build_context_block",
    "AXEL_ROOT",
    "DEFAULT_MODEL",
    "COMMAND_TIMEOUT",
    "MAX_FILE_SIZE",
    "MAX_FILES",
    "MAX_TOTAL_CONTEXT",
    "ALLOWED_EXTENSIONS",
]
