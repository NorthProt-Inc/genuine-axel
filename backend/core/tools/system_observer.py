import asyncio
import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any

AXEL_ROOT = Path(__file__).resolve().parents[3]

MAX_FILE_SIZE = 10 * 1024 * 1024

MAX_LOG_LINES = 1000

MAX_SEARCH_RESULTS = 100

SEARCH_CONTEXT_LINES = 2

ALLOWED_CODE_DIRS = [
    "core",
    "memory",
    "llm",
    "media",
    "reasoning",
    "api",
    "scripts",
    "utils",
    "protocols",
    "mutations",
    "wake",
    "tests",
    "docs",
    "resources",
    "data",
]

ALLOWED_ROOT_FILES = [
    "config.py",
    "app.py",
    "server.py",
    "requirements.txt",
]

ALLOWED_LOG_DIRS = [
    AXEL_ROOT / "logs",
    AXEL_ROOT / "data" / "logs",
]

ALLOWED_CODE_EXTENSIONS = [
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".yaml", ".yml", ".env.example",
    ".txt", ".md", ".mdx",
    ".css", ".scss", ".html",
]

EXCLUDED_PATTERNS = [
    "__pycache__",
    ".pyc",
    "node_modules",
    ".env",
    ".git",
    "chroma_db",
    "venv",
    ".next",
    "dist",
    "build",
    ".venv",
    "*.egg-info",
]

LOG_FILE_ALIASES = {
    "backend": "backend.log",
    "backend_error": "backend.error.log",
    "mcp": "mcp.log",
    "mcp_error": "mcp.error.log",
    "main": "axnmihn.log",
    "rvc": "ultimate_rvc.log",
    "app": "app.log",
}

@dataclass
class LogReadResult:

    success: bool
    content: str
    lines_read: int
    file_path: str
    error: Optional[str] = None
    filter_applied: Optional[str] = None

@dataclass
class SearchMatch:

    file_path: str
    line_number: int
    content: str
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)

@dataclass
class SearchResult:

    success: bool
    matches: List[SearchMatch] = field(default_factory=list)
    total_matches: int = 0
    files_searched: int = 0
    error: Optional[str] = None
    truncated: bool = False

def _is_path_excluded(path: str) -> bool:

    for pattern in EXCLUDED_PATTERNS:
        if pattern in path:
            return True
    return False

def _is_code_file_allowed(file_path: str) -> bool:

    if _is_path_excluded(file_path):
        return False

    _, ext = os.path.splitext(file_path)
    if ext.lower() not in ALLOWED_CODE_EXTENSIONS:
        return False

    if os.path.exists(file_path) and os.path.getsize(file_path) > MAX_FILE_SIZE:
        return False

    return True

def _validate_log_path(log_path: str) -> tuple[bool, Optional[Path], Optional[str]]:

    if log_path.lower() in LOG_FILE_ALIASES:
        log_path = LOG_FILE_ALIASES[log_path.lower()]

    if "/" not in log_path and "\\" not in log_path:
        for log_dir in ALLOWED_LOG_DIRS:
            candidate = log_dir / log_path
            if candidate.exists():
                return True, candidate, None
        return False, None, f"Log file '{log_path}' not found in allowed directories"

    try:
        resolved = Path(log_path).resolve()

        if ".." in str(log_path):
            return False, None, "Path traversal not allowed"

        for allowed_dir in ALLOWED_LOG_DIRS:
            try:
                resolved.relative_to(allowed_dir.resolve())
                if resolved.exists() and resolved.is_file():
                    return True, resolved, None
            except ValueError:
                continue

        return False, None, f"Path '{log_path}' is outside allowed log directories"

    except Exception as e:
        return False, None, f"Invalid path: {str(e)}"

def _get_allowed_code_paths() -> List[Path]:

    paths = []
    for dir_name in ALLOWED_CODE_DIRS:
        path = AXEL_ROOT / dir_name
        if path.exists() and path.is_dir():
            paths.append(path)
    return paths

def _read_tail(file_path: Path, num_lines: int) -> str:

    with open(file_path, 'rb') as f:

        f.seek(0, 2)
        file_size = f.tell()

        if file_size == 0:
            return ""

        if file_size < 1024 * 100:
            f.seek(0)
            lines = f.readlines()
            return b''.join(lines[-num_lines:]).decode('utf-8', errors='replace')

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

        return '\n'.join(lines[-num_lines:] if lines[-1] else lines[-(num_lines + 1):-1])

def _filter_lines(content: str, keyword: str, case_sensitive: bool) -> tuple[str, int]:

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

    is_valid, resolved_path, error = _validate_log_path(log_file)
    if not is_valid:
        return LogReadResult(
            success=False,
            content="",
            lines_read=0,
            file_path=log_file,
            error=error
        )

    lines = min(max(1, lines), MAX_LOG_LINES)

    try:

        content = await asyncio.to_thread(_read_tail, resolved_path, lines)

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

    logs = []

    for log_dir in ALLOWED_LOG_DIRS:
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
            except Exception:
                continue

    logs.sort(key=lambda x: x["modified"], reverse=True)

    return {
        "success": True,
        "logs": logs,
        "aliases": LOG_FILE_ALIASES
    }

def _search_file(
    file_path: Path,
    pattern: re.Pattern,
    context_lines: int = SEARCH_CONTEXT_LINES
) -> List[SearchMatch]:

    matches = []

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if pattern.search(line):

                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)

                context_before = [l.rstrip() for l in lines[start:i]]
                context_after = [l.rstrip() for l in lines[i + 1:end]]

                relative_path = str(file_path.relative_to(AXEL_ROOT))

                matches.append(SearchMatch(
                    file_path=relative_path,
                    line_number=i + 1,
                    content=line.rstrip(),
                    context_before=context_before,
                    context_after=context_after
                ))
    except Exception:

        pass

    return matches

async def search_codebase(
    keyword: str,
    file_pattern: str = "*.py",
    case_sensitive: bool = False,
    include_context: bool = True,
    max_results: int = MAX_SEARCH_RESULTS,
    search_dirs: Optional[List[str]] = None
) -> SearchResult:

    if not keyword:
        return SearchResult(
            success=False,
            error="Search keyword cannot be empty"
        )

    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(re.escape(keyword), flags)
    except re.error as e:
        return SearchResult(
            success=False,
            error=f"Invalid search pattern: {str(e)}"
        )

    if search_dirs:
        dirs_to_search = []
        for d in search_dirs:
            path = AXEL_ROOT / d
            if path.exists() and d in ALLOWED_CODE_DIRS:
                dirs_to_search.append(path)
    else:
        dirs_to_search = _get_allowed_code_paths()

    root_files = [AXEL_ROOT / f for f in ALLOWED_ROOT_FILES if (AXEL_ROOT / f).exists()]

    files_to_search = []

    for search_dir in dirs_to_search:
        for root, dirs, files in os.walk(search_dir):

            dirs[:] = [d for d in dirs if not _is_path_excluded(d)]

            for filename in files:

                if file_pattern != "*":

                    if "{" in file_pattern:

                        base, ext_group = file_pattern.rsplit(".", 1)
                        if ext_group.startswith("{") and ext_group.endswith("}"):
                            exts = ext_group[1:-1].split(",")
                            if not any(filename.endswith(f".{e}") for e in exts):
                                continue
                    elif not fnmatch.fnmatch(filename, file_pattern):
                        continue

                full_path = Path(root) / filename

                if _is_code_file_allowed(str(full_path)):
                    files_to_search.append(full_path)

    for root_file in root_files:
        if fnmatch.fnmatch(root_file.name, file_pattern) or file_pattern == "*":
            if _is_code_file_allowed(str(root_file)):
                files_to_search.append(root_file)

    all_matches = []
    files_searched = 0

    context_lines = SEARCH_CONTEXT_LINES if include_context else 0

    batch_size = 50
    for i in range(0, len(files_to_search), batch_size):
        batch = files_to_search[i:i + batch_size]

        tasks = [
            asyncio.to_thread(_search_file, f, pattern, context_lines)
            for f in batch
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            files_searched += 1
            if isinstance(result, list):
                all_matches.extend(result)

                if len(all_matches) >= max_results:
                    break

        if len(all_matches) >= max_results:
            break

    truncated = len(all_matches) > max_results
    if truncated:
        all_matches = all_matches[:max_results]

    return SearchResult(
        success=True,
        matches=all_matches,
        total_matches=len(all_matches),
        files_searched=files_searched,
        truncated=truncated
    )

async def search_codebase_regex(
    pattern: str,
    file_pattern: str = "*.py",
    case_sensitive: bool = False,
    max_results: int = MAX_SEARCH_RESULTS
) -> SearchResult:

    if not pattern:
        return SearchResult(
            success=False,
            error="Search pattern cannot be empty"
        )

    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled_pattern = re.compile(pattern, flags)
    except re.error as e:
        return SearchResult(
            success=False,
            error=f"Invalid regex pattern: {str(e)}"
        )

    dirs_to_search = _get_allowed_code_paths()
    root_files = [AXEL_ROOT / f for f in ALLOWED_ROOT_FILES if (AXEL_ROOT / f).exists()]

    files_to_search = []

    for search_dir in dirs_to_search:
        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if not _is_path_excluded(d)]

            for filename in files:
                if file_pattern != "*" and not fnmatch.fnmatch(filename, file_pattern):
                    continue

                full_path = Path(root) / filename
                if _is_code_file_allowed(str(full_path)):
                    files_to_search.append(full_path)

    for root_file in root_files:
        if fnmatch.fnmatch(root_file.name, file_pattern) or file_pattern == "*":
            if _is_code_file_allowed(str(root_file)):
                files_to_search.append(root_file)

    all_matches = []
    files_searched = 0

    for file_path in files_to_search:
        matches = _search_file(file_path, compiled_pattern)
        files_searched += 1
        all_matches.extend(matches)

        if len(all_matches) >= max_results:
            break

    truncated = len(all_matches) > max_results
    if truncated:
        all_matches = all_matches[:max_results]

    return SearchResult(
        success=True,
        matches=all_matches,
        total_matches=len(all_matches),
        files_searched=files_searched,
        truncated=truncated
    )

def get_source_code(relative_path: str) -> Optional[str]:

    full_path = AXEL_ROOT / relative_path

    path_parts = relative_path.split("/")
    if path_parts:
        root_part = path_parts[0]
        if root_part not in ALLOWED_CODE_DIRS and relative_path not in ALLOWED_ROOT_FILES:
            return None

    if not _is_code_file_allowed(str(full_path)):
        return None

    if not full_path.exists():
        return None

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def list_source_files(filter_dir: Optional[str] = None) -> List[Dict[str, Any]]:

    files = []

    dirs_to_scan = ALLOWED_CODE_DIRS if not filter_dir else [filter_dir]

    for dir_name in dirs_to_scan:
        if filter_dir and dir_name != filter_dir:
            continue

        path = AXEL_ROOT / dir_name

        if not path.exists():
            continue

        if path.is_file():
            if _is_code_file_allowed(str(path)):
                files.append({
                    "path": dir_name,
                    "size": path.stat().st_size,
                    "type": path.suffix
                })
        elif path.is_dir():
            for root, dirs, filenames in os.walk(path):
                dirs[:] = [d for d in dirs if not _is_path_excluded(d)]

                for filename in filenames:
                    full_path = Path(root) / filename

                    if _is_code_file_allowed(str(full_path)):
                        relative = full_path.relative_to(AXEL_ROOT)
                        files.append({
                            "path": str(relative).replace("\\", "/"),
                            "size": full_path.stat().st_size,
                            "type": full_path.suffix
                        })

    if not filter_dir:
        for root_file in ALLOWED_ROOT_FILES:
            path = AXEL_ROOT / root_file
            if path.exists() and _is_code_file_allowed(str(path)):
                files.append({
                    "path": root_file,
                    "size": path.stat().st_size,
                    "type": path.suffix
                })

    return sorted(files, key=lambda x: x["path"])

def get_code_summary() -> str:

    files = list_source_files()

    summary = ["##  Axel Codebase Structure\n"]

    dirs: Dict[str, List[Dict]] = {}
    for f in files:
        parts = f["path"].split("/")
        dir_name = parts[0] if len(parts) > 1 else "root"
        if dir_name not in dirs:
            dirs[dir_name] = []
        dirs[dir_name].append(f)

    for dir_name, dir_files in sorted(dirs.items()):
        summary.append(f"\n### {dir_name}/")
        for f in dir_files[:10]:
            size_kb = f["size"] / 1024
            summary.append(f"- `{f['path']}` ({size_kb:.1f}KB)")
        if len(dir_files) > 10:
            summary.append(f"- ... and {len(dir_files) - 10} more files")

    summary.append(f"\n\n**Total: {len(files)} files**")
    summary.append("\n\nUse `get_source_code('path')` to read specific files.")
    summary.append("Use `search_codebase('keyword')` to search across files.")

    return "\n".join(summary)

def format_search_results(result: SearchResult, max_display: int = 20) -> str:

    if not result.success:
        return f" Search Error: {result.error}"

    if not result.matches:
        return f" No matches found (searched {result.files_searched} files)"

    output = [
        f" Found {result.total_matches} matches in {result.files_searched} files",
        ""
    ]

    if result.truncated:
        output.append(f" Results truncated to {len(result.matches)} matches\n")

    for i, match in enumerate(result.matches[:max_display]):
        output.append(f"**{match.file_path}:{match.line_number}**")

        if match.context_before:
            for ctx in match.context_before:
                output.append(f"  {ctx}")

        output.append(f"→ {match.content}")

        if match.context_after:
            for ctx in match.context_after:
                output.append(f"  {ctx}")

        output.append("")

    if len(result.matches) > max_display:
        output.append(f"... and {len(result.matches) - max_display} more matches")

    return "\n".join(output)

def format_log_result(result: LogReadResult) -> str:

    if not result.success:
        return f" Log Error: {result.error}"

    header = f" Log: {result.file_path} ({result.lines_read} lines)"
    if result.filter_applied:
        header += f" [filter: {result.filter_applied}]"

    return f"{header}\n{'─' * 50}\n{result.content}"

async def analyze_recent_errors(
    log_file: str = "backend.log",
    lines: int = 500,
    error_patterns: Optional[List[tuple]] = None
) -> Dict[str, Any]:

    default_patterns = [
        (r"ERROR", "error"),
        (r"WARNING", "warning"),
        (r"Exception|Traceback", "exception"),
        (r"CRITICAL", "critical"),
        (r"FAILED|FAILURE", "failure"),
    ]

    patterns = error_patterns or default_patterns

    result = await read_logs(log_file, lines=lines)

    if not result.success:
        return {
            "success": False,
            "error": result.error,
            "analysis": None
        }

    analysis = {
        "total_lines": result.lines_read,
        "categories": {},
        "recent_errors": []
    }

    lines_list = result.content.split('\n')

    for pattern, category in patterns:
        matching = [
            line for line in lines_list
            if re.search(pattern, line, re.IGNORECASE)
        ]
        analysis["categories"][category] = len(matching)

        if category in ("error", "critical", "exception"):
            analysis["recent_errors"].extend(matching[-5:])

    return {
        "success": True,
        "error": None,
        "analysis": analysis
    }

__all__ = [

    "read_logs",
    "list_available_logs",
    "analyze_recent_errors",
    "LogReadResult",

    "search_codebase",
    "search_codebase_regex",
    "SearchResult",
    "SearchMatch",

    "get_source_code",
    "list_source_files",
    "get_code_summary",

    "format_search_results",
    "format_log_result",

    "ALLOWED_CODE_DIRS",
    "ALLOWED_LOG_DIRS",
    "LOG_FILE_ALIASES",
]
