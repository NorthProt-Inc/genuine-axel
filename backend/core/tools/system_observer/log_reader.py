"""Log reading and filtering functionality."""

import asyncio
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from backend.core.logging import get_logger
from backend.core.security.path_security import PathAccessType, get_path_security

from . import types
from .types import LogReadResult

_log = get_logger("tools.system_observer.log_reader")


def _validate_log_path(log_path: str) -> Tuple[bool, Optional[Path], Optional[str]]:
    """Validate and resolve log file path.
    
    Returns:
        (is_valid, resolved_path, error_message)
    """
    # Check aliases first
    if log_path.lower() in types.LOG_FILE_ALIASES:
        log_path = types.LOG_FILE_ALIASES[log_path.lower()]

    # Bare filename — search in allowed log dirs directly
    if "/" not in log_path and "\\" not in log_path:
        for log_dir in types.ALLOWED_LOG_DIRS:
            candidate = log_dir / log_path
            if candidate.exists():
                return True, candidate, None
        return False, None, f"Log file '{log_path}' not found in allowed directories"

    # Use path security manager for full paths
    psm = get_path_security()
    result = psm.validate(log_path, PathAccessType.READ_LOG, must_exist=True, must_be_file=True)
    if result.valid:
        return True, result.resolved_path, None
    return False, None, result.error


def _read_tail(file_path: Path, num_lines: int) -> str:
    """Read last N lines from file efficiently."""
    with open(file_path, 'rb') as f:
        # Get file size
        f.seek(0, 2)
        file_size = f.tell()

        if file_size == 0:
            return ""

        # For small files, just read all
        if file_size < 1024 * 100:
            f.seek(0)
            lines = f.readlines()
            return b''.join(lines[-num_lines:]).decode('utf-8', errors='replace')

        # For large files, read in chunks from the end
        buffer = b''
        chunk_size = 8192
        lines_found = 0
        position = file_size

        while position > 0 and lines_found <= num_lines:
            read_size = min(chunk_size, position)
            position -= read_size
            f.seek(position)
            chunk = f.read(read_size)
            buffer = chunk + buffer
            lines_found = buffer.count(b'\n')

        lines = buffer.decode('utf-8', errors='replace').split('\n')

        # Return last num_lines (handle trailing newline)
        return '\n'.join(lines[-num_lines:] if lines[-1] else lines[-(num_lines + 1):-1])


def _filter_lines(content: str, keyword: str, case_sensitive: bool) -> Tuple[str, int]:
    """Filter lines containing keyword.
    
    Returns:
        (filtered_content, original_line_count)
    """
    lines = content.split('\n')
    original_count = len(lines)

    if case_sensitive:
        filtered = [line for line in lines if keyword in line]
    else:
        keyword_lower = keyword.lower()
        filtered = [line for line in lines if keyword_lower in line.lower()]

    return '\n'.join(filtered), original_count


async def read_logs(
    log_file: str = "app.log",
    lines: int = 50,
    filter_keyword: Optional[str] = None,
    case_sensitive: bool = False
) -> LogReadResult:
    """Read last N lines from a log file with optional filtering.
    
    Args:
        log_file: Log file name or path (supports aliases)
        lines: Number of lines to read (max MAX_LOG_LINES)
        filter_keyword: Optional keyword to filter lines
        case_sensitive: Whether filtering should be case-sensitive
        
    Returns:
        LogReadResult with content and metadata
    """
    # Validate path
    is_valid, resolved_path, error = _validate_log_path(log_file)
    if not is_valid:
        return LogReadResult(
            success=False,
            content="",
            lines_read=0,
            file_path=log_file,
            error=error
        )

    # Clamp lines to allowed range
    lines = min(max(1, lines), types.MAX_LOG_LINES)

    try:
        # Read file in thread to avoid blocking
        content = await asyncio.to_thread(_read_tail, resolved_path, lines)

        # Apply filter if specified
        if filter_keyword:
            content, original_count = _filter_lines(
                content,
                filter_keyword,
                case_sensitive
            )
            filtered_count = len(content.strip().split('\n')) if content.strip() else 0

            return LogReadResult(
                success=True,
                content=content if content else f"No lines matching '{filter_keyword}' found in last {original_count} lines.",
                lines_read=filtered_count,
                file_path=str(resolved_path),
                filter_applied=filter_keyword
            )

        # No filter applied
        lines_read = len(content.strip().split('\n')) if content.strip() else 0

        return LogReadResult(
            success=True,
            content=content,
            lines_read=lines_read,
            file_path=str(resolved_path)
        )

    except PermissionError:
        return LogReadResult(
            success=False,
            content="",
            lines_read=0,
            file_path=str(resolved_path),
            error="Permission denied reading log file"
        )
    except Exception as e:
        return LogReadResult(
            success=False,
            content="",
            lines_read=0,
            file_path=str(resolved_path),
            error=f"Error reading log: {str(e)}"
        )


async def list_available_logs() -> Dict[str, Any]:
    """List all available log files in allowed directories.
    
    Returns:
        Dict with success status, list of logs, and aliases
    """
    logs = []

    for log_dir in types.ALLOWED_LOG_DIRS:
        if not log_dir.exists():
            continue

        for log_file in log_dir.glob("*.log"):
            try:
                stat = log_file.stat()
                logs.append({
                    "path": str(log_file),
                    "name": log_file.name,
                    "size_kb": round(stat.st_size / 1024, 2),
                    "modified": stat.st_mtime
                })
            except OSError as e:
                _log.debug("Log file stat failed", path=str(log_file), error=str(e))
                continue

    # Sort by modification time (newest first)
    logs.sort(key=lambda x: x["modified"], reverse=True)

    return {
        "success": True,
        "logs": logs,
        "aliases": types.LOG_FILE_ALIASES
    }


async def analyze_recent_errors(
    log_file: str = "backend.log",
    lines: int = 500,
    error_patterns: Optional[List[tuple]] = None
) -> Dict[str, Any]:
    """Analyze recent log entries for errors and warnings.
    
    Args:
        log_file: Log file to analyze
        lines: Number of recent lines to analyze
        error_patterns: List of (regex_pattern, category) tuples
        
    Returns:
        Dict with analysis results including categories and recent errors
    """
    # Default error patterns
    default_patterns = [
        (r"ERROR", "error"),
        (r"WARNING", "warning"),
        (r"Exception|Traceback", "exception"),
        (r"CRITICAL", "critical"),
        (r"FAILED|FAILURE", "failure"),
    ]

    patterns = error_patterns or default_patterns

    # Read log file
    result = await read_logs(log_file, lines=lines)

    if not result.success:
        return {
            "success": False,
            "error": result.error,
            "analysis": None
        }

    # Analyze content
    analysis = {
        "total_lines": result.lines_read,
        "categories": {},
        "recent_errors": []
    }

    lines_list = result.content.split('\n')

    # Count matches for each category
    for pattern, category in patterns:
        matching = [
            line for line in lines_list
            if re.search(pattern, line, re.IGNORECASE)
        ]
        analysis["categories"][category] = len(matching)

        # Collect recent critical errors
        if category in ("error", "critical", "exception"):
            analysis["recent_errors"].extend(matching[-5:])

    return {
        "success": True,
        "error": None,
        "analysis": analysis
    }


def format_log_result(result: LogReadResult) -> str:
    """Format log result for display.
    
    Args:
        result: LogReadResult to format
        
    Returns:
        Formatted string
    """
    if not result.success:
        return f"❌ Log Error: {result.error}"

    header = f"📄 Log: {result.file_path} ({result.lines_read} lines)"
    if result.filter_applied:
        header += f" [filter: {result.filter_applied}]"

    return f"{header}\n{'─' * 50}\n{result.content}"


__all__ = [
    "read_logs",
    "list_available_logs",
    "analyze_recent_errors",
    "format_log_result",
]
