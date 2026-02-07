"""Tests for opus_shared module — Phase 1 RED.

All tests should fail with ImportError until opus_shared.py is created.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, "/home/northprot/projects/axnmihn")

from backend.core.utils.opus_shared import (
    build_context_block,
    generate_task_summary,
    run_claude_cli,
    safe_decode,
)


# ── Cycle 1.1: safe_decode ────────────────────────────────────────────────────


class TestSafeDecode:
    """Pure function: bytes → str with multi-encoding fallback."""

    def test_utf8_bytes(self):
        """Standard UTF-8 bytes decode correctly."""
        assert safe_decode(b"hello world") == "hello world"

    def test_cp949_bytes(self):
        """Korean CP949-encoded bytes decode correctly."""
        raw = "안녕하세요".encode("cp949")
        assert safe_decode(raw) == "안녕하세요"

    def test_latin1_bytes(self):
        """Latin-1 bytes decode correctly when UTF-8 and CP949 fail."""
        # Single byte 0x80 — invalid utf-8 continuation, not a valid cp949 lead byte alone
        raw = bytes([0x80])
        result = safe_decode(raw)
        # CP949 decodes 0x80 as a single char; latin-1 also would.
        # Either way, should decode to a single character string.
        assert isinstance(result, str)
        assert len(result) == 1

    def test_invalid_bytes_fallback(self):
        """Bytes invalid in all encodings fall back to utf-8 replace."""
        # Lone surrogate byte range — triggers replace in all codecs
        raw = b"\x80\x81\x82\x83"
        result = safe_decode(raw)
        assert isinstance(result, str)

    def test_empty_bytes(self):
        """Empty bytes return empty string."""
        assert safe_decode(b"") == ""


# ── Cycle 1.2: generate_task_summary ──────────────────────────────────────────


class TestGenerateTaskSummary:
    """Pure function: instruction → short summary with action prefix."""

    # -- Action keyword detection --

    def test_refactor_keyword(self):
        result = generate_task_summary("refactor the auth module")
        assert result.startswith("Refactoring")

    def test_implement_keyword(self):
        result = generate_task_summary("implement a new login feature")
        assert result.startswith("Implementing")

    def test_fix_keyword(self):
        result = generate_task_summary("fix the broken database connection")
        assert result.startswith("Fixing")

    def test_update_keyword(self):
        result = generate_task_summary("update the config parser")
        assert result.startswith("Updating")

    def test_review_keyword(self):
        result = generate_task_summary("review the pull request changes")
        assert result.startswith("Analyzing")

    def test_test_keyword(self):
        result = generate_task_summary("test the payment processor")
        assert result.startswith("Writing tests for")

    def test_document_keyword(self):
        result = generate_task_summary("document the API endpoints")
        assert result.startswith("Documenting")

    def test_optimize_keyword(self):
        result = generate_task_summary("optimize the query performance")
        assert result.startswith("Optimizing")

    def test_no_matching_keyword(self):
        result = generate_task_summary("do something with the data")
        assert result.startswith("Processing")

    # -- Subject extraction --

    def test_file_path_extraction(self):
        result = generate_task_summary("refactor core/auth_handler.py to use JWT")
        assert "core/auth_handler.py" in result

    def test_max_length_truncation(self):
        long_instruction = "implement " + "a" * 100 + ".py very long description"
        result = generate_task_summary(long_instruction, max_length=30)
        assert len(result) <= 30
        assert result.endswith("...")

    def test_default_max_length(self):
        result = generate_task_summary("implement a new feature for the system")
        assert len(result) <= 60


# ── Cycle 1.3: build_context_block ────────────────────────────────────────────


class TestBuildContextBlock:
    """Depends on opus_file_validator (mocked via fixtures)."""

    def test_empty_file_list(self):
        """Empty list returns empty context, no files, no errors."""
        context, included, errors = build_context_block([])
        assert context == ""
        assert included == []
        assert errors == []

    def test_single_valid_file(
        self,
        mock_validate_file_path: MagicMock,
        mock_read_file_content: MagicMock,
        mock_axel_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Single valid file produces context block."""
        resolved = mock_axel_root / "backend" / "main.py"
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.touch()

        mock_validate_file_path.return_value = (True, resolved, None)
        mock_read_file_content.return_value = "print('hello')"
        monkeypatch.setattr("backend.core.utils.opus_shared.AXEL_ROOT", mock_axel_root)

        context, included, errors = build_context_block(["backend/main.py"])

        assert "### File:" in context
        assert "print('hello')" in context
        assert len(included) == 1
        assert errors == []

    def test_invalid_file_skipped(
        self,
        mock_validate_file_path: MagicMock,
        mock_read_file_content: MagicMock,
    ):
        """Invalid file path is skipped and added to errors."""
        mock_validate_file_path.return_value = (False, None, "path not allowed")

        context, included, errors = build_context_block(["../../etc/passwd"])

        assert context == ""
        assert included == []
        assert "path not allowed" in errors

    def test_mixed_valid_invalid(
        self,
        mock_validate_file_path: MagicMock,
        mock_read_file_content: MagicMock,
        mock_axel_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Mix of valid and invalid files: valid included, invalid in errors."""
        valid_path = mock_axel_root / "a.py"
        valid_path.touch()

        mock_validate_file_path.side_effect = [
            (True, valid_path, None),
            (False, None, "blocked"),
        ]
        mock_read_file_content.return_value = "code"
        monkeypatch.setattr("backend.core.utils.opus_shared.AXEL_ROOT", mock_axel_root)

        context, included, errors = build_context_block(["a.py", "bad.py"])

        assert len(included) == 1
        assert "blocked" in errors

    def test_max_files_limit(
        self,
        mock_validate_file_path: MagicMock,
        mock_read_file_content: MagicMock,
        mock_axel_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Files beyond MAX_FILES limit trigger error message."""
        resolved = mock_axel_root / "file.py"
        resolved.touch()

        mock_validate_file_path.return_value = (True, resolved, None)
        mock_read_file_content.return_value = "x"
        monkeypatch.setattr("backend.core.utils.opus_shared.AXEL_ROOT", mock_axel_root)

        file_list = [f"file_{i}.py" for i in range(25)]
        context, included, errors = build_context_block(file_list)

        assert any("Too many files" in e for e in errors)

    def test_context_size_limit(
        self,
        mock_validate_file_path: MagicMock,
        mock_read_file_content: MagicMock,
        mock_axel_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Files exceeding total context size limit are skipped."""
        resolved = mock_axel_root / "big.py"
        resolved.touch()

        mock_validate_file_path.return_value = (True, resolved, None)
        # Each file is 600KB; second file exceeds 1MB limit
        mock_read_file_content.return_value = "x" * (600 * 1024)
        monkeypatch.setattr("backend.core.utils.opus_shared.AXEL_ROOT", mock_axel_root)

        context, included, errors = build_context_block(["a.py", "b.py"])

        assert len(included) == 1
        assert any("Context limit reached" in e for e in errors)

    def test_context_format(
        self,
        mock_validate_file_path: MagicMock,
        mock_read_file_content: MagicMock,
        mock_axel_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Context block uses expected markdown format."""
        resolved = mock_axel_root / "src" / "app.py"
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.touch()

        mock_validate_file_path.return_value = (True, resolved, None)
        mock_read_file_content.return_value = "import os"
        monkeypatch.setattr("backend.core.utils.opus_shared.AXEL_ROOT", mock_axel_root)

        context, _, _ = build_context_block(["src/app.py"])

        assert context.startswith("### File: src/app.py")
        assert "```\nimport os\n```" in context


# ── Cycle 1.4: run_claude_cli ─────────────────────────────────────────────────


class TestRunClaudeCli:
    """Async function: subprocess execution with timeout and fallback."""

    @pytest.mark.asyncio
    async def test_successful_execution(
        self,
        mock_create_subprocess: AsyncMock,
        mock_process: AsyncMock,
    ):
        """Successful CLI call returns OpusResult with success=True."""
        mock_process.communicate.return_value = (b"generated code", b"")
        mock_process.returncode = 0

        result = await run_claude_cli(instruction="write hello world")

        assert result.success is True
        assert result.output == "generated code"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_model_validation_forces_opus(
        self,
        mock_create_subprocess: AsyncMock,
        mock_process: AsyncMock,
    ):
        """Invalid model name is forced to 'opus'."""
        mock_process.communicate.return_value = (b"ok", b"")
        mock_process.returncode = 0

        result = await run_claude_cli(instruction="task", model="haiku")

        assert result.success is True
        # Verify the command used opus, not haiku
        call_args = mock_create_subprocess.call_args
        cmd = call_args[0]
        model_idx = list(cmd).index("--model")
        assert cmd[model_idx + 1] == "opus"

    @pytest.mark.asyncio
    async def test_context_prompt_format(
        self,
        mock_create_subprocess: AsyncMock,
        mock_process: AsyncMock,
    ):
        """When context is provided, prompt includes Context Files section."""
        mock_process.communicate.return_value = (b"ok", b"")
        mock_process.returncode = 0

        await run_claude_cli(instruction="do task", context="file contents")

        stdin_bytes = mock_process.communicate.call_args[1]["input"]
        stdin_text = stdin_bytes.decode("utf-8")
        assert "## Context Files" in stdin_text
        assert "file contents" in stdin_text
        assert "## Task" in stdin_text
        assert "do task" in stdin_text

    @pytest.mark.asyncio
    async def test_no_context_prompt_format(
        self,
        mock_create_subprocess: AsyncMock,
        mock_process: AsyncMock,
    ):
        """Without context, prompt is just the instruction."""
        mock_process.communicate.return_value = (b"ok", b"")
        mock_process.returncode = 0

        await run_claude_cli(instruction="simple task", context="")

        stdin_bytes = mock_process.communicate.call_args[1]["input"]
        stdin_text = stdin_bytes.decode("utf-8")
        assert stdin_text == "simple task"

    @pytest.mark.asyncio
    async def test_timeout_kills_process(
        self,
        mock_create_subprocess: AsyncMock,
        mock_process: AsyncMock,
    ):
        """Timeout triggers process.kill() and returns failure."""
        mock_process.communicate.side_effect = asyncio.TimeoutError()

        result = await run_claude_cli(instruction="slow task", timeout=1)

        assert result.success is False
        assert "timed out" in result.error
        assert result.exit_code == -1
        mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(
        self,
        mock_create_subprocess: AsyncMock,
        mock_process: AsyncMock,
    ):
        """Non-zero exit code with _is_fallback=True returns failure."""
        mock_process.communicate.return_value = (b"partial", b"error msg")
        mock_process.returncode = 1

        result = await run_claude_cli(
            instruction="bad task", model="sonnet", _is_fallback=True
        )

        assert result.success is False
        assert "error msg" in result.error

    @pytest.mark.asyncio
    async def test_fallback_to_sonnet_on_failure(
        self,
        mock_create_subprocess: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Failed opus call triggers automatic sonnet retry."""
        call_count = 0

        async def mock_communicate(input=None):
            nonlocal call_count
            call_count += 1
            return (b"partial" if call_count == 1 else b"success output", b"err")

        fail_process = AsyncMock()
        fail_process.communicate = mock_communicate
        fail_process.returncode = 1
        fail_process.kill = MagicMock()
        fail_process.wait = AsyncMock()

        success_process = AsyncMock()
        success_process.communicate = AsyncMock(return_value=(b"success output", b""))
        success_process.returncode = 0
        success_process.kill = MagicMock()
        success_process.wait = AsyncMock()

        mock_create_subprocess.side_effect = [fail_process, success_process]

        result = await run_claude_cli(instruction="retry task", model="opus")

        assert result.success is True
        assert result.output == "success output"
        # Verify sonnet was used in second call
        second_call_cmd = mock_create_subprocess.call_args_list[1][0]
        model_idx = list(second_call_cmd).index("--model")
        assert second_call_cmd[model_idx + 1] == "sonnet"

    @pytest.mark.asyncio
    async def test_no_double_fallback(
        self,
        mock_create_subprocess: AsyncMock,
        mock_process: AsyncMock,
    ):
        """When _is_fallback=True, no recursive retry happens."""
        mock_process.communicate.return_value = (b"", b"still failing")
        mock_process.returncode = 1

        result = await run_claude_cli(
            instruction="task", model="opus", _is_fallback=True
        )

        assert result.success is False
        # Only one subprocess call — no retry
        assert mock_create_subprocess.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_only_from_opus(
        self,
        mock_create_subprocess: AsyncMock,
        mock_process: AsyncMock,
    ):
        """Sonnet model failure does not trigger fallback."""
        mock_process.communicate.return_value = (b"", b"error")
        mock_process.returncode = 1

        result = await run_claude_cli(instruction="task", model="sonnet")

        assert result.success is False
        assert mock_create_subprocess.call_count == 1

    @pytest.mark.asyncio
    async def test_cli_not_found(
        self,
        mock_create_subprocess: AsyncMock,
    ):
        """FileNotFoundError returns descriptive error."""
        mock_create_subprocess.side_effect = FileNotFoundError("claude not found")

        result = await run_claude_cli(instruction="task")

        assert result.success is False
        assert "CLI not found" in result.error
        assert result.exit_code == -1

    @pytest.mark.asyncio
    async def test_generic_exception(
        self,
        mock_create_subprocess: AsyncMock,
    ):
        """Unexpected exception is caught and returned as error."""
        mock_create_subprocess.side_effect = RuntimeError("boom")

        result = await run_claude_cli(instruction="task")

        assert result.success is False
        assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_execution_time_tracked(
        self,
        mock_create_subprocess: AsyncMock,
        mock_process: AsyncMock,
    ):
        """Execution time is recorded in result."""
        mock_process.communicate.return_value = (b"ok", b"")
        mock_process.returncode = 0

        result = await run_claude_cli(instruction="task")

        assert result.execution_time >= 0

    @pytest.mark.asyncio
    async def test_env_has_term_dumb(
        self,
        mock_create_subprocess: AsyncMock,
        mock_process: AsyncMock,
    ):
        """Environment variable TERM=dumb is set for subprocess."""
        mock_process.communicate.return_value = (b"ok", b"")
        mock_process.returncode = 0

        await run_claude_cli(instruction="task")

        call_kwargs = mock_create_subprocess.call_args[1]
        assert call_kwargs["env"]["TERM"] == "dumb"
