from pathlib import Path
from typing import Optional, Tuple, List
from backend.core.logging import get_logger
from backend.core.security.path_security import PathAccessType, get_path_security

_log = get_logger("path-validator")

ALLOWED_DIRECTORIES: List[Path] = [
    Path.home() / "projects" / "axnmihn",
    Path.home() / ".axel",
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
    operation: str = "read"
) -> Tuple[bool, Optional[str]]:
    """Validate a path via PathSecurityManager.

    Maintains the same (bool, Optional[str]) signature for backward
    compatibility with file_tools.py and other callers.
    """
    psm = get_path_security()
    access_type = PathAccessType.WRITE if operation == "write" else PathAccessType.READ_ANY
    result = psm.validate(path_str, access_type)
    if result.valid:
        return True, None
    return False, result.error


def _is_subpath(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def sanitize_path(path_str: str) -> str:
    if not path_str:
        return path_str

    import re

    path_str = path_str.replace("\x00", "")

    # PERF-040: Use regex instead of while loop for efficiency
    path_str = re.sub(r'/+', '/', path_str)

    path_str = path_str.strip()

    return path_str
