"""Tests for backend.core.tools.system_observer.

Covers log reading, codebase search, file listing, code summary,
format helpers, and error analysis. Uses tmp_path for file operations.
"""

import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.core.tools.system_observer import (
    ALLOWED_CODE_DIRS,
    ALLOWED_CODE_EXTENSIONS,
    EXCLUDED_PATTERNS,
    LOG_FILE_ALIASES,
    LogReadResult,
    SearchMatch,
    SearchResult,
    _filter_lines,
    _is_code_file_allowed,
    _is_path_excluded,
    _read_tail,
    _search_file,
    _validate_log_path,
    analyze_recent_errors,
    format_log_result,
    format_search_results,
    get_code_summary,
    get_source_code,
    list_available_logs,
    list_source_files,
    read_logs,
    search_codebase,
    search_codebase_regex,
)


# ---------------------------------------------------------------------------
# _is_path_excluded
# ---------------------------------------------------------------------------


class TestIsPathExcluded:

    def test_pycache_excluded(self):
        assert _is_path_excluded("/project/__pycache__/mod.pyc") is True

    def test_node_modules_excluded(self):
        assert _is_path_excluded("/project/node_modules/pkg") is True

    def test_dotenv_excluded(self):
        assert _is_path_excluded("/project/.env") is True

    def test_git_excluded(self):
        assert _is_path_excluded("/project/.git/config") is True

    def test_venv_excluded(self):
        assert _is_path_excluded("/project/venv/lib/site.py") is True

    def test_normal_path_not_excluded(self):
        assert _is_path_excluded("/project/core/main.py") is False

    def test_egg_info_excluded(self):
        # EXCLUDED_PATTERNS contains "*.egg-info" - the asterisk is literal
        # in substring matching, so the full pattern must appear in the path
        assert _is_path_excluded("/project/pkg*.egg-info/PKG-INFO") is True

    def test_chroma_db_excluded(self):
        assert _is_path_excluded("/project/chroma_db/data") is True


# ---------------------------------------------------------------------------
# _is_code_file_allowed
# ---------------------------------------------------------------------------


class TestIsCodeFileAllowed:

    def test_python_file_allowed(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1")
        assert _is_code_file_allowed(str(f)) is True

    def test_json_file_allowed(self, tmp_path):
        f = tmp_path / "config.json"
        f.write_text("{}")
        assert _is_code_file_allowed(str(f)) is True

    def test_markdown_file_allowed(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text("# Hi")
        assert _is_code_file_allowed(str(f)) is True

    def test_binary_extension_not_allowed(self, tmp_path):
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG")
        assert _is_code_file_allowed(str(f)) is False

    def test_excluded_path_not_allowed(self, tmp_path):
        d = tmp_path / "__pycache__"
        d.mkdir()
        f = d / "module.py"
        f.write_text("x = 1")
        assert _is_code_file_allowed(str(f)) is False

    def test_oversized_file_not_allowed(self, tmp_path):
        f = tmp_path / "big.py"
        f.write_text("x" * (11 * 1024 * 1024))  # > 10MB default
        assert _is_code_file_allowed(str(f)) is False

    def test_nonexistent_file_allowed_by_extension(self):
        # File doesn't exist, but extension is fine and path not excluded
        # Size check is skipped when file doesn't exist
        assert _is_code_file_allowed("/nonexistent/safe.py") is True


# ---------------------------------------------------------------------------
# _validate_log_path
# ---------------------------------------------------------------------------


class TestValidateLogPath:

    def test_alias_resolution(self, tmp_path):
        """Known alias maps to the expected filename."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "backend.log"
        log_file.write_text("log line")

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            valid, resolved, err = _validate_log_path("backend")
            assert valid is True
            assert resolved == log_file

    def test_bare_filename_found(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "custom.log"
        log_file.write_text("data")

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            valid, resolved, err = _validate_log_path("custom.log")
            assert valid is True
            assert resolved == log_file

    def test_bare_filename_not_found(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            valid, resolved, err = _validate_log_path("missing.log")
            assert valid is False
            assert "not found" in err

    def test_full_path_validated_by_security(self):
        """Full path delegates to PathSecurityManager."""
        mock_result = MagicMock()
        mock_result.valid = True
        mock_result.resolved_path = Path("/safe/logs/app.log")

        mock_psm = MagicMock()
        mock_psm.validate.return_value = mock_result

        with patch(
            "backend.core.tools.system_observer.log_reader.get_path_security",
            return_value=mock_psm,
        ):
            valid, resolved, err = _validate_log_path("/safe/logs/app.log")
            assert valid is True
            assert resolved == Path("/safe/logs/app.log")

    def test_full_path_rejected_by_security(self):
        mock_result = MagicMock()
        mock_result.valid = False
        mock_result.error = "Outside allowed dir"

        mock_psm = MagicMock()
        mock_psm.validate.return_value = mock_result

        with patch(
            "backend.core.tools.system_observer.log_reader.get_path_security",
            return_value=mock_psm,
        ):
            valid, resolved, err = _validate_log_path("/etc/shadow")
            assert valid is False
            assert "Outside allowed dir" in err


# ---------------------------------------------------------------------------
# _read_tail
# ---------------------------------------------------------------------------


class TestReadTail:

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.log"
        f.write_text("")
        assert _read_tail(f, 10) == ""

    def test_small_file_all_lines(self, tmp_path):
        f = tmp_path / "small.log"
        f.write_text("line1\nline2\nline3\n")
        result = _read_tail(f, 100)
        assert "line1" in result
        assert "line3" in result

    def test_small_file_tail(self, tmp_path):
        f = tmp_path / "small.log"
        f.write_text("line1\nline2\nline3\n")
        result = _read_tail(f, 2)
        assert "line3" in result
        # May or may not contain line1 depending on exact logic
        lines = [l for l in result.strip().split("\n") if l]
        assert len(lines) <= 2

    def test_large_file_tail(self, tmp_path):
        """File > 100KB triggers chunked reading."""
        f = tmp_path / "large.log"
        # Create a file with enough content to exceed 100KB
        lines = [f"log line {i}: " + "x" * 80 for i in range(2000)]
        f.write_text("\n".join(lines) + "\n")
        assert f.stat().st_size > 100 * 1024

        result = _read_tail(f, 5)
        result_lines = [l for l in result.strip().split("\n") if l]
        assert len(result_lines) <= 5
        # Last lines should be from the end
        assert "1999" in result_lines[-1] or "1998" in result_lines[-1]


# ---------------------------------------------------------------------------
# _filter_lines
# ---------------------------------------------------------------------------


class TestFilterLines:

    def test_case_insensitive_default(self):
        content = "INFO ok\nERROR bad\ninfo also\nwarning meh"
        filtered, original_count = _filter_lines(content, "error", case_sensitive=False)
        assert "ERROR bad" in filtered
        assert "INFO ok" not in filtered
        assert original_count == 4

    def test_case_sensitive(self):
        content = "ERROR bad\nerror bad too"
        filtered, _ = _filter_lines(content, "ERROR", case_sensitive=True)
        assert "ERROR bad" in filtered
        assert "error bad too" not in filtered

    def test_no_matches(self):
        content = "line1\nline2"
        filtered, count = _filter_lines(content, "NOTFOUND", case_sensitive=False)
        assert filtered == ""
        assert count == 2

    def test_empty_content(self):
        filtered, count = _filter_lines("", "test", case_sensitive=False)
        assert count == 1  # Empty string split gives [""]
        assert filtered == ""


# ---------------------------------------------------------------------------
# read_logs (async)
# ---------------------------------------------------------------------------


class TestReadLogs:

    async def test_invalid_path_returns_failure(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            result = await read_logs("nonexistent.log")
            assert result.success is False
            assert "not found" in result.error

    async def test_successful_read(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "app.log"
        log_file.write_text("INFO start\nERROR fail\nINFO end\n")

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            result = await read_logs("app.log", lines=50)
            assert result.success is True
            assert "INFO start" in result.content
            assert result.lines_read == 3

    async def test_read_with_filter_keyword(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "app.log"
        log_file.write_text("INFO ok\nERROR bad\nINFO fine\n")

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            result = await read_logs("app.log", lines=50, filter_keyword="ERROR")
            assert result.success is True
            assert "ERROR bad" in result.content
            assert "INFO ok" not in result.content
            assert result.filter_applied == "ERROR"

    async def test_filter_no_matches(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "app.log"
        log_file.write_text("INFO ok\nINFO fine\n")

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            result = await read_logs("app.log", filter_keyword="CRITICAL")
            assert result.success is True
            assert "No lines matching" in result.content
            assert result.lines_read == 0

    async def test_lines_clamped_to_range(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "app.log"
        log_file.write_text("line\n" * 5)

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            # lines=0 gets clamped to 1
            result = await read_logs("app.log", lines=0)
            # Should still succeed (clamped)
            assert result.success is True

    async def test_permission_error(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "locked.log"
        log_file.write_text("data")

        with (
            patch(
                "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
                [log_dir],
            ),
            patch(
                "backend.core.tools.system_observer.log_reader._read_tail",
                side_effect=PermissionError("denied"),
            ),
        ):
            result = await read_logs("locked.log")
            assert result.success is False
            assert "Permission denied" in result.error

    async def test_generic_exception(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "broken.log"
        log_file.write_text("data")

        with (
            patch(
                "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
                [log_dir],
            ),
            patch(
                "backend.core.tools.system_observer.log_reader._read_tail",
                side_effect=IOError("disk fail"),
            ),
        ):
            result = await read_logs("broken.log")
            assert result.success is False
            assert "disk fail" in result.error


# ---------------------------------------------------------------------------
# list_available_logs (async)
# ---------------------------------------------------------------------------


class TestListAvailableLogs:

    async def test_returns_log_files(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "app.log").write_text("data")
        (log_dir / "error.log").write_text("err")
        (log_dir / "not_a_log.txt").write_text("skip")

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            result = await list_available_logs()
            assert result["success"] is True
            names = [l["name"] for l in result["logs"]]
            assert "app.log" in names
            assert "error.log" in names
            assert "not_a_log.txt" not in names  # Only *.log files

    async def test_nonexistent_log_dir(self, tmp_path):
        missing = tmp_path / "no_such_dir"
        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [missing],
        ):
            result = await list_available_logs()
            assert result["success"] is True
            assert result["logs"] == []

    async def test_aliases_returned(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            result = await list_available_logs()
            assert "aliases" in result
            assert result["aliases"] == LOG_FILE_ALIASES


# ---------------------------------------------------------------------------
# _search_file
# ---------------------------------------------------------------------------


class TestSearchFile:

    def test_simple_match(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("line1\ndef process():\nline3\n")
        pattern = re.compile("process")
        with patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path):
            matches = _search_file(f, pattern, context_lines=1)
        assert len(matches) == 1
        assert matches[0].line_number == 2
        assert "process" in matches[0].content
        assert matches[0].context_before == ["line1"]
        assert matches[0].context_after == ["line3"]

    def test_no_match(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("hello\nworld\n")
        pattern = re.compile("missing")
        with patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path):
            matches = _search_file(f, pattern)
        assert matches == []

    def test_multiple_matches(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("error 1\nok\nerror 2\n")
        pattern = re.compile("error")
        with patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path):
            matches = _search_file(f, pattern)
        assert len(matches) == 2

    def test_permission_error_returns_empty(self, tmp_path):
        f = tmp_path / "locked.py"
        f.write_text("data")
        pattern = re.compile("data")

        with patch("builtins.open", side_effect=PermissionError("denied")):
            matches = _search_file(f, pattern)
            assert matches == []

    def test_context_at_file_boundaries(self, tmp_path):
        """Context should not go out of bounds for first/last lines."""
        f = tmp_path / "test.py"
        f.write_text("first match\nsecond\nthird\n")
        pattern = re.compile("first")
        with patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path):
            matches = _search_file(f, pattern, context_lines=5)
        assert len(matches) == 1
        assert matches[0].context_before == []  # Nothing before first line


# ---------------------------------------------------------------------------
# search_codebase (async)
# ---------------------------------------------------------------------------


class TestSearchCodebase:

    async def test_empty_keyword_returns_failure(self):
        result = await search_codebase("")
        assert result.success is False
        assert "empty" in result.error

    async def test_search_finds_matches(self, tmp_path):
        code_dir = tmp_path / "core"
        code_dir.mkdir()
        py_file = code_dir / "main.py"
        py_file.write_text("def process_request():\n    pass\n")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            result = await search_codebase("process_request")
            assert result.success is True
            assert result.total_matches >= 1
            assert "process_request" in result.matches[0].content

    async def test_case_insensitive_search(self, tmp_path):
        code_dir = tmp_path / "core"
        code_dir.mkdir()
        py_file = code_dir / "main.py"
        py_file.write_text("def MyFunction():\n    pass\n")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            result = await search_codebase("myfunction", case_sensitive=False)
            assert result.success is True
            assert result.total_matches == 1

    async def test_case_sensitive_search_misses(self, tmp_path):
        code_dir = tmp_path / "core"
        code_dir.mkdir()
        py_file = code_dir / "main.py"
        py_file.write_text("def MyFunction():\n    pass\n")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            result = await search_codebase("myfunction", case_sensitive=True)
            assert result.success is True
            assert result.total_matches == 0

    async def test_file_pattern_filter(self, tmp_path):
        code_dir = tmp_path / "core"
        code_dir.mkdir()
        (code_dir / "main.py").write_text("keyword here\n")
        (code_dir / "style.css").write_text("keyword here\n")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            result = await search_codebase("keyword", file_pattern="*.py")
            assert result.success is True
            # Only the .py file should match
            for m in result.matches:
                assert m.file_path.endswith(".py")

    async def test_max_results_truncation(self, tmp_path):
        code_dir = tmp_path / "core"
        code_dir.mkdir()
        # Create a file with many matching lines
        lines = ["match_line\n"] * 50
        (code_dir / "big.py").write_text("".join(lines))

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            result = await search_codebase("match_line", max_results=5)
            assert result.success is True
            assert len(result.matches) <= 5

    async def test_search_with_specific_dirs(self, tmp_path):
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "a.py").write_text("target\n")

        utils_dir = tmp_path / "utils"
        utils_dir.mkdir()
        (utils_dir / "b.py").write_text("target\n")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core", "utils"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            result = await search_codebase("target", search_dirs=["core"])
            assert result.success is True
            # Should only search core/
            for m in result.matches:
                assert m.file_path.startswith("core/")

    async def test_excluded_dirs_skipped(self, tmp_path):
        code_dir = tmp_path / "core"
        code_dir.mkdir()
        cache_dir = code_dir / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "mod.py").write_text("keyword\n")
        (code_dir / "main.py").write_text("keyword\n")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            result = await search_codebase("keyword")
            assert result.success is True
            for m in result.matches:
                assert "__pycache__" not in m.file_path


# ---------------------------------------------------------------------------
# search_codebase_regex (async)
# ---------------------------------------------------------------------------


class TestSearchCodebaseRegex:

    async def test_empty_pattern_returns_failure(self):
        result = await search_codebase_regex("")
        assert result.success is False
        assert "empty" in result.error

    async def test_invalid_regex_returns_failure(self):
        result = await search_codebase_regex("[invalid")
        assert result.success is False
        assert "Invalid regex" in result.error

    async def test_regex_search_finds_matches(self, tmp_path):
        code_dir = tmp_path / "core"
        code_dir.mkdir()
        (code_dir / "main.py").write_text("def foo_bar():\ndef baz_qux():\n")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            result = await search_codebase_regex(r"def \w+_\w+\(")
            assert result.success is True
            assert result.total_matches == 2


# ---------------------------------------------------------------------------
# get_source_code
# ---------------------------------------------------------------------------


class TestGetSourceCode:

    def test_allowed_file_reads_content(self, tmp_path):
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        f = core_dir / "main.py"
        f.write_text("print('hello')")

        mock_result = MagicMock()
        mock_result.valid = True
        mock_result.resolved_path = f

        mock_psm = MagicMock()
        mock_psm.validate.return_value = mock_result

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch(
                "backend.core.tools.system_observer.code_browser.get_path_security",
                return_value=mock_psm,
            ),
        ):
            content = get_source_code("core/main.py")
            assert content == "print('hello')"

    def test_disallowed_dir_returns_none(self, tmp_path):
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        f = secret_dir / "keys.py"
        f.write_text("SECRET=123")

        mock_result = MagicMock()
        mock_result.valid = True
        mock_result.resolved_path = f

        mock_psm = MagicMock()
        mock_psm.validate.return_value = mock_result

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
            patch(
                "backend.core.tools.system_observer.code_browser.get_path_security",
                return_value=mock_psm,
            ),
        ):
            content = get_source_code("secrets/keys.py")
            assert content is None

    def test_security_rejection_returns_none(self, tmp_path):
        mock_result = MagicMock()
        mock_result.valid = False

        mock_psm = MagicMock()
        mock_psm.validate.return_value = mock_result

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch(
                "backend.core.tools.system_observer.code_browser.get_path_security",
                return_value=mock_psm,
            ),
        ):
            content = get_source_code("../../etc/passwd")
            assert content is None

    def test_nonexistent_file_returns_none(self, tmp_path):
        mock_result = MagicMock()
        mock_result.valid = True
        mock_result.resolved_path = tmp_path / "core" / "missing.py"

        mock_psm = MagicMock()
        mock_psm.validate.return_value = mock_result

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch(
                "backend.core.tools.system_observer.code_browser.get_path_security",
                return_value=mock_psm,
            ),
        ):
            content = get_source_code("core/missing.py")
            assert content is None

    def test_allowed_root_file(self, tmp_path):
        f = tmp_path / "config.py"
        f.write_text("DEBUG=True")

        mock_result = MagicMock()
        mock_result.valid = True
        mock_result.resolved_path = f

        mock_psm = MagicMock()
        mock_psm.validate.return_value = mock_result

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", []),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", ["config.py"]),
            patch(
                "backend.core.tools.system_observer.code_browser.get_path_security",
                return_value=mock_psm,
            ),
        ):
            content = get_source_code("config.py")
            assert content == "DEBUG=True"


# ---------------------------------------------------------------------------
# list_source_files
# ---------------------------------------------------------------------------


class TestListSourceFiles:

    def test_lists_python_files(self, tmp_path):
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "main.py").write_text("x = 1")
        (core_dir / "utils.py").write_text("y = 2")
        (core_dir / "data.bin").write_bytes(b"\x00\x01")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            files = list_source_files()
            paths = [f["path"] for f in files]
            assert "core/main.py" in paths
            assert "core/utils.py" in paths
            # .bin not in ALLOWED_CODE_EXTENSIONS
            assert all("data.bin" not in p for p in paths)

    def test_filter_by_dir(self, tmp_path):
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "a.py").write_text("a")

        utils_dir = tmp_path / "utils"
        utils_dir.mkdir()
        (utils_dir / "b.py").write_text("b")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core", "utils"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            files = list_source_files(filter_dir="core")
            paths = [f["path"] for f in files]
            assert "core/a.py" in paths
            assert all("utils/" not in p for p in paths)

    def test_includes_root_files(self, tmp_path):
        (tmp_path / "config.py").write_text("x = 1")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", []),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", ["config.py"]),
        ):
            files = list_source_files()
            paths = [f["path"] for f in files]
            assert "config.py" in paths

    def test_excludes_pycache(self, tmp_path):
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        cache_dir = core_dir / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "mod.py").write_text("x")
        (core_dir / "mod.py").write_text("x")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            files = list_source_files()
            for f in files:
                assert "__pycache__" not in f["path"]

    def test_file_metadata(self, tmp_path):
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "main.py").write_text("hello")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            files = list_source_files()
            assert len(files) == 1
            assert files[0]["type"] == ".py"
            assert files[0]["size"] == 5  # len("hello")


# ---------------------------------------------------------------------------
# get_code_summary
# ---------------------------------------------------------------------------


class TestGetCodeSummary:

    def test_summary_format(self, tmp_path):
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "main.py").write_text("x = 1")
        (core_dir / "utils.py").write_text("y = 2")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            summary = get_code_summary()
            assert "Codebase Structure" in summary
            assert "core/" in summary
            assert "Total: 2 files" in summary
            assert "get_source_code" in summary

    def test_summary_truncates_long_dirs(self, tmp_path):
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        for i in range(15):
            (core_dir / f"mod_{i}.py").write_text(f"x = {i}")

        with (
            patch("backend.core.tools.system_observer.types.AXEL_ROOT", tmp_path),
            patch("backend.core.tools.system_observer.types.ALLOWED_CODE_DIRS", ["core"]),
            patch("backend.core.tools.system_observer.types.ALLOWED_ROOT_FILES", []),
        ):
            summary = get_code_summary()
            assert "... and 5 more files" in summary


# ---------------------------------------------------------------------------
# format_search_results
# ---------------------------------------------------------------------------


class TestFormatSearchResults:

    def test_error_result(self):
        result = SearchResult(success=False, error="Something broke")
        text = format_search_results(result)
        assert "Search Error" in text
        assert "Something broke" in text

    def test_no_matches(self):
        result = SearchResult(success=True, matches=[], files_searched=10)
        text = format_search_results(result)
        assert "No matches found" in text
        assert "10 files" in text

    def test_with_matches(self):
        result = SearchResult(
            success=True,
            matches=[
                SearchMatch(
                    file_path="core/main.py",
                    line_number=5,
                    content="def hello():",
                    context_before=["# comment"],
                    context_after=["    pass"],
                )
            ],
            total_matches=1,
            files_searched=3,
        )
        text = format_search_results(result)
        assert "Found 1 matches" in text
        assert "core/main.py:5" in text
        assert "def hello()" in text
        assert "# comment" in text

    def test_truncated_results(self):
        result = SearchResult(
            success=True,
            matches=[
                SearchMatch(
                    file_path=f"core/f{i}.py", line_number=i, content=f"line {i}"
                )
                for i in range(30)
            ],
            total_matches=30,
            files_searched=10,
            truncated=True,
        )
        text = format_search_results(result, max_display=5)
        assert "truncated" in text.lower()
        assert "... and 25 more matches" in text

    def test_max_display_limits_output(self):
        matches = [
            SearchMatch(
                file_path=f"core/f{i}.py", line_number=i, content=f"line {i}"
            )
            for i in range(10)
        ]
        result = SearchResult(
            success=True,
            matches=matches,
            total_matches=10,
            files_searched=5,
        )
        text = format_search_results(result, max_display=3)
        assert "... and 7 more matches" in text


# ---------------------------------------------------------------------------
# format_log_result
# ---------------------------------------------------------------------------


class TestFormatLogResult:

    def test_error_result(self):
        result = LogReadResult(
            success=False, content="", lines_read=0,
            file_path="x.log", error="File not found",
        )
        text = format_log_result(result)
        assert "Log Error" in text
        assert "File not found" in text

    def test_success_result(self):
        result = LogReadResult(
            success=True,
            content="line1\nline2",
            lines_read=2,
            file_path="/logs/app.log",
        )
        text = format_log_result(result)
        assert "Log: /logs/app.log" in text
        assert "2 lines" in text
        assert "line1" in text

    def test_filtered_result(self):
        result = LogReadResult(
            success=True,
            content="ERROR bad",
            lines_read=1,
            file_path="/logs/app.log",
            filter_applied="ERROR",
        )
        text = format_log_result(result)
        assert "filter: ERROR" in text


# ---------------------------------------------------------------------------
# analyze_recent_errors (async)
# ---------------------------------------------------------------------------


class TestAnalyzeRecentErrors:

    async def test_log_read_failure_propagates(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            result = await analyze_recent_errors("nonexistent.log")
            assert result["success"] is False
            assert result["error"] is not None

    async def test_categorizes_errors_and_warnings(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "backend.log"
        log_file.write_text(
            "INFO startup\n"
            "ERROR connection failed\n"
            "WARNING slow query\n"
            "ERROR timeout\n"
            "CRITICAL out of memory\n"
            "Traceback (most recent call last):\n"
            "FAILED health check\n"
        )

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            result = await analyze_recent_errors("backend.log", lines=100)
            assert result["success"] is True
            analysis = result["analysis"]
            assert analysis["categories"]["error"] == 2
            assert analysis["categories"]["warning"] == 1
            assert analysis["categories"]["critical"] == 1
            assert analysis["categories"]["exception"] == 1
            # "connection failed" and "FAILED health check" both match FAILED|FAILURE
            assert analysis["categories"]["failure"] == 2
            # Recent errors should include ERROR and CRITICAL and exception lines
            assert len(analysis["recent_errors"]) > 0

    async def test_no_errors_found(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "backend.log"
        log_file.write_text("INFO all good\nINFO still good\n")

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            result = await analyze_recent_errors("backend.log")
            assert result["success"] is True
            analysis = result["analysis"]
            assert analysis["categories"]["error"] == 0
            assert analysis["categories"]["warning"] == 0
            assert analysis["recent_errors"] == []

    async def test_custom_error_patterns(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "backend.log"
        log_file.write_text("CUSTOM_ERR happened\nOK fine\n")

        with patch(
            "backend.core.tools.system_observer.types.ALLOWED_LOG_DIRS",
            [log_dir],
        ):
            result = await analyze_recent_errors(
                "backend.log",
                error_patterns=[(r"CUSTOM_ERR", "custom")],
            )
            assert result["success"] is True
            analysis = result["analysis"]
            assert analysis["categories"]["custom"] == 1


# ---------------------------------------------------------------------------
# _env_int helper (module-level)
# ---------------------------------------------------------------------------


class TestEnvInt:

    def test_default_when_unset(self):
        from backend.core.tools.system_observer import _env_int
        # Use a key that definitely won't be set
        assert _env_int("__TEST_NONEXISTENT_KEY__", 42) == 42

    def test_reads_env_var(self):
        from backend.core.tools.system_observer import _env_int
        os.environ["__TEST_ENV_INT__"] = "99"
        try:
            assert _env_int("__TEST_ENV_INT__", 0) == 99
        finally:
            del os.environ["__TEST_ENV_INT__"]

    def test_invalid_value_falls_back_to_default(self):
        from backend.core.tools.system_observer import _env_int
        os.environ["__TEST_ENV_INT_BAD__"] = "notanumber"
        try:
            assert _env_int("__TEST_ENV_INT_BAD__", 7) == 7
        finally:
            del os.environ["__TEST_ENV_INT_BAD__"]


# ---------------------------------------------------------------------------
# LogReadResult / SearchMatch / SearchResult dataclass basics
# ---------------------------------------------------------------------------


class TestDataclasses:

    def test_log_read_result_defaults(self):
        r = LogReadResult(success=True, content="x", lines_read=1, file_path="/a")
        assert r.error is None
        assert r.filter_applied is None

    def test_search_match_defaults(self):
        m = SearchMatch(file_path="a.py", line_number=1, content="x")
        assert m.context_before == []
        assert m.context_after == []

    def test_search_result_defaults(self):
        r = SearchResult(success=True)
        assert r.matches == []
        assert r.total_matches == 0
        assert r.files_searched == 0
        assert r.truncated is False
