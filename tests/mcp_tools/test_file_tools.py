"""Tests for backend.core.mcp_tools.file_tools -- File tool handlers.

Each tool is tested for:
  - Successful invocation with valid arguments
  - Missing/empty required parameters
  - Path validation failures
  - File system edge cases (missing, binary, permissions, too large)
  - External dependency fallback (get_source_code ImportError path)

All file I/O uses tmp_path to avoid touching the real filesystem.
Path validation is mocked to isolate tool logic from security policy.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.mcp_tools.file_tools import (
    get_source_code,
    list_directory,
    read_file,
)


# ===========================================================================
# read_file
# ===========================================================================


class TestReadFile:
    async def test_success(self, tmp_path, mock_validate_path, mock_sanitize_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')", encoding="utf-8")

        result = await read_file({"path": str(f)})
        assert result[0].text == "print('hello')"

    async def test_empty_path_returns_error(self):
        result = await read_file({"path": ""})
        assert "Error" in result[0].text
        assert "path parameter is required" in result[0].text

    async def test_missing_path_returns_error(self):
        result = await read_file({})
        assert "Error" in result[0].text

    async def test_path_validation_failure(self, mock_sanitize_path):
        with patch("backend.core.mcp_tools.file_tools.validate_path") as mock_vp:
            mock_vp.return_value = (False, "Path outside allowed directories")
            result = await read_file({"path": "/etc/shadow"})
        assert "Error" in result[0].text
        assert "outside" in result[0].text.lower() or "Path" in result[0].text

    async def test_file_not_found(self, tmp_path, mock_validate_path, mock_sanitize_path):
        result = await read_file({"path": str(tmp_path / "missing.py")})
        assert "Error" in result[0].text
        assert "not found" in result[0].text.lower()

    async def test_not_a_file(self, tmp_path, mock_validate_path, mock_sanitize_path):
        d = tmp_path / "subdir"
        d.mkdir()
        result = await read_file({"path": str(d)})
        assert "Error" in result[0].text
        assert "not a file" in result[0].text.lower()

    async def test_file_too_large(self, tmp_path, mock_validate_path, mock_sanitize_path):
        f = tmp_path / "big.txt"
        f.write_text("x")  # small file, but we mock the size check
        with patch("backend.core.mcp_tools.file_tools.MAX_FILE_SIZE", 5):
            f.write_text("x" * 10)
            result = await read_file({"path": str(f)})
        assert "Error" in result[0].text
        assert "too large" in result[0].text.lower()

    async def test_binary_file(self, tmp_path, mock_validate_path, mock_sanitize_path):
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\xff\xfe")
        result = await read_file({"path": str(f)})
        assert "Error" in result[0].text
        assert "binary" in result[0].text.lower()

    async def test_permission_denied(self, tmp_path, mock_validate_path, mock_sanitize_path):
        f = tmp_path / "secret.txt"
        f.write_text("secret")
        f.chmod(0o000)
        result = await read_file({"path": str(f)})
        assert "Error" in result[0].text
        assert "ermission" in result[0].text  # "Permission" or "permission"
        f.chmod(0o644)

    async def test_generic_exception(self, tmp_path, mock_validate_path, mock_sanitize_path):
        f = tmp_path / "crash.py"
        f.write_text("content")
        with patch.object(Path, "read_text", side_effect=OSError("disk error")):
            result = await read_file({"path": str(f)})
        assert "Error" in result[0].text

    async def test_sanitize_path_called(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("content", encoding="utf-8")
        with patch("backend.core.mcp_tools.file_tools.sanitize_path") as mock_sp, \
             patch("backend.core.mcp_tools.file_tools.validate_path", return_value=(True, None)):
            mock_sp.return_value = str(f)
            await read_file({"path": str(f)})
            mock_sp.assert_called_once_with(str(f))


# ===========================================================================
# list_directory
# ===========================================================================


class TestListDirectory:
    async def test_success(self, tmp_path, mock_validate_path, mock_sanitize_path):
        (tmp_path / "subdir").mkdir()
        (tmp_path / "file_a.py").write_text("a")
        (tmp_path / "file_b.txt").write_text("b")

        result = await list_directory({"path": str(tmp_path)})
        text = result[0].text
        assert "[DIR] subdir" in text
        assert "[FILE] file_a.py" in text
        assert "[FILE] file_b.txt" in text

    async def test_dirs_listed_before_files(self, tmp_path, mock_validate_path, mock_sanitize_path):
        (tmp_path / "zdir").mkdir()
        (tmp_path / "afile.txt").write_text("a")

        result = await list_directory({"path": str(tmp_path)})
        text = result[0].text
        lines = text.strip().split("\n")
        # DIR entries should come before FILE entries
        dir_idx = next(i for i, l in enumerate(lines) if "[DIR]" in l)
        file_idx = next(i for i, l in enumerate(lines) if "[FILE]" in l)
        assert dir_idx < file_idx

    async def test_empty_directory(self, tmp_path, mock_validate_path, mock_sanitize_path):
        result = await list_directory({"path": str(tmp_path)})
        assert "empty" in result[0].text.lower()

    async def test_empty_path_returns_error(self):
        result = await list_directory({"path": ""})
        assert "Error" in result[0].text
        assert "path parameter is required" in result[0].text

    async def test_missing_path_returns_error(self):
        result = await list_directory({})
        assert "Error" in result[0].text

    async def test_path_validation_failure(self, mock_sanitize_path):
        with patch("backend.core.mcp_tools.file_tools.validate_path") as mock_vp:
            mock_vp.return_value = (False, "Path traversal detected (..)")
            result = await list_directory({"path": "/etc/../root"})
        assert "Error" in result[0].text

    async def test_path_not_found(self, tmp_path, mock_validate_path, mock_sanitize_path):
        result = await list_directory({"path": str(tmp_path / "nope")})
        assert "Error" in result[0].text
        assert "not found" in result[0].text.lower()

    async def test_not_a_directory(self, tmp_path, mock_validate_path, mock_sanitize_path):
        f = tmp_path / "file.txt"
        f.write_text("content")
        result = await list_directory({"path": str(f)})
        assert "Error" in result[0].text
        assert "not a directory" in result[0].text.lower()

    async def test_permission_denied(self, tmp_path, mock_validate_path, mock_sanitize_path):
        d = tmp_path / "locked"
        d.mkdir()
        d.chmod(0o000)
        result = await list_directory({"path": str(d)})
        assert "Error" in result[0].text
        assert "ermission" in result[0].text
        d.chmod(0o755)

    async def test_generic_exception(self, tmp_path, mock_validate_path, mock_sanitize_path):
        with patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "iterdir", side_effect=OSError("I/O error")):
            result = await list_directory({"path": str(tmp_path)})
        assert "Error" in result[0].text


# ===========================================================================
# get_source_code
# ===========================================================================


class TestGetSourceCode:
    async def test_success_via_system_observer(self):
        with patch(
            "backend.core.tools.system_observer.get_source_code",
            return_value="def main(): pass",
        ):
            result = await get_source_code({"relative_path": "core/chat_handler.py"})
        assert result[0].text == "def main(): pass"

    async def test_empty_path_returns_error(self):
        result = await get_source_code({"relative_path": ""})
        assert "Error" in result[0].text
        assert "relative_path parameter is required" in result[0].text

    async def test_missing_path_returns_error(self):
        result = await get_source_code({})
        assert "Error" in result[0].text

    async def test_source_not_found_via_observer(self):
        with patch(
            "backend.core.tools.system_observer.get_source_code",
            return_value=None,
        ):
            result = await get_source_code({"relative_path": "nonexistent.py"})
        assert "Error" in result[0].text
        assert "Could not read" in result[0].text

    async def test_fallback_on_import_error(self, tmp_path):
        """When system_observer is unavailable, falls back to direct file read."""
        src_file = tmp_path / "module.py"
        src_file.write_text("# source code", encoding="utf-8")

        with patch(
            "backend.core.tools.system_observer.get_source_code",
            side_effect=ImportError("module not found"),
        ), \
             patch("backend.core.mcp_tools.file_tools.validate_path", return_value=(True, None)), \
             patch("backend.config.PROJECT_ROOT", tmp_path):
            result = await get_source_code({"relative_path": "module.py"})
        assert result[0].text == "# source code"

    async def test_fallback_path_validation_failure(self, tmp_path):
        with patch(
            "backend.core.tools.system_observer.get_source_code",
            side_effect=ImportError("no module"),
        ), \
             patch("backend.core.mcp_tools.file_tools.validate_path", return_value=(False, "Forbidden")), \
             patch("backend.config.PROJECT_ROOT", tmp_path):
            result = await get_source_code({"relative_path": ".env"})
        assert "Error" in result[0].text

    async def test_fallback_file_not_found(self, tmp_path):
        with patch(
            "backend.core.tools.system_observer.get_source_code",
            side_effect=ImportError("no module"),
        ), \
             patch("backend.core.mcp_tools.file_tools.validate_path", return_value=(True, None)), \
             patch("backend.config.PROJECT_ROOT", tmp_path):
            result = await get_source_code({"relative_path": "missing.py"})
        assert "Error" in result[0].text
        assert "not found" in result[0].text.lower()

    async def test_fallback_read_exception(self, tmp_path):
        f = tmp_path / "crash.py"
        f.write_text("content")
        f.chmod(0o000)

        with patch(
            "backend.core.tools.system_observer.get_source_code",
            side_effect=ImportError("no module"),
        ), \
             patch("backend.core.mcp_tools.file_tools.validate_path", return_value=(True, None)), \
             patch("backend.config.PROJECT_ROOT", tmp_path):
            result = await get_source_code({"relative_path": "crash.py"})
        assert "Error" in result[0].text
        f.chmod(0o644)

    async def test_observer_generic_exception(self):
        with patch(
            "backend.core.tools.system_observer.get_source_code",
            side_effect=RuntimeError("unexpected"),
        ):
            result = await get_source_code({"relative_path": "any.py"})
        assert "Error" in result[0].text
        assert "unexpected" in result[0].text
