"""Centralized path security validation.

Single entry-point for all path validation across the project.
Replaces fragmented checks in system_observer, opus_file_validator,
and path_validator.
"""

from __future__ import annotations

import enum
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class PathAccessType(enum.Enum):
    """Declares the intent behind a path access request."""

    READ_LOG = "read_log"
    READ_CODE = "read_code"
    READ_ANY = "read_any"
    WRITE = "write"
    OPUS_DELEGATE = "opus_delegate"


@dataclass(frozen=True)
class PathValidationResult:
    """Immutable outcome of a validation check."""

    valid: bool
    resolved_path: Path | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Traversal pattern (pre-resolve, catches encoded variants too)
# ---------------------------------------------------------------------------

_DOTDOT_RE = re.compile(
    r"(?:^|[\\/])\.\.(?:[\\/]|$)"  # literal ../  ..\
    r"|%2[eE]%2[eE]"  # URL-encoded %2e%2e
    r"|%252[eE]%252[eE]",  # double-encoded
)

# ---------------------------------------------------------------------------
# Forbidden filename / path fragments
# ---------------------------------------------------------------------------

_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    ".env",
    ".git/config",
    ".git/HEAD",
    "id_rsa",
    "id_ed25519",
    ".ssh/",
    "credentials",
    "secrets",
    ".htpasswd",
    ".netrc",
    "shadow",
)


# ---------------------------------------------------------------------------
# PathSecurityManager
# ---------------------------------------------------------------------------


class PathSecurityManager:
    """Central path validation engine.

    Args:
        project_root: Absolute path to the project root directory.
        logs_dirs: Extra directories allowed for READ_LOG access.
        data_root: Data directory (for WRITE / temp usage).
    """

    def __init__(
        self,
        project_root: Path,
        logs_dirs: Sequence[Path] | None = None,
        data_root: Path | None = None,
    ) -> None:
        self._project_root = project_root.resolve()
        self._logs_dirs = tuple(
            d.resolve() for d in (logs_dirs or [self._project_root / "logs"])
        )
        self._data_root = (data_root or self._project_root / "data").resolve()

        # Pre-compute allowed dirs per access type
        self._allowed: dict[PathAccessType, tuple[Path, ...]] = {
            PathAccessType.READ_LOG: self._logs_dirs,
            PathAccessType.READ_CODE: (self._project_root,),
            PathAccessType.READ_ANY: (self._project_root, self._data_root),
            PathAccessType.WRITE: (self._data_root,),
            PathAccessType.OPUS_DELEGATE: (self._project_root,),
        }

    # -- public API ----------------------------------------------------------

    def validate(
        self,
        raw_path: str | None,
        access_type: PathAccessType,
        *,
        must_exist: bool = False,
        must_be_file: bool = False,
        max_size: int | None = None,
        allowed_extensions: frozenset[str] | None = None,
    ) -> PathValidationResult:
        """Single entry-point for path validation.

        Args:
            raw_path: The untrusted path string.
            access_type: The intended operation.
            must_exist: Reject if path does not exist on disk.
            must_be_file: Reject if path is not a regular file.
            max_size: Maximum file size in bytes (requires must_exist).
            allowed_extensions: Allowed file suffixes (e.g. {".py", ".md"}).

        Returns:
            PathValidationResult with valid=True and resolved_path on success,
            or valid=False and an error message.
        """
        # 1. Empty / non-string
        if not isinstance(raw_path, str) or not raw_path.strip():
            return PathValidationResult(valid=False, error="Path is empty or invalid type")

        # 2. Null byte
        if "\x00" in raw_path:
            return PathValidationResult(valid=False, error="Null byte in path")

        # 3. Traversal check on raw input (before resolve)
        if _DOTDOT_RE.search(raw_path):
            return PathValidationResult(valid=False, error="Path traversal detected (..)")

        # Also check URL-decoded form
        try:
            decoded = urllib.parse.unquote(raw_path)
        except Exception:
            decoded = raw_path
        if decoded != raw_path and _DOTDOT_RE.search(decoded):
            return PathValidationResult(valid=False, error="Path traversal detected (encoded ..)")

        # 4. Resolve
        try:
            path = Path(raw_path).resolve()
        except (OSError, ValueError) as exc:
            return PathValidationResult(valid=False, error=f"Invalid path: {exc}")

        # 5. Symlink check — original is a symlink whose target must land
        #    inside allowed dirs for this access_type
        raw_p = Path(raw_path)
        try:
            if raw_p.is_symlink():
                target = raw_p.resolve()
                if not self._is_within_allowed(target, access_type):
                    return PathValidationResult(
                        valid=False,
                        error=f"Symlink target outside allowed directories: {target}",
                    )
        except PermissionError:
            return PathValidationResult(
                valid=False,
                error=f"Permission denied accessing path: {raw_path}",
            )

        # 6. Forbidden patterns
        path_str_lower = str(path).lower()
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern.lower() in path_str_lower:
                return PathValidationResult(
                    valid=False,
                    error=f"Forbidden pattern in path: {pattern}",
                )

        # 7. Access-type directory whitelist
        if not self._is_within_allowed(path, access_type):
            return PathValidationResult(
                valid=False,
                error=f"Path outside allowed directories for {access_type.value}",
            )

        # 8. Optional existence / file / size / extension checks
        if must_exist and not path.exists():
            return PathValidationResult(valid=False, error=f"Path does not exist: {path}")

        if must_be_file:
            if not path.exists():
                return PathValidationResult(valid=False, error=f"File not found: {path}")
            if not path.is_file():
                return PathValidationResult(valid=False, error=f"Not a regular file: {path}")

        if max_size is not None and path.exists() and path.is_file():
            try:
                if path.stat().st_size > max_size:
                    return PathValidationResult(
                        valid=False,
                        error=f"File exceeds size limit ({max_size} bytes)",
                    )
            except OSError:
                pass

        if allowed_extensions is not None:
            if path.suffix.lower() not in allowed_extensions:
                return PathValidationResult(
                    valid=False,
                    error=f"File extension not allowed: {path.suffix}",
                )

        return PathValidationResult(valid=True, resolved_path=path)

    # -- internals -----------------------------------------------------------

    def _is_within_allowed(self, path: Path, access_type: PathAccessType) -> bool:
        """Check if *path* falls under at least one allowed directory."""
        for allowed in self._allowed[access_type]:
            try:
                path.relative_to(allowed)
                return True
            except ValueError:
                continue
        return False


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_instance: PathSecurityManager | None = None


def get_path_security() -> PathSecurityManager:
    """Return a project-wide singleton, lazily initialized.

    Uses lazy import of backend.config to avoid circular imports.
    """
    global _instance
    if _instance is None:
        from backend.config import DATA_ROOT, LOGS_DIR, PROJECT_ROOT

        _instance = PathSecurityManager(
            project_root=PROJECT_ROOT,
            logs_dirs=[LOGS_DIR, DATA_ROOT / "logs"],
            data_root=DATA_ROOT,
        )
    return _instance
