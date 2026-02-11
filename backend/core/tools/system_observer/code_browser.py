"""Code browsing functionality - read and list source files."""

import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from backend.core.security.path_security import PathAccessType, get_path_security

from . import types

# Import helper functions from code_searcher to avoid duplication
from .code_searcher import _is_code_file_allowed, _is_path_excluded


def get_source_code(relative_path: str) -> Optional[str]:
    """Read source code file by relative path from project root.
    
    Args:
        relative_path: Path relative to types.AXEL_ROOT (e.g., "core/config.py")
        
    Returns:
        File content as string, or None if access denied or error
    """
    # Validate path with security manager
    psm = get_path_security()
    full_path_str = str(types.AXEL_ROOT / relative_path)
    result = psm.validate(full_path_str, PathAccessType.READ_CODE)
    if not result.valid:
        return None

    full_path = result.resolved_path
    assert full_path is not None

    # Check if path is in allowed directories
    path_parts = relative_path.split("/")
    if path_parts:
        root_part = path_parts[0]
        if root_part not in types.ALLOWED_CODE_DIRS and relative_path not in types.ALLOWED_ROOT_FILES:
            return None

    # Check if file is allowed
    if not _is_code_file_allowed(str(full_path)):
        return None

    # Check existence
    if not full_path.exists():
        return None

    # Read file
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


def list_source_files(filter_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all source files in allowed directories.
    
    Args:
        filter_dir: Optional directory name to filter by (e.g., "core")
        
    Returns:
        List of dicts with path, size, and type info
    """
    files = []

    # Determine which directories to scan
    dirs_to_scan = types.ALLOWED_CODE_DIRS if not filter_dir else [filter_dir]

    for dir_name in dirs_to_scan:
        # Skip if filtering and doesn't match
        if filter_dir and dir_name != filter_dir:
            continue

        path = types.AXEL_ROOT / dir_name

        if not path.exists():
            continue

        # Handle single file case
        if path.is_file():
            if _is_code_file_allowed(str(path)):
                files.append({
                    "path": dir_name,
                    "size": path.stat().st_size,
                    "type": path.suffix
                })
        # Handle directory case
        elif path.is_dir():
            for root, dirs, filenames in os.walk(path):
                # Filter out excluded directories
                dirs[:] = [d for d in dirs if not _is_path_excluded(d)]

                for filename in filenames:
                    full_path = Path(root) / filename

                    if _is_code_file_allowed(str(full_path)):
                        relative = full_path.relative_to(types.AXEL_ROOT)
                        files.append({
                            "path": str(relative).replace("\\", "/"),
                            "size": full_path.stat().st_size,
                            "type": full_path.suffix
                        })

    # Add root-level files if not filtering
    if not filter_dir:
        for root_file in types.ALLOWED_ROOT_FILES:
            path = types.AXEL_ROOT / root_file
            if path.exists() and _is_code_file_allowed(str(path)):
                files.append({
                    "path": root_file,
                    "size": path.stat().st_size,
                    "type": path.suffix
                })

    return sorted(files, key=lambda x: x["path"])


def get_code_summary() -> str:
    """Get a formatted summary of the codebase structure.
    
    Returns:
        Markdown-formatted summary string
    """
    files = list_source_files()

    summary = ["## 🏗️ Axel Codebase Structure\n"]

    # Group files by directory
    dirs: Dict[str, List[Dict]] = {}
    for f in files:
        parts = f["path"].split("/")
        dir_name = parts[0] if len(parts) > 1 else "root"
        if dir_name not in dirs:
            dirs[dir_name] = []
        dirs[dir_name].append(f)

    # Format each directory
    for dir_name, dir_files in sorted(dirs.items()):
        summary.append(f"\n### {dir_name}/")
        # Show first 10 files
        for f in dir_files[:10]:
            size_kb = f["size"] / 1024
            summary.append(f"- `{f['path']}` ({size_kb:.1f}KB)")
        if len(dir_files) > 10:
            summary.append(f"- ... and {len(dir_files) - 10} more files")

    # Add totals and usage instructions
    summary.append(f"\n\n**Total: {len(files)} files**")
    summary.append("\n\nUse `get_source_code('path')` to read specific files.")
    summary.append("Use `search_codebase('keyword')` to search across files.")

    return "\n".join(summary)


__all__ = [
    "get_source_code",
    "list_source_files",
    "get_code_summary",
]
