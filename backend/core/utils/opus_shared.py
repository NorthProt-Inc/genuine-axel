"""Shared Opus CLI delegation utilities.

Pure and async functions used by both opus_executor (internal API)
and opus_bridge (standalone MCP server). Single source of truth
for context building, encoding, task summarization, and CLI execution.
"""

import asyncio
import os
import re
import time
from typing import List

from backend.core.logging import get_logger
from backend.core.tools.opus_types import OpusResult
from backend.core.utils.opus_file_validator import (
    AXEL_ROOT,
    OPUS_MAX_FILES as MAX_FILES,
    OPUS_MAX_TOTAL_CONTEXT as MAX_TOTAL_CONTEXT,
    validate_opus_file_path as _validate_file_path,
    read_opus_file_content as _read_file_content,
)

_log = get_logger("opus-shared")

# Read directly from env to avoid circular import (backend.config → backend.core → here)
DEFAULT_MODEL: str = os.getenv("OPUS_DEFAULT_MODEL", "opus")
COMMAND_TIMEOUT: int = int(os.getenv("OPUS_COMMAND_TIMEOUT", "600"))

_ACTION_PATTERNS: list[tuple[str, str]] = [
    (r"\b(refactor|rewrite)\b", "Refactoring"),
    (r"\b(add|implement|create)\b", "Implementing"),
    (r"\b(fix|debug|resolve)\b", "Fixing"),
    (r"\b(update|modify|change)\b", "Updating"),
    (r"\b(review|analyze)\b", "Analyzing"),
    (r"\b(test|write test)\b", "Writing tests for"),
    (r"\b(document|docstring)\b", "Documenting"),
    (r"\b(optimize|improve)\b", "Optimizing"),
]


def safe_decode(data: bytes) -> str:
    """Decode bytes with multiple encoding fallbacks.

    Args:
        data: Raw bytes to decode.

    Returns:
        Decoded string, trying utf-8, cp949, latin-1 in order.
    """
    for encoding in ["utf-8", "cp949", "latin-1"]:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def generate_task_summary(instruction: str, max_length: int = 60) -> str:
    """Generate a short summary for logging from instruction text.

    Args:
        instruction: Full instruction string.
        max_length: Maximum length of the returned summary.

    Returns:
        Concise summary string with action prefix.
    """
    instruction_lower = instruction.lower()
    action_prefix = "Processing"

    for pattern, action in _ACTION_PATTERNS:
        if re.search(pattern, instruction_lower):
            action_prefix = action
            break

    file_match = re.search(r"([a-zA-Z_][a-zA-Z0-9_/]*\.py)", instruction)
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
        first_line = instruction.split("\n")[0][:50].strip()
        if len(first_line) > 40:
            first_line = first_line[:37] + "..."
        subject = first_line

    summary = f"{action_prefix} {subject}"

    if len(summary) > max_length:
        summary = summary[: max_length - 3] + "..."

    return summary


def build_context_block(file_paths: List[str]) -> tuple[str, list[str], list[str]]:
    """Build context string from file paths for Opus delegation.

    Args:
        file_paths: List of file paths (relative to project root).

    Returns:
        Tuple of (context_string, included_files, error_messages).
    """
    if not file_paths:
        return "", [], []

    context_parts: list[str] = []
    included: list[str] = []
    errors: list[str] = []
    total_size = 0

    for file_path in file_paths[:MAX_FILES]:
        is_valid, resolved, error = _validate_file_path(file_path)

        if not is_valid:
            errors.append(error or "Unknown error")
            continue

        if resolved is None:
            continue

        content = _read_file_content(resolved)
        # Keep original logic - LOW priority optimization not worth breaking tests
        content_size = len(content.encode("utf-8"))

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


async def run_claude_cli(
    instruction: str,
    context: str = "",
    model: str = DEFAULT_MODEL,
    timeout: int = COMMAND_TIMEOUT,
    _is_fallback: bool = False,
) -> OpusResult:
    """Execute a task via the Claude CLI subprocess.

    Args:
        instruction: The task instruction to send.
        context: Optional file context block.
        model: Model name ('opus' or 'sonnet').
        timeout: Command timeout in seconds.
        _is_fallback: Whether this is already a fallback attempt.

    Returns:
        OpusResult with execution outcome.
    """
    start_time = time.time()

    if model not in ("opus", "sonnet"):
        _log.warning(f"Model '{model}' not allowed, forcing opus")
        model = "opus"

    if context:
        full_prompt = f"""## Context Files

{context}

## Task

{instruction}"""
    else:
        full_prompt = instruction

    claude_cli = os.path.expanduser("~/.local/bin/claude")
    command = [
        claude_cli,
        "--print",
        "--dangerously-skip-permissions",
        "--model",
        model,
        "-",
    ]

    task_summary = generate_task_summary(instruction)

    _log.info(
        f"[Opus] Executing: {task_summary}",
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
                process.communicate(input=full_prompt.encode("utf-8")),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            execution_time = time.time() - start_time
            _log.error(f"[Opus] Task timed out after {timeout}s: {task_summary}")
            return OpusResult(
                success=False,
                output="",
                error=f"Command timed out after {timeout} seconds",
                exit_code=-1,
                execution_time=execution_time,
            )

        stdout = safe_decode(stdout_bytes)
        stderr = safe_decode(stderr_bytes)
        returncode = process.returncode or 0

        execution_time = time.time() - start_time

        if returncode == 0:
            _log.info(
                f"[Opus] Complete: {task_summary}",
                time=f"{execution_time:.1f}s",
                output_chars=len(stdout),
            )
            return OpusResult(
                success=True,
                output=stdout,
                exit_code=returncode,
                execution_time=execution_time,
            )
        else:
            _log.warning(
                f"[Opus] Failed: {task_summary}",
                exit_code=returncode,
                stderr_preview=stderr[:200] if stderr else None,
            )

            if model == "opus" and not _is_fallback:
                _log.info(f"[Opus] Retrying with sonnet: {task_summary}")
                return await run_claude_cli(
                    instruction=instruction,
                    context=context,
                    model="sonnet",
                    timeout=timeout,
                    _is_fallback=True,
                )

            return OpusResult(
                success=False,
                output=stdout,
                error=stderr or f"Command exited with code {returncode}",
                exit_code=returncode,
                execution_time=execution_time,
            )

    except FileNotFoundError:
        _log.error("[Opus] CLI not found - ensure claude is installed")
        return OpusResult(
            success=False,
            output="",
            error="claude CLI not found. Install it with: npm install -g @anthropic-ai/claude-code",
            exit_code=-1,
        )

    except Exception as e:
        execution_time = time.time() - start_time
        _log.error(f"[Opus] Error: {e}", exc_info=True)
        return OpusResult(
            success=False,
            output="",
            error=str(e),
            exit_code=-1,
            execution_time=execution_time,
        )
