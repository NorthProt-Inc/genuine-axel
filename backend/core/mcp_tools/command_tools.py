"""Command execution tools for MCP.

This module provides tools for executing shell commands on the host system.
"""

import asyncio
import subprocess
from typing import Any, Sequence
from mcp.types import TextContent
from . import register_tool
from backend.config import PROJECT_ROOT as AXEL_ROOT
from backend.core.logging.logging import get_logger

_log = get_logger("mcp.command_tools")


@register_tool(
    "run_command",
    category="system",
    description="""Execute a shell command on the host system.

CAPABILITIES:
- Full bash shell access
- sudo available WITHOUT password (NOPASSWD configured)
- Can install packages, manage services, modify system files

COMMON USES:
- sudo systemctl restart/stop/start <service>
- sudo apt install <package>
- git operations
- File operations outside project directory
- Process management (ps, kill, etc.)

CAUTION: You have full system access. Be careful with destructive commands.""",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to execute (sudo available without password)"},
            "cwd": {"type": "string", "description": "Working directory (default: project root)"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default: 180)", "default": 180}
        },
        "required": ["command"]
    }
)
async def run_command(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Execute a shell command on the host system.

    Args:
        arguments: Dict with command, cwd, and timeout

    Returns:
        TextContent with stdout/stderr output
    """
    command = arguments.get("command", "")
    cwd = arguments.get("cwd", str(AXEL_ROOT))
    timeout = arguments.get("timeout", 120)
    _log.debug("TOOL invoke", fn="run_command", cmd=command[:80] if command else None, cwd=cwd[:40], timeout=timeout)

    if not command:
        _log.warning("TOOL fail", fn="run_command", err="command parameter required")
        return [TextContent(type="text", text="Error: command parameter is required")]

    if not isinstance(timeout, (int, float)) or timeout < 1 or timeout > 180:
        _log.warning("TOOL fail", fn="run_command", err="invalid timeout")
        return [TextContent(type="text", text="Error: timeout must be between 1 and 180 seconds")]

    try:

        result = await asyncio.to_thread(
            subprocess.run,
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=False,
            timeout=timeout
        )

        def safe_decode(data: bytes) -> str:
            modes = ["cp949", "utf-8", "latin-1"]
            for mode in modes:
                try:
                    return data.decode(mode)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="replace")

        stdout_str = safe_decode(result.stdout)
        stderr_str = safe_decode(result.stderr)

        output_parts = []
        if result.returncode == 0:
            _log.info("TOOL ok", fn="run_command", exit_code=0, stdout_len=len(stdout_str))
            output_parts.append("✓ Success (Exit: 0)")
        else:
            _log.warning("TOOL partial", fn="run_command", exit_code=result.returncode)
            output_parts.append(f"✗ Failed (Exit: {result.returncode})")

        if stdout_str.strip():
            output_parts.append(f"\n[Stdout]\n{stdout_str.strip()}")
        if stderr_str.strip():
            output_parts.append(f"\n[Stderr]\n{stderr_str.strip()}")

        return [TextContent(type="text", text="\n".join(output_parts))]

    except subprocess.TimeoutExpired:
        _log.warning("TOOL fail", fn="run_command", err="command timeout", timeout_sec=timeout)
        return [TextContent(type="text", text=f"✗ Timed out after {timeout}s")]
    except Exception as e:
        _log.error("TOOL fail", fn="run_command", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Execution Error: {str(e)}")]


__all__ = ["run_command"]
