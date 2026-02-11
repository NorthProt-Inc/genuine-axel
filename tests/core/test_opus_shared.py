"""Tests for backend.core.utils.opus_shared."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.utils.opus_shared import (
    build_context_block,
    generate_task_summary,
    run_claude_cli,
    safe_decode,
)
from backend.core.tools.opus_types import OpusResult


# ---------------------------------------------------------------------------
# safe_decode
# ---------------------------------------------------------------------------


class TestSafeDecode:
    def test_utf8_bytes(self):
        assert safe_decode(b"hello world") == "hello world"

    def test_utf8_with_multibyte(self):
        text = "cafe\u0301"
        assert safe_decode(text.encode("utf-8")) == text

    def test_korean_cp949(self):
        # CP949-only bytes that are not valid UTF-8
        korean = "\ud55c\uad6d\uc5b4"
        encoded = korean.encode("cp949")
        result = safe_decode(encoded)
        assert result == korean

    def test_latin1_fallback(self):
        # Byte 0xc0, 0xc1 are invalid UTF-8 lead bytes
        data = bytes([0xc0, 0xc1])
        result = safe_decode(data)
        assert isinstance(result, str)

    def test_replace_fallback(self):
        # latin-1 actually accepts all bytes, so this tests the full chain
        data = b"hello \xff world"
        result = safe_decode(data)
        assert isinstance(result, str)
        assert "hello" in result

    def test_empty_bytes(self):
        assert safe_decode(b"") == ""


# ---------------------------------------------------------------------------
# generate_task_summary
# ---------------------------------------------------------------------------


class TestGenerateTaskSummary:
    def test_refactor_action(self):
        summary = generate_task_summary("refactor the login module")
        assert summary.startswith("Refactoring")

    def test_add_action(self):
        summary = generate_task_summary("add a new feature for users")
        assert summary.startswith("Implementing")

    def test_fix_action(self):
        summary = generate_task_summary("fix the broken login flow")
        assert summary.startswith("Fixing")

    def test_update_action(self):
        summary = generate_task_summary("update the configuration")
        assert summary.startswith("Updating")

    def test_review_action(self):
        summary = generate_task_summary("review the code in main.py")
        assert summary.startswith("Analyzing")

    def test_test_action(self):
        summary = generate_task_summary("test the database module")
        assert summary.startswith("Writing tests for")

    def test_document_action(self):
        summary = generate_task_summary("document the API endpoints")
        assert summary.startswith("Documenting")

    def test_optimize_action(self):
        summary = generate_task_summary("optimize the query performance")
        assert summary.startswith("Optimizing")

    def test_default_action(self):
        summary = generate_task_summary("do something unusual with the system")
        assert summary.startswith("Processing")

    def test_file_subject_extraction(self):
        summary = generate_task_summary("refactor backend/app.py to use new pattern")
        assert "backend/app.py" in summary

    def test_function_subject_extraction(self):
        summary = generate_task_summary('fix function "calculate" in the module')
        assert "`calculate`" in summary

    def test_class_subject_extraction(self):
        # The regex matches on lowercased text, so class name is lowercase
        summary = generate_task_summary('fix class "router" in the module')
        assert "`router`" in summary

    def test_module_subject_extraction(self):
        summary = generate_task_summary("review module auth carefully")
        assert "auth module" in summary

    def test_long_instruction_truncated(self):
        long_instruction = "do " + "x" * 200
        summary = generate_task_summary(long_instruction, max_length=60)
        assert len(summary) <= 60
        assert summary.endswith("...")

    def test_max_length_respected(self):
        summary = generate_task_summary("refactor everything", max_length=20)
        assert len(summary) <= 20

    def test_multiline_uses_first_line(self):
        summary = generate_task_summary("do this thing\nand also that\nand more")
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_short_instruction_not_truncated(self):
        summary = generate_task_summary("fix bug")
        assert "..." not in summary or len(summary) < 60

    def test_file_takes_precedence_over_func(self):
        """When both a .py file and a function are mentioned, file wins."""
        summary = generate_task_summary('fix function "calc" in backend/math.py')
        assert "backend/math.py" in summary

    def test_func_takes_precedence_over_module(self):
        """When both function and module match, function wins (checked first)."""
        summary = generate_task_summary('fix method "run" in module auth')
        assert "`run`" in summary


# ---------------------------------------------------------------------------
# build_context_block
# ---------------------------------------------------------------------------


class TestBuildContextBlock:
    @patch("backend.core.utils.opus_shared._read_file_content")
    @patch("backend.core.utils.opus_shared._validate_file_path")
    def test_empty_file_list(self, mock_validate, mock_read):
        ctx, included, errors = build_context_block([])
        assert ctx == ""
        assert included == []
        assert errors == []

    @patch("backend.core.utils.opus_shared.AXEL_ROOT", new=Path("/project"))
    @patch("backend.core.utils.opus_shared._read_file_content")
    @patch("backend.core.utils.opus_shared._validate_file_path")
    def test_single_valid_file(self, mock_validate, mock_read):
        resolved = Path("/project/src/app.py")
        mock_validate.return_value = (True, resolved, None)
        mock_read.return_value = "print('hello')"

        ctx, included, errors = build_context_block(["src/app.py"])

        assert len(included) == 1
        assert "src/app.py" in included[0]
        assert "print('hello')" in ctx
        assert errors == []

    @patch("backend.core.utils.opus_shared._read_file_content")
    @patch("backend.core.utils.opus_shared._validate_file_path")
    def test_invalid_file_records_error(self, mock_validate, mock_read):
        mock_validate.return_value = (False, None, "Extension not allowed")

        ctx, included, errors = build_context_block(["bad.exe"])

        assert included == []
        assert len(errors) == 1
        assert "Extension not allowed" in errors[0]

    @patch("backend.core.utils.opus_shared.MAX_FILES", 2)
    @patch("backend.core.utils.opus_shared._read_file_content")
    @patch("backend.core.utils.opus_shared._validate_file_path")
    def test_too_many_files_warning(self, mock_validate, mock_read):
        mock_validate.return_value = (False, None, "skip")

        files = ["a.py", "b.py", "c.py"]
        ctx, included, errors = build_context_block(files)

        assert any("Too many files" in e for e in errors)

    @patch("backend.core.utils.opus_shared.MAX_TOTAL_CONTEXT", 10)
    @patch("backend.core.utils.opus_shared.AXEL_ROOT", new=Path("/project"))
    @patch("backend.core.utils.opus_shared._read_file_content")
    @patch("backend.core.utils.opus_shared._validate_file_path")
    def test_context_limit_exceeded(self, mock_validate, mock_read):
        resolved = Path("/project/big.py")
        mock_validate.return_value = (True, resolved, None)
        # First call: content fits. Second call: would exceed limit.
        mock_read.side_effect = ["tiny", "x" * 100]

        ctx, included, errors = build_context_block(["small.py", "big.py"])

        # First file fits (4 bytes < 10), second file exceeds
        assert len(included) == 1
        assert any("Context limit" in e for e in errors)

    @patch("backend.core.utils.opus_shared.AXEL_ROOT", new=Path("/project"))
    @patch("backend.core.utils.opus_shared._read_file_content")
    @patch("backend.core.utils.opus_shared._validate_file_path")
    def test_multiple_valid_files(self, mock_validate, mock_read):
        resolved_a = Path("/project/a.py")
        resolved_b = Path("/project/b.py")
        mock_validate.side_effect = [
            (True, resolved_a, None),
            (True, resolved_b, None),
        ]
        mock_read.side_effect = ["code_a", "code_b"]

        ctx, included, errors = build_context_block(["a.py", "b.py"])

        assert len(included) == 2
        assert "code_a" in ctx
        assert "code_b" in ctx
        assert errors == []

    @patch("backend.core.utils.opus_shared.AXEL_ROOT", new=Path("/project"))
    @patch("backend.core.utils.opus_shared._read_file_content")
    @patch("backend.core.utils.opus_shared._validate_file_path")
    def test_context_block_format(self, mock_validate, mock_read):
        resolved = Path("/project/foo.py")
        mock_validate.return_value = (True, resolved, None)
        mock_read.return_value = "content"

        ctx, _, _ = build_context_block(["foo.py"])

        assert "### File: foo.py" in ctx
        assert "```" in ctx


# ---------------------------------------------------------------------------
# run_claude_cli
# ---------------------------------------------------------------------------


class TestRunClaudeCli:
    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_successful_execution(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"output text", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result = await run_claude_cli("do something")

        assert isinstance(result, OpusResult)
        assert result.success is True
        assert result.output == "output text"
        assert result.exit_code == 0

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_with_context(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"done", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result = await run_claude_cli("task", context="file content")

        assert result.success is True
        assert result.output == "done"

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_invalid_model_forced_to_opus(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result = await run_claude_cli("task", model="gpt-4")

        assert result.success is True
        call_args = mock_exec.call_args[0]
        assert "opus" in call_args

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_nonzero_exit_retries_with_sonnet(self, mock_exec):
        mock_proc_fail = AsyncMock()
        mock_proc_fail.communicate.return_value = (b"", b"error msg")
        mock_proc_fail.returncode = 1

        mock_proc_ok = AsyncMock()
        mock_proc_ok.communicate.return_value = (b"ok via sonnet", b"")
        mock_proc_ok.returncode = 0

        mock_exec.side_effect = [mock_proc_fail, mock_proc_ok]

        result = await run_claude_cli("task", model="opus")

        assert result.success is True
        assert result.output == "ok via sonnet"
        assert mock_exec.call_count == 2

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_nonzero_exit_no_retry_if_already_fallback(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"partial", b"err")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        result = await run_claude_cli("task", model="sonnet", _is_fallback=True)

        assert result.success is False
        assert mock_exec.call_count == 1

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_timeout_kills_process(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.communicate.side_effect = asyncio.TimeoutError()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_exec.return_value = mock_proc

        result = await run_claude_cli("slow task", timeout=1)

        assert result.success is False
        assert "timed out" in result.error.lower()
        assert result.exit_code == -1
        mock_proc.kill.assert_called_once()

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_file_not_found_error(self, mock_exec):
        mock_exec.side_effect = FileNotFoundError()

        result = await run_claude_cli("task")

        assert result.success is False
        assert "not found" in result.error.lower()

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_generic_exception(self, mock_exec):
        mock_exec.side_effect = RuntimeError("unexpected failure")

        result = await run_claude_cli("task")

        assert result.success is False
        assert "unexpected failure" in result.error

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_sonnet_model_accepted(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"sonnet output", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result = await run_claude_cli("task", model="sonnet")

        assert result.success is True
        call_args = mock_exec.call_args[0]
        assert "sonnet" in call_args

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_nonzero_exit_sonnet_no_retry(self, mock_exec):
        """When model=sonnet and not a fallback, no retry happens (only opus triggers fallback)."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"fail", b"err")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        result = await run_claude_cli("task", model="sonnet", _is_fallback=False)

        assert result.success is False
        assert mock_exec.call_count == 1

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_execution_time_is_positive(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result = await run_claude_cli("task")

        assert result.execution_time >= 0.0

    @patch("backend.core.utils.opus_shared.asyncio.create_subprocess_exec")
    async def test_stderr_included_in_error_on_failure(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"detailed error info")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        # Use sonnet + _is_fallback to prevent retry
        result = await run_claude_cli("task", model="sonnet", _is_fallback=True)

        assert result.success is False
        assert result.error == "detailed error info"
