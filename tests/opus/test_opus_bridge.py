"""Integration tests for opus_bridge — verifies MCP server uses shared module."""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, "/home/northprot/projects/axnmihn")

from backend.core.tools.opus_types import OpusResult


# ── TestOpusBridgeCallTool ────────────────────────────────────────────────────


class TestOpusBridgeCallTool:
    """Integration: MCP bridge tool handler uses shared module."""

    @pytest.fixture(autouse=True)
    def _patch_shared(self, monkeypatch: pytest.MonkeyPatch):
        """Patch shared functions used by opus_bridge.call_tool."""
        self.mock_build = MagicMock(return_value=("ctx", ["a.py"], []))
        self.mock_run = AsyncMock(
            return_value=OpusResult(
                success=True, output="generated code", exit_code=0, execution_time=1.0
            )
        )
        monkeypatch.setattr(
            "backend.protocols.mcp.opus_bridge.build_context_block", self.mock_build
        )
        monkeypatch.setattr(
            "backend.protocols.mcp.opus_bridge.run_claude_cli", self.mock_run
        )

    async def test_run_opus_task_success(self):
        """Successful run_opus_task returns TextContent with output."""
        from backend.protocols.mcp.opus_bridge import call_tool

        results = await call_tool("run_opus_task", {"instruction": "do task"})

        assert len(results) == 1
        assert "generated code" in results[0].text

    async def test_empty_instruction_error(self):
        """Empty instruction returns error message."""
        from backend.protocols.mcp.opus_bridge import call_tool

        results = await call_tool("run_opus_task", {"instruction": ""})

        assert "Error: instruction is required" in results[0].text

    async def test_context_errors_in_output(self):
        """Context build warnings appear with warning markers."""
        from backend.protocols.mcp.opus_bridge import call_tool

        self.mock_build.return_value = ("ctx", ["a.py"], ["file too big"])

        results = await call_tool("run_opus_task", {"instruction": "task"})

        assert "file too big" in results[0].text

    async def test_xml_filtering_applied(self):
        """XML control tags are stripped from successful output."""
        from backend.protocols.mcp.opus_bridge import call_tool

        self.mock_run.return_value = OpusResult(
            success=True,
            output="<thinking>hidden</thinking>visible",
            exit_code=0,
            execution_time=0.5,
        )

        results = await call_tool("run_opus_task", {"instruction": "task"})

        assert "<thinking>" not in results[0].text
        assert "visible" in results[0].text

    async def test_health_check_healthy(self, monkeypatch: pytest.MonkeyPatch):
        """Healthy health check returns version info."""
        from backend.protocols.mcp.opus_bridge import call_tool

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"2.0.0"

        mock_thread = AsyncMock(return_value=mock_result)
        monkeypatch.setattr(
            "backend.protocols.mcp.opus_bridge.asyncio.to_thread", mock_thread
        )

        results = await call_tool("opus_health_check", {})

        assert "Healthy" in results[0].text
        assert "2.0.0" in results[0].text

    async def test_health_check_cli_not_found(self, monkeypatch: pytest.MonkeyPatch):
        """Missing CLI returns not-available message."""
        from backend.protocols.mcp.opus_bridge import call_tool

        mock_thread = AsyncMock(side_effect=FileNotFoundError())
        monkeypatch.setattr(
            "backend.protocols.mcp.opus_bridge.asyncio.to_thread", mock_thread
        )

        results = await call_tool("opus_health_check", {})

        assert "Not available" in results[0].text

    async def test_unknown_tool_name(self):
        """Unknown tool name returns error message."""
        from backend.protocols.mcp.opus_bridge import call_tool

        results = await call_tool("nonexistent_tool", {})

        assert "Unknown tool" in results[0].text
