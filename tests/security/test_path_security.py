"""Tests for PathSecurityManager (TDD Red phase)."""

from pathlib import Path

import pytest

from backend.core.security.path_security import (
    PathAccessType,
    PathSecurityManager,
    PathValidationResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

AXEL_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def psm() -> PathSecurityManager:
    """Create a fresh PathSecurityManager bound to project root."""
    return PathSecurityManager(project_root=AXEL_ROOT)


# ---------------------------------------------------------------------------
# TestPathValidationResult
# ---------------------------------------------------------------------------


class TestPathValidationResult:
    """Verify the frozen dataclass basics."""

    def test_valid_result(self) -> None:
        r = PathValidationResult(valid=True, resolved_path=Path("/a/b"))
        assert r.valid is True
        assert r.resolved_path == Path("/a/b")
        assert r.error is None

    def test_invalid_result(self) -> None:
        r = PathValidationResult(valid=False, error="bad path")
        assert r.valid is False
        assert r.resolved_path is None
        assert r.error == "bad path"

    def test_frozen(self) -> None:
        r = PathValidationResult(valid=True, resolved_path=Path("/a"))
        with pytest.raises(AttributeError):
            r.valid = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestPathSecurityManagerBasic
# ---------------------------------------------------------------------------


class TestPathSecurityManagerBasic:
    """Empty / None / non-string inputs should be rejected."""

    def test_empty_string(self, psm: PathSecurityManager) -> None:
        r = psm.validate("", PathAccessType.READ_CODE)
        assert r.valid is False
        assert r.error is not None

    def test_none_input(self, psm: PathSecurityManager) -> None:
        r = psm.validate(None, PathAccessType.READ_CODE)  # type: ignore[arg-type]
        assert r.valid is False

    def test_non_string_input(self, psm: PathSecurityManager) -> None:
        r = psm.validate(123, PathAccessType.READ_CODE)  # type: ignore[arg-type]
        assert r.valid is False

    def test_whitespace_only(self, psm: PathSecurityManager) -> None:
        r = psm.validate("   ", PathAccessType.READ_CODE)
        assert r.valid is False


# ---------------------------------------------------------------------------
# TestNullByteProtection
# ---------------------------------------------------------------------------


class TestNullByteProtection:
    """Null bytes must be rejected before any OS call."""

    def test_null_in_middle(self, psm: PathSecurityManager) -> None:
        r = psm.validate("/some/path\x00.txt", PathAccessType.READ_CODE)
        assert r.valid is False
        assert "null" in (r.error or "").lower()

    def test_null_at_end(self, psm: PathSecurityManager) -> None:
        r = psm.validate("core/main.py\x00", PathAccessType.READ_CODE)
        assert r.valid is False


# ---------------------------------------------------------------------------
# TestPathTraversal
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """All forms of '..' traversal must be rejected."""

    def test_simple_dotdot(self, psm: PathSecurityManager) -> None:
        r = psm.validate("../../../etc/passwd", PathAccessType.READ_CODE)
        assert r.valid is False

    def test_dotdot_in_middle(self, psm: PathSecurityManager) -> None:
        r = psm.validate("core/../../../etc/passwd", PathAccessType.READ_CODE)
        assert r.valid is False

    def test_encoded_dotdot(self, psm: PathSecurityManager) -> None:
        r = psm.validate("core/%2e%2e/%2e%2e/etc/passwd", PathAccessType.READ_CODE)
        assert r.valid is False

    def test_backslash_traversal(self, psm: PathSecurityManager) -> None:
        r = psm.validate("core\\..\\..\\etc\\passwd", PathAccessType.READ_CODE)
        assert r.valid is False

    def test_dotdot_absolute(self, psm: PathSecurityManager) -> None:
        r = psm.validate("/home/northprot/projects/axnmihn/../../../etc/shadow", PathAccessType.READ_LOG)
        assert r.valid is False


# ---------------------------------------------------------------------------
# TestSymlinkProtection
# ---------------------------------------------------------------------------


class TestSymlinkProtection:
    """Symlinks pointing outside allowed directories must be rejected."""

    def test_symlink_outside_project(
        self, psm: PathSecurityManager, tmp_path: Path
    ) -> None:
        # Create a file outside project
        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("secret")

        # Create a symlink inside project-like dir pointing outside
        link_dir = tmp_path / "project"
        link_dir.mkdir()
        link = link_dir / "link.txt"
        link.symlink_to(outside_file)

        # Use a PSM scoped to tmp_path/project
        local_psm = PathSecurityManager(project_root=link_dir)
        r = local_psm.validate(str(link), PathAccessType.READ_CODE)
        assert r.valid is False
        assert "symlink" in (r.error or "").lower()

    def test_symlink_inside_project(
        self, psm: PathSecurityManager, tmp_path: Path
    ) -> None:
        # Symlink within allowed directory should pass
        project = tmp_path / "proj"
        project.mkdir()
        src = project / "real.py"
        src.write_text("x = 1")
        link = project / "alias.py"
        link.symlink_to(src)

        local_psm = PathSecurityManager(project_root=project)
        r = local_psm.validate(str(link), PathAccessType.READ_CODE)
        assert r.valid is True


# ---------------------------------------------------------------------------
# TestAccessTypeEnforcement
# ---------------------------------------------------------------------------


class TestAccessTypeEnforcement:
    """Each PathAccessType must only allow its designated directories."""

    def test_read_log_allows_logs_dir(self, psm: PathSecurityManager) -> None:
        log_path = AXEL_ROOT / "logs" / "backend.log"
        if log_path.exists():
            r = psm.validate(str(log_path), PathAccessType.READ_LOG)
            assert r.valid is True

    def test_read_log_rejects_code_dir(self, psm: PathSecurityManager) -> None:
        r = psm.validate(str(AXEL_ROOT / "backend" / "config.py"), PathAccessType.READ_LOG)
        assert r.valid is False

    def test_read_code_allows_backend(self, psm: PathSecurityManager) -> None:
        code_path = AXEL_ROOT / "backend" / "config.py"
        if code_path.exists():
            r = psm.validate(str(code_path), PathAccessType.READ_CODE)
            assert r.valid is True

    def test_read_code_rejects_outside(self, psm: PathSecurityManager) -> None:
        r = psm.validate("/etc/hosts", PathAccessType.READ_CODE)
        assert r.valid is False

    def test_opus_delegate_allows_project(self, psm: PathSecurityManager) -> None:
        code_path = AXEL_ROOT / "backend" / "config.py"
        if code_path.exists():
            r = psm.validate(str(code_path), PathAccessType.OPUS_DELEGATE)
            assert r.valid is True

    def test_opus_delegate_rejects_outside(self, psm: PathSecurityManager) -> None:
        r = psm.validate("/usr/bin/python3", PathAccessType.OPUS_DELEGATE)
        assert r.valid is False


# ---------------------------------------------------------------------------
# TestForbiddenPatterns
# ---------------------------------------------------------------------------


class TestForbiddenPatterns:
    """Sensitive files must be blocked regardless of access type."""

    @pytest.mark.parametrize(
        "forbidden",
        [".env", ".ssh/id_rsa", "credentials.json", ".git/config", ".htpasswd"],
    )
    def test_forbidden_file(
        self, psm: PathSecurityManager, forbidden: str
    ) -> None:
        path = str(AXEL_ROOT / forbidden)
        r = psm.validate(path, PathAccessType.READ_ANY)
        assert r.valid is False
        assert "forbidden" in (r.error or "").lower()


# ---------------------------------------------------------------------------
# TestTmpDirectoryRemoval
# ---------------------------------------------------------------------------


class TestTmpDirectoryRemoval:
    """/tmp must NOT be an allowed directory."""

    def test_system_tmp_rejected(self, psm: PathSecurityManager) -> None:
        r = psm.validate("/tmp/some_file.txt", PathAccessType.READ_ANY)
        assert r.valid is False

    def test_system_tmp_rejected_write(self, psm: PathSecurityManager) -> None:
        r = psm.validate("/tmp/output.json", PathAccessType.WRITE)
        assert r.valid is False


# ---------------------------------------------------------------------------
# TestRegressions (from security report)
# ---------------------------------------------------------------------------


class TestRegressions:
    """Reproduce exact scenarios from the security report."""

    def test_system_observer_log_traversal(self, psm: PathSecurityManager) -> None:
        """system_observer: resolve() before '..' check makes the check useless."""
        r = psm.validate("logs/../../../etc/passwd", PathAccessType.READ_LOG)
        assert r.valid is False

    def test_get_source_code_traversal(self, psm: PathSecurityManager) -> None:
        """get_source_code: 'core/../../../etc/passwd' bypasses first-component check."""
        r = psm.validate("core/../../../etc/passwd", PathAccessType.READ_CODE)
        assert r.valid is False

    def test_opus_null_byte_injection(self, psm: PathSecurityManager) -> None:
        """opus_file_validator: null byte truncation attack."""
        r = psm.validate("backend/config.py\x00.jpg", PathAccessType.OPUS_DELEGATE)
        assert r.valid is False

    def test_path_validator_tmp_abuse(self, psm: PathSecurityManager) -> None:
        """/tmp was in ALLOWED_DIRECTORIES — attacker could read world-readable files."""
        r = psm.validate("/tmp/stolen_data.txt", PathAccessType.READ_ANY)
        assert r.valid is False


# ---------------------------------------------------------------------------
# TestPermissionDeniedPath
# ---------------------------------------------------------------------------


class TestPermissionDeniedPath:
    """Inaccessible paths (e.g. /root/) must return valid=False, not raise."""

    def test_root_path_rejected_gracefully(self, psm: PathSecurityManager) -> None:
        """'/root/...' should be rejected without raising PermissionError."""
        r = psm.validate("/root/axnmihn-backend/README.md", PathAccessType.READ_ANY)
        assert r.valid is False
        assert r.error is not None
