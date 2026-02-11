"""Tests for backend.core.utils.opus_file_validator."""

from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

from backend.core.utils.opus_file_validator import (
    OPUS_ALLOWED_EXTENSIONS,
    OPUS_MAX_FILE_SIZE,
    OPUS_MAX_FILES,
    OPUS_MAX_TOTAL_CONTEXT,
    read_opus_file_content,
    validate_opus_file_path,
)
from backend.core.security.path_security import PathValidationResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_allowed_extensions_is_frozenset(self):
        assert isinstance(OPUS_ALLOWED_EXTENSIONS, frozenset)

    def test_allowed_extensions_contains_common_types(self):
        for ext in (".py", ".js", ".ts", ".json", ".md", ".txt", ".yaml"):
            assert ext in OPUS_ALLOWED_EXTENSIONS

    def test_max_file_size(self):
        assert OPUS_MAX_FILE_SIZE == 500 * 1024

    def test_max_files(self):
        assert OPUS_MAX_FILES == 20

    def test_max_total_context(self):
        assert OPUS_MAX_TOTAL_CONTEXT == 1024 * 1024


# ---------------------------------------------------------------------------
# validate_opus_file_path
# ---------------------------------------------------------------------------


class TestValidateOpusFilePath:
    @patch("backend.core.utils.opus_file_validator.get_path_security")
    def test_valid_path_returns_resolved(self, mock_get_psm):
        resolved = Path("/home/user/project/foo.py")
        mock_psm = MagicMock()
        mock_psm.validate.return_value = PathValidationResult(
            valid=True, resolved_path=resolved
        )
        mock_get_psm.return_value = mock_psm

        ok, path, err = validate_opus_file_path("foo.py")

        assert ok is True
        assert path == resolved
        assert err is None

    @patch("backend.core.utils.opus_file_validator.get_path_security")
    def test_invalid_path_returns_error(self, mock_get_psm):
        mock_psm = MagicMock()
        mock_psm.validate.return_value = PathValidationResult(
            valid=False, error="Path outside allowed directories"
        )
        mock_get_psm.return_value = mock_psm

        ok, path, err = validate_opus_file_path("/etc/passwd")

        assert ok is False
        assert path is None
        assert "outside" in err.lower() or err is not None

    @patch("backend.core.utils.opus_file_validator.get_path_security")
    def test_passes_correct_params_to_psm(self, mock_get_psm):
        from backend.core.security.path_security import PathAccessType

        mock_psm = MagicMock()
        mock_psm.validate.return_value = PathValidationResult(valid=False, error="nope")
        mock_get_psm.return_value = mock_psm

        validate_opus_file_path("some/file.py")

        mock_psm.validate.assert_called_once_with(
            "some/file.py",
            PathAccessType.OPUS_DELEGATE,
            must_exist=True,
            must_be_file=True,
            max_size=OPUS_MAX_FILE_SIZE,
            allowed_extensions=OPUS_ALLOWED_EXTENSIONS,
        )


# ---------------------------------------------------------------------------
# read_opus_file_content
# ---------------------------------------------------------------------------


class TestReadOpusFileContent:
    def test_reads_file_successfully(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')", encoding="utf-8")

        content = read_opus_file_content(f)
        assert content == "print('hello')"

    def test_handles_utf8_with_bom(self, tmp_path):
        f = tmp_path / "bom.py"
        f.write_bytes(b"\xef\xbb\xbf# coding: utf-8\n")

        content = read_opus_file_content(f)
        assert "coding" in content

    def test_handles_read_error(self, tmp_path):
        missing = tmp_path / "nonexistent.py"
        content = read_opus_file_content(missing)

        assert content.startswith("[Error reading file:")

    def test_handles_binary_with_replace(self, tmp_path):
        f = tmp_path / "binary.py"
        f.write_bytes(b"hello \xff\xfe world")

        content = read_opus_file_content(f)
        assert "hello" in content
        assert "world" in content

    def test_handles_permission_error(self, tmp_path):
        f = tmp_path / "noperm.py"
        f.write_text("secret")
        f.chmod(0o000)

        content = read_opus_file_content(f)
        assert "[Error reading file:" in content

        # Restore permissions for cleanup
        f.chmod(0o644)

    def test_returns_empty_string_for_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")

        content = read_opus_file_content(f)
        assert content == ""
