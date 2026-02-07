"""Integration tests for opus_executor — verifies shared module usage."""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, "/home/northprot/projects/axnmihn")

from backend.core.tools.opus_types import OpusResult


# ── TestDelegateToOpus ────────────────────────────────────────────────────────


class TestDelegateToOpus:
    """Integration: delegate_to_opus wraps shared module correctly."""

    @pytest.fixture(autouse=True)
    def _patch_shared(self, monkeypatch: pytest.MonkeyPatch):
        """Patch shared functions used by delegate_to_opus."""
        self.mock_build = MagicMock(return_value=("ctx", ["a.py"], []))
        self.mock_run = AsyncMock(
            return_value=OpusResult(
                success=True, output="generated code", exit_code=0, execution_time=1.5
            )
        )
        monkeypatch.setattr(
            "backend.core.tools.opus_executor.build_context_block", self.mock_build
        )
        monkeypatch.setattr("backend.core.tools.opus_executor.run_claude_cli", self.mock_run)

    async def test_successful_delegation(self):
        """Successful run returns DelegationResult with success=True."""
        from backend.core.tools.opus_executor import delegate_to_opus

        result = await delegate_to_opus("write tests", file_paths=["a.py"])

        assert result.success is True
        assert "generated code" in result.response
        assert result.files_included == ["a.py"]
        assert result.execution_time == 1.5

    async def test_xml_tags_stripped_from_output(self):
        """XML control tags are removed from successful output."""
        from backend.core.tools.opus_executor import delegate_to_opus

        self.mock_run.return_value = OpusResult(
            success=True,
            output="<thinking>internal</thinking>visible content",
            exit_code=0,
            execution_time=1.0,
        )

        result = await delegate_to_opus("task")

        assert "<thinking>" not in result.response
        assert "visible content" in result.response

    async def test_xml_tags_stripped_from_error_output(self):
        """XML tags stripped from partial output on failure."""
        from backend.core.tools.opus_executor import delegate_to_opus

        self.mock_run.return_value = OpusResult(
            success=False,
            output="<tool_call>leaked</tool_call>partial",
            error="exit 1",
            exit_code=1,
            execution_time=0.5,
        )

        result = await delegate_to_opus("task")

        assert result.success is False
        assert "<tool_call>" not in result.response

    async def test_context_errors_in_response(self):
        """Context build warnings appear in the response."""
        from backend.core.tools.opus_executor import delegate_to_opus

        self.mock_build.return_value = ("ctx", ["a.py"], ["file too large"])

        result = await delegate_to_opus("task", file_paths=["a.py", "big.py"])

        assert "Warnings:" in result.response
        assert "file too large" in result.response

    async def test_files_included_in_result(self):
        """files_included field reflects build_context_block output."""
        from backend.core.tools.opus_executor import delegate_to_opus

        self.mock_build.return_value = ("ctx", ["x.py", "y.py"], [])

        result = await delegate_to_opus("task", file_paths=["x.py", "y.py"])

        assert result.files_included == ["x.py", "y.py"]

    async def test_invalid_model_defaults_to_opus(self):
        """Invalid model name is corrected to 'opus'."""
        from backend.core.tools.opus_executor import delegate_to_opus

        await delegate_to_opus("task", model="gpt-4")

        call_kwargs = self.mock_run.call_args[1]
        assert call_kwargs["model"] == "opus"

    async def test_exception_returns_error_result(self, monkeypatch: pytest.MonkeyPatch):
        """Unexpected exception produces DelegationResult with error."""
        from backend.core.tools.opus_executor import delegate_to_opus

        self.mock_run.side_effect = RuntimeError("unexpected")

        result = await delegate_to_opus("task")

        assert result.success is False
        assert "Execution error" in result.error


# ── TestCheckOpusHealth ───────────────────────────────────────────────────────


class TestCheckOpusHealth:
    """Integration: health check subprocess behavior."""

    async def test_healthy_returns_status(self, monkeypatch: pytest.MonkeyPatch):
        """Healthy CLI returns available=True with version."""
        from backend.core.tools.opus_executor import check_opus_health

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"1.2.3"

        mock_thread = AsyncMock(return_value=mock_result)
        monkeypatch.setattr("backend.core.tools.opus_executor.asyncio.to_thread", mock_thread)

        status = await check_opus_health()

        assert status.available is True
        assert status.version == "1.2.3"

    async def test_unhealthy_returns_error(self, monkeypatch: pytest.MonkeyPatch):
        """Failed CLI returns available=False."""
        from backend.core.tools.opus_executor import check_opus_health

        mock_result = MagicMock()
        mock_result.returncode = 1

        mock_thread = AsyncMock(return_value=mock_result)
        monkeypatch.setattr("backend.core.tools.opus_executor.asyncio.to_thread", mock_thread)

        status = await check_opus_health()

        assert status.available is False

    async def test_cli_not_found(self, monkeypatch: pytest.MonkeyPatch):
        """Missing CLI returns available=False with install hint."""
        from backend.core.tools.opus_executor import check_opus_health

        mock_thread = AsyncMock(side_effect=FileNotFoundError())
        monkeypatch.setattr("backend.core.tools.opus_executor.asyncio.to_thread", mock_thread)

        status = await check_opus_health()

        assert status.available is False
        assert "not found" in status.message


# ── TestListOpusCapabilities ──────────────────────────────────────────────────


class TestListOpusCapabilities:
    """Verify capabilities dict structure."""

    async def test_returns_tools_list(self):
        """Result contains tools with delegate_to_opus."""
        from backend.core.tools.opus_executor import list_opus_capabilities

        caps = await list_opus_capabilities()

        assert "tools" in caps
        assert any(t["name"] == "delegate_to_opus" for t in caps["tools"])

    async def test_returns_limits(self):
        """Result contains numeric limits."""
        from backend.core.tools.opus_executor import list_opus_capabilities

        caps = await list_opus_capabilities()

        assert "limits" in caps
        assert "max_files" in caps["limits"]
        assert "timeout_seconds" in caps["limits"]
