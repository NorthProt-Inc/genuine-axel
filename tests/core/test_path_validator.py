"""Tests for backend.core.utils.path_validator."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.core.utils.path_validator import (
    validate_path,
    _is_subpath,
    sanitize_path,
    ALLOWED_DIRECTORIES,
    FORBIDDEN_PATTERNS,
    READ_ONLY_EXCEPTIONS,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Validate the module-level constant lists."""

    def test_allowed_directories_not_empty(self):
        assert len(ALLOWED_DIRECTORIES) > 0

    def test_allowed_directories_are_paths(self):
        for d in ALLOWED_DIRECTORIES:
            assert isinstance(d, Path)

    def test_forbidden_patterns_not_empty(self):
        assert len(FORBIDDEN_PATTERNS) > 0

    def test_forbidden_patterns_contain_sensitive_items(self):
        assert ".env" in FORBIDDEN_PATTERNS
        assert "id_rsa" in FORBIDDEN_PATTERNS
        assert ".ssh/" in FORBIDDEN_PATTERNS
        assert "credentials" in FORBIDDEN_PATTERNS
        assert "secrets" in FORBIDDEN_PATTERNS

    def test_read_only_exceptions_exist(self):
        assert isinstance(READ_ONLY_EXCEPTIONS, list)


# ---------------------------------------------------------------------------
# _is_subpath
# ---------------------------------------------------------------------------


class TestIsSubpath:
    """Tests for the _is_subpath helper."""

    def test_child_of_parent(self):
        parent = Path("/home/user")
        child = Path("/home/user/projects/file.py")
        assert _is_subpath(child, parent) is True

    def test_same_path_is_subpath(self):
        p = Path("/home/user")
        assert _is_subpath(p, p) is True

    def test_unrelated_paths(self):
        p1 = Path("/home/user")
        p2 = Path("/var/log")
        assert _is_subpath(p1, p2) is False

    def test_parent_is_not_subpath_of_child(self):
        parent = Path("/home/user")
        child = Path("/home/user/projects")
        assert _is_subpath(parent, child) is False


# ---------------------------------------------------------------------------
# sanitize_path
# ---------------------------------------------------------------------------


class TestSanitizePath:
    """Tests for the sanitize_path function."""

    def test_empty_string(self):
        assert sanitize_path("") == ""

    def test_none_input(self):
        """Empty/falsy input returns as-is."""
        assert sanitize_path(None) is None

    def test_removes_null_bytes(self):
        result = sanitize_path("/home/user\x00/file.txt")
        assert "\x00" not in result
        assert result == "/home/user/file.txt"

    def test_collapses_double_slashes(self):
        result = sanitize_path("/home//user///file.txt")
        assert "//" not in result
        assert result == "/home/user/file.txt"

    def test_strips_whitespace(self):
        result = sanitize_path("  /home/user/file.txt  ")
        assert result == "/home/user/file.txt"

    def test_clean_path_unchanged(self):
        path = "/home/user/file.txt"
        assert sanitize_path(path) == path

    def test_multiple_null_bytes(self):
        result = sanitize_path("\x00/home\x00/user\x00")
        assert "\x00" not in result

    def test_combined_sanitization(self):
        """Null bytes + double slashes + whitespace all handled."""
        result = sanitize_path("  /home//\x00user///file.txt  ")
        assert "\x00" not in result
        assert "//" not in result
        assert not result.startswith(" ")
        assert not result.endswith(" ")


# ---------------------------------------------------------------------------
# validate_path (delegates to PathSecurityManager)
# ---------------------------------------------------------------------------


class TestValidatePath:
    """Tests for the validate_path function.

    Since validate_path delegates to PathSecurityManager.validate via
    get_path_security(), we mock get_path_security to isolate the unit.
    """

    def _mock_psm(self, valid: bool, error: str | None = None):
        """Create a mock PathSecurityManager."""
        result = MagicMock()
        result.valid = valid
        result.error = error
        psm = MagicMock()
        psm.validate.return_value = result
        return psm

    @patch("backend.core.utils.path_validator.get_path_security")
    def test_valid_read_path(self, mock_get_psm):
        mock_get_psm.return_value = self._mock_psm(valid=True)
        ok, err = validate_path("/home/northprot/projects/axnmihn/README.md", "read")
        assert ok is True
        assert err is None

    @patch("backend.core.utils.path_validator.get_path_security")
    def test_invalid_path_returns_error(self, mock_get_psm):
        mock_get_psm.return_value = self._mock_psm(
            valid=False, error="Path outside allowed directories"
        )
        ok, err = validate_path("/etc/shadow", "read")
        assert ok is False
        assert err is not None
        assert "outside" in err.lower() or "Path" in err

    @patch("backend.core.utils.path_validator.get_path_security")
    def test_write_operation(self, mock_get_psm):
        mock_get_psm.return_value = self._mock_psm(valid=True)
        ok, err = validate_path("/home/northprot/projects/axnmihn/data/file.json", "write")
        assert ok is True
        assert err is None

    @patch("backend.core.utils.path_validator.get_path_security")
    def test_read_operation_default(self, mock_get_psm):
        """Default operation is 'read'."""
        mock_get_psm.return_value = self._mock_psm(valid=True)
        ok, err = validate_path("/some/path")
        assert ok is True
        # Verify PathAccessType.READ_ANY was used
        from backend.core.security.path_security import PathAccessType
        call_args = mock_get_psm.return_value.validate.call_args
        assert call_args[0][1] == PathAccessType.READ_ANY

    @patch("backend.core.utils.path_validator.get_path_security")
    def test_write_uses_write_access_type(self, mock_get_psm):
        mock_get_psm.return_value = self._mock_psm(valid=True)
        ok, _ = validate_path("/some/path", "write")
        from backend.core.security.path_security import PathAccessType
        call_args = mock_get_psm.return_value.validate.call_args
        assert call_args[0][1] == PathAccessType.WRITE

    @patch("backend.core.utils.path_validator.get_path_security")
    def test_forbidden_pattern_rejected(self, mock_get_psm):
        mock_get_psm.return_value = self._mock_psm(
            valid=False, error="Forbidden pattern in path: .env"
        )
        ok, err = validate_path("/home/user/.env", "read")
        assert ok is False
        assert ".env" in err

    @patch("backend.core.utils.path_validator.get_path_security")
    def test_traversal_rejected(self, mock_get_psm):
        mock_get_psm.return_value = self._mock_psm(
            valid=False, error="Path traversal detected (..)"
        )
        ok, err = validate_path("/home/user/../../../etc/passwd", "read")
        assert ok is False
        assert "traversal" in err.lower()
