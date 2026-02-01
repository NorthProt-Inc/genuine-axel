import asyncio
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from backend.core.logging import get_logger
from backend.core.tools.opus_types import OpusResult, DelegationResult, OpusHealthStatus
from backend.core.utils.opus_file_validator import (
    AXEL_ROOT,
    OPUS_ALLOWED_EXTENSIONS as ALLOWED_EXTENSIONS,
    OPUS_MAX_FILE_SIZE as MAX_FILE_SIZE,
    OPUS_MAX_FILES as MAX_FILES,
    OPUS_MAX_TOTAL_CONTEXT as MAX_TOTAL_CONTEXT,
    validate_opus_file_path as _validate_file_path,
    read_opus_file_content as _read_file_content,
)

logger = get_logger("opus-executor")

DEFAULT_MODEL = "opus"

# Regex pattern to strip XML-style tags from LLM output
_XML_TAG_PATTERN = re.compile(
    r'</?(?:'
    r'attempt_completion|result|thought|thinking|reflection|'
    r'call:[^>]+|function_call|tool_call|tool_result|tool_use|'
    r'antthinking|search_quality_reflection|search_quality_score|'
    r'invoke|parameters|arguments|input|output|name|value'
    r')[^>]*>',
    re.IGNORECASE | re.DOTALL
)

# Pattern to detect complete tool call blocks
_TOOL_BLOCK_PATTERN = re.compile(
    r'<(?:function_call|tool_call|tool_use|invoke)[^>]*>.*?</(?:function_call|tool_call|tool_use|invoke)>',
    re.IGNORECASE | re.DOTALL
)

def _strip_xml_tags(text: str) -> str:
    """Strip XML-style control tags from LLM output, preserving content."""
    if not text:
        return text
    # First, remove complete tool call blocks entirely
    cleaned = _TOOL_BLOCK_PATTERN.sub('', text)
    # Then remove individual XML tags, keeping the content between them
    cleaned = _XML_TAG_PATTERN.sub('', cleaned)
    # Clean up excessive whitespace left behind
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r'  +', ' ', cleaned)
    return cleaned.strip()

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

async def delegate_to_opus(
    instruction: str,
    file_paths: Optional[List[str]] = None,
    model: str = "opus",
) -> DelegationResult:

    file_paths = file_paths or []

    if model not in ("opus", "sonnet"):
        model = "opus"

    try:

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
            # Strip XML tags from output before returning
            cleaned_output = _strip_xml_tags(result.output)
            response_parts.append(cleaned_output)

            return DelegationResult(
                success=True,
                response="\n\n".join(response_parts),
                files_included=included_files,
                execution_time=result.execution_time
            )
        else:
            # Strip XML tags from error output as well
            cleaned_output = _strip_xml_tags(result.output) if result.output else ""
            return DelegationResult(
                success=False,
                response=cleaned_output,
                error=result.error,
                files_included=included_files,
                execution_time=result.execution_time
            )

    except Exception as e:
        return DelegationResult(
            success=False,
            response="",
            error=f"Execution error: {str(e)}"
        )

async def check_opus_health(timeout: int = 10) -> OpusHealthStatus:

    try:
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
                message="Claude CLI available",
                version=version,
                details={
                    "default_model": DEFAULT_MODEL,
                    "timeout": COMMAND_TIMEOUT,
                    "max_context_kb": MAX_TOTAL_CONTEXT // 1024,
                    "working_directory": str(AXEL_ROOT),
                }
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
            "max_files": MAX_FILES,
            "max_file_size_kb": MAX_FILE_SIZE // 1024,
            "max_total_context_kb": MAX_TOTAL_CONTEXT // 1024,
            "timeout_seconds": COMMAND_TIMEOUT
        },
        "supported_extensions": list(ALLOWED_EXTENSIONS)
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
    "OpusResult",

    "get_mcp_tool_definition",

    "_generate_task_summary",
    "_build_context_block",

    "AXEL_ROOT",
    "DEFAULT_MODEL",
    "COMMAND_TIMEOUT",
    "MAX_FILE_SIZE",
    "MAX_FILES",
    "MAX_TOTAL_CONTEXT",
    "ALLOWED_EXTENSIONS",
]
