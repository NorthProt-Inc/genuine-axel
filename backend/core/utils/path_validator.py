import os
from pathlib import Path
from typing import Optional, Tuple, List
from backend.core.logging import get_logger

logger = get_logger("path-validator")

ALLOWED_DIRECTORIES: List[Path] = [
    Path("/home/northprot/projects/axnmihn"),
    Path("/home/northprot/.axel"),
    Path("/tmp"),
]

FORBIDDEN_PATTERNS: List[str] = [
    ".env",
    ".git/config",
    "id_rsa",
    "id_ed25519",
    ".ssh/",
    "credentials",
    "secrets",
    ".htpasswd",
    ".netrc",
    "shadow",
    "passwd",
]

READ_ONLY_EXCEPTIONS: List[str] = [
    "/etc/passwd",
]

def validate_path(
    path_str: str,
    allow_outside_project: bool = False,
    operation: str = "read"
) -> Tuple[bool, Optional[str]]:

    if not path_str:
        return False, "Path is empty"

    if not isinstance(path_str, str):
        return False, f"Path must be a string, got {type(path_str).__name__}"

    if "\x00" in path_str:
        logger.warning(f"Null byte detected in path: {repr(path_str)}")
        return False, "Invalid characters in path (null byte)"

    if ".." in path_str:
        logger.warning(f"Path traversal attempt detected: {path_str}")
        return False, "Path traversal detected (..)"

    try:

        path = Path(path_str).resolve()
    except Exception as e:
        return False, f"Invalid path format: {e}"

    path_str_resolved = str(path)

    path_lower = path_str_resolved.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.lower() in path_lower:

            if operation == "read" and path_str_resolved in READ_ONLY_EXCEPTIONS:
                continue
            logger.warning(f"Forbidden pattern '{pattern}' in path: {path_str_resolved}")
            return False, f"Access to '{pattern}' is forbidden"

    if not allow_outside_project:
        is_allowed = any(
            path == allowed_dir or
            _is_subpath(path, allowed_dir)
            for allowed_dir in ALLOWED_DIRECTORIES
        )
        if not is_allowed:
            logger.warning(f"Path outside allowed directories: {path_str_resolved}")
            return False, f"Path '{path_str_resolved}' is outside allowed directories"

    return True, None

def _is_subpath(path: Path, parent: Path) -> bool:

    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False

def sanitize_path(path_str: str) -> str:

    if not path_str:
        return path_str

    path_str = path_str.replace("\x00", "")

    while "//" in path_str:
        path_str = path_str.replace("//", "/")

    path_str = path_str.strip()

    return path_str
