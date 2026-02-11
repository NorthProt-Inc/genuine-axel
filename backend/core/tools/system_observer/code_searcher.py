"""Codebase search functionality with regex support."""

import asyncio
import fnmatch
import os
import re
from pathlib import Path
from typing import List, Optional

from backend.core.logging import get_logger

from . import types

_log = get_logger("tools.system_observer.code_searcher")


def _is_path_excluded(path: str) -> bool:
    """Check if path matches any excluded patterns."""
    for pattern in types.EXCLUDED_PATTERNS:
        if pattern in path:
            return True
    return False


def _is_code_file_allowed(file_path: str) -> bool:
    """Check if file is allowed for code reading."""
    # Exclude based on patterns
    if _is_path_excluded(file_path):
        return False

    # Check extension
    _, ext = os.path.splitext(file_path)
    if ext.lower() not in types.ALLOWED_CODE_EXTENSIONS:
        return False

    # Check file size
    if os.path.exists(file_path) and os.path.getsize(file_path) > types.MAX_FILE_SIZE:
        return False

    return True


def _get_allowed_code_paths() -> List[Path]:
    """Get list of allowed code directories that exist."""
    paths = []
    for dir_name in types.ALLOWED_CODE_DIRS:
        path = types.AXEL_ROOT / dir_name
        if path.exists() and path.is_dir():
            paths.append(path)
    return paths


def _search_file(
    file_path: Path,
    pattern: re.Pattern,
    context_lines: int = types.SEARCH_CONTEXT_LINES
) -> List[types.SearchMatch]:
    """Search single file for pattern matches with context.
    
    Args:
        file_path: File to search
        pattern: Compiled regex pattern
        context_lines: Lines of context before/after match
        
    Returns:
        List of SearchMatch objects
    """
    matches = []

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if pattern.search(line):
                # Extract context
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)

                context_before = [line.rstrip() for line in lines[start:i]]
                context_after = [line.rstrip() for line in lines[i + 1:end]]

                # Use relative path from project root
                relative_path = str(file_path.relative_to(types.AXEL_ROOT))

                matches.append(types.SearchMatch(
                    file_path=relative_path,
                    line_number=i + 1,
                    content=line.rstrip(),
                    context_before=context_before,
                    context_after=context_after
                ))
    except PermissionError:
        _log.debug("Permission denied", path=str(file_path))
    except UnicodeDecodeError:
        pass  # binary file - skip
    except Exception as e:
        _log.warning("File read failed", path=str(file_path), error=str(e))

    return matches


async def search_codebase(
    keyword: str,
    file_pattern: str = "*.py",
    case_sensitive: bool = False,
    include_context: bool = True,
    max_results: int = types.MAX_SEARCH_RESULTS,
    search_dirs: Optional[List[str]] = None
) -> types.SearchResult:
    """Search codebase for keyword with optional file pattern filter.
    
    Args:
        keyword: Text to search for (will be escaped for regex)
        file_pattern: Glob pattern for files (e.g., "*.py", "*.{ts,tsx}")
        case_sensitive: Whether search is case-sensitive
        include_context: Whether to include context lines
        max_results: Maximum number of matches to return
        search_dirs: Optional list of specific directories to search
        
    Returns:
        SearchResult with matches and metadata
    """
    if not keyword:
        return types.SearchResult(
            success=False,
            error="Search keyword cannot be empty"
        )

    # Compile search pattern
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(re.escape(keyword), flags)
    except re.error as e:
        return types.SearchResult(
            success=False,
            error=f"Invalid search pattern: {str(e)}"
        )

    # Determine directories to search
    if search_dirs:
        dirs_to_search = []
        for d in search_dirs:
            path = types.AXEL_ROOT / d
            if path.exists() and d in types.ALLOWED_CODE_DIRS:
                dirs_to_search.append(path)
    else:
        dirs_to_search = _get_allowed_code_paths()

    # Include allowed root files
    root_files = [types.AXEL_ROOT / f for f in types.ALLOWED_ROOT_FILES if (types.AXEL_ROOT / f).exists()]

    # Collect files to search
    files_to_search = []

    for search_dir in dirs_to_search:
        for root, dirs, files in os.walk(search_dir):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not _is_path_excluded(d)]

            for filename in files:
                # Apply file pattern
                if file_pattern != "*":
                    # Handle {ext1,ext2} pattern
                    if "{" in file_pattern:
                        # Split on last dot to get extension group
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

    # Add root files that match pattern
    for root_file in root_files:
        if fnmatch.fnmatch(root_file.name, file_pattern) or file_pattern == "*":
            if _is_code_file_allowed(str(root_file)):
                files_to_search.append(root_file)

    # Search files in batches
    all_matches = []
    files_searched = 0

    context_lines = types.SEARCH_CONTEXT_LINES if include_context else 0

    batch_size = 50
    for i in range(0, len(files_to_search), batch_size):
        batch = files_to_search[i:i + batch_size]

        # Search batch in parallel
        tasks = [
            asyncio.to_thread(_search_file, f, pattern, context_lines)
            for f in batch
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            files_searched += 1
            if isinstance(result, list):
                all_matches.extend(result)

                # Stop if we have enough matches
                if len(all_matches) >= max_results:
                    break

        if len(all_matches) >= max_results:
            break

    # Truncate if needed
    truncated = len(all_matches) > max_results
    if truncated:
        all_matches = all_matches[:max_results]

    return types.SearchResult(
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
    max_results: int = types.MAX_SEARCH_RESULTS
) -> types.SearchResult:
    """Search codebase using regular expression pattern.
    
    Args:
        pattern: Regular expression pattern to search for
        file_pattern: Glob pattern for files to search
        case_sensitive: Whether regex is case-sensitive
        max_results: Maximum number of matches to return
        
    Returns:
        SearchResult with matches and metadata
    """
    if not pattern:
        return types.SearchResult(
            success=False,
            error="Search pattern cannot be empty"
        )

    # Compile regex pattern
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled_pattern = re.compile(pattern, flags)
    except re.error as e:
        return types.SearchResult(
            success=False,
            error=f"Invalid regex pattern: {str(e)}"
        )

    # Get directories and files to search
    dirs_to_search = _get_allowed_code_paths()
    root_files = [types.AXEL_ROOT / f for f in types.ALLOWED_ROOT_FILES if (types.AXEL_ROOT / f).exists()]

    files_to_search = []

    # Collect files from directories
    for search_dir in dirs_to_search:
        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if not _is_path_excluded(d)]

            for filename in files:
                if file_pattern != "*" and not fnmatch.fnmatch(filename, file_pattern):
                    continue

                full_path = Path(root) / filename
                if _is_code_file_allowed(str(full_path)):
                    files_to_search.append(full_path)

    # Add matching root files
    for root_file in root_files:
        if fnmatch.fnmatch(root_file.name, file_pattern) or file_pattern == "*":
            if _is_code_file_allowed(str(root_file)):
                files_to_search.append(root_file)

    # Search files (synchronously for regex)
    all_matches = []
    files_searched = 0

    for file_path in files_to_search:
        matches = _search_file(file_path, compiled_pattern)
        files_searched += 1
        all_matches.extend(matches)

        if len(all_matches) >= max_results:
            break

    # Truncate if needed
    truncated = len(all_matches) > max_results
    if truncated:
        all_matches = all_matches[:max_results]

    return types.SearchResult(
        success=True,
        matches=all_matches,
        total_matches=len(all_matches),
        files_searched=files_searched,
        truncated=truncated
    )


def format_search_results(result: types.SearchResult, max_display: int = 20) -> str:
    """Format search results for display.
    
    Args:
        result: types.SearchResult to format
        max_display: Maximum number of matches to display
        
    Returns:
        Formatted string
    """
    if not result.success:
        return f"❌ Search Error: {result.error}"

    if not result.matches:
        return f"🔍 No matches found (searched {result.files_searched} files)"

    output = [
        f"🔍 Found {result.total_matches} matches in {result.files_searched} files",
        ""
    ]

    if result.truncated:
        output.append(f"⚠️ Results truncated to {len(result.matches)} matches\n")

    for i, match in enumerate(result.matches[:max_display]):
        output.append(f"**{match.file_path}:{match.line_number}**")

        # Add context before
        if match.context_before:
            for ctx in match.context_before:
                output.append(f"  {ctx}")

        # Add matching line
        output.append(f"→ {match.content}")

        # Add context after
        if match.context_after:
            for ctx in match.context_after:
                output.append(f"  {ctx}")

        output.append("")

    if len(result.matches) > max_display:
        output.append(f"... and {len(result.matches) - max_display} more matches")

    return "\n".join(output)


__all__ = [
    "search_codebase",
    "search_codebase_regex",
    "format_search_results",
]
