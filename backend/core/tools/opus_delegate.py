import asyncio
from typing import Any, Dict, List, Optional
import aiohttp

from backend.core.tools.opus_types import DelegationResult, OpusHealthStatus

OPUS_BRIDGE_TIMEOUT = 660


async def _call_opus_direct(
    instruction: str,
    file_paths: List[str],
    model: str = "opus"
) -> DelegationResult:

    try:

        from backend.protocols.mcp.opus_bridge import _run_claude_cli, _build_context_block

        context, included_files, context_errors = _build_context_block(file_paths)

        result = await _run_claude_cli(
            instruction=instruction,
            context=context,
            model=model
        )

        if result.success:
            response_parts = []
            if included_files:
                response_parts.append(f"Files included: {', '.join(included_files)}")
            if context_errors:
                response_parts.append(f"Warnings: {'; '.join(context_errors)}")
            response_parts.append(result.output)

            return DelegationResult(
                success=True,
                response="\n\n".join(response_parts),
                files_included=included_files,
                execution_time=result.execution_time
            )
        else:
            return DelegationResult(
                success=False,
                response=result.output or "",
                error=result.error,
                files_included=included_files,
                execution_time=result.execution_time
            )

    except ImportError as e:
        return DelegationResult(
            success=False,
            response="",
            error=f"Failed to import opus_bridge: {str(e)}"
        )
    except Exception as e:
        return DelegationResult(
            success=False,
            response="",
            error=f"Execution error: {str(e)}"
        )

async def delegate_to_opus(
    instruction: str,
    file_paths: Optional[List[str]] = None,
    model: str = "opus",
) -> DelegationResult:

    file_paths = file_paths or []

    if model not in ("opus", "sonnet"):
        model = "opus"

    return await _call_opus_direct(
        instruction=instruction,
        file_paths=file_paths,
        model=model
    )

async def check_opus_health(timeout: int = 10) -> OpusHealthStatus:

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://localhost:8766/health",
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return OpusHealthStatus(
                        available=True,
                        message="Opus Bridge server is healthy",
                        details=data
                    )
                else:
                    return OpusHealthStatus(
                        available=False,
                        message=f"Server returned status {response.status}"
                    )
    except aiohttp.ClientError:
        pass
    except asyncio.TimeoutError:
        pass

    try:
        import subprocess
        result = await asyncio.to_thread(
            subprocess.run,
            ["claude", "--version"],
            capture_output=True,
            timeout=timeout
        )

        if result.returncode == 0:
            version = result.stdout.decode('utf-8', errors='replace').strip()
            return OpusHealthStatus(
                available=True,
                message="Claude CLI available (server not running, using direct mode)",
                version=version
            )
        else:
            return OpusHealthStatus(
                available=False,
                message="Claude CLI returned error"
            )
    except FileNotFoundError:
        return OpusHealthStatus(
            available=False,
            message="Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
        )
    except Exception as e:
        return OpusHealthStatus(
            available=False,
            message=f"Health check failed: {str(e)}"
        )

async def list_opus_capabilities() -> Dict[str, Any]:

    return {
        "tools": [
            {
                "name": "delegate_to_opus",
                "description": "Delegate complex coding tasks to Claude Opus",
                "parameters": {
                    "instruction": "The coding task instruction (required)",
                    "file_paths": "List of files to include as context (optional)",
                    "model": "Model to use: opus (default), sonnet (fallback). haiku not allowed."
                }
            }
        ],
        "limits": {
            "max_files": 20,
            "max_file_size_kb": 500,
            "max_total_context_kb": 1024,
            "timeout_seconds": 600
        },
        "supported_extensions": [
            ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
            ".md", ".txt", ".html", ".css", ".scss", ".sql", ".sh"
        ]
    }

def get_mcp_tool_definition() -> Dict[str, Any]:

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
                    "description": "Clear, detailed instruction for the coding task"
                },
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths (relative to project root) to include as context",
                    "default": []
                },
                "model": {
                    "type": "string",
                    "enum": ["opus", "sonnet"],
                    "description": "Model to use. opus=best quality (default), sonnet=fallback. haiku not allowed.",
                    "default": "opus"
                }
            },
            "required": ["instruction"]
        }
    }

__all__ = [
    "delegate_to_opus",
    "check_opus_health",
    "list_opus_capabilities",
    "DelegationResult",
    "OpusHealthStatus",
    "get_mcp_tool_definition",
]
