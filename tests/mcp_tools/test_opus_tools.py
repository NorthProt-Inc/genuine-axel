"""Tests for backend.core.mcp_tools.opus_tools.

Covers delegate_to_opus_tool and google_deep_research_tool handlers.
All downstream delegation and research calls are mocked.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# delegate_to_opus_tool
# ---------------------------------------------------------------------------


class TestDelegateToOpus:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.opus_tools import delegate_to_opus_tool
        self.tool = delegate_to_opus_tool

    async def test_missing_instruction(self):
        result = await self.tool({"instruction": ""})
        assert "instruction parameter is required" in result[0].text

    async def test_no_instruction_key(self):
        result = await self.tool({})
        assert "instruction parameter is required" in result[0].text

    async def test_invalid_model(self):
        result = await self.tool({"instruction": "do stuff", "model": "gpt4"})
        assert "model must be" in result[0].text

    async def test_successful_delegation(self):
        from backend.core.tools.opus_types import DelegationResult

        mock_result = DelegationResult(
            success=True,
            response="Here is the refactored code...",
            files_included=["core/main.py", "core/utils.py"],
            execution_time=5.42,
        )

        with patch(
            "backend.core.tools.opus_executor.delegate_to_opus",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({
                "instruction": "Refactor auth module",
                "file_paths": "core/main.py,core/utils.py",
                "model": "opus",
            })
            text = result[0].text
            assert "Opus Task Completed" in text
            assert "core/main.py" in text
            assert "5.42s" in text
            assert "refactored code" in text

    async def test_successful_delegation_no_files(self):
        from backend.core.tools.opus_types import DelegationResult

        mock_result = DelegationResult(
            success=True,
            response="Analysis complete.",
            files_included=[],
            execution_time=2.0,
        )

        with patch(
            "backend.core.tools.opus_executor.delegate_to_opus",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"instruction": "Analyze this"})
            text = result[0].text
            assert "Opus Task Completed" in text
            assert "2.00s" in text

    async def test_delegation_failure(self):
        from backend.core.tools.opus_types import DelegationResult

        mock_result = DelegationResult(
            success=False,
            response="Partial output before crash",
            error="CLI timeout after 120s",
            files_included=["core/main.py"],
            execution_time=120.0,
        )

        with patch(
            "backend.core.tools.opus_executor.delegate_to_opus",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({
                "instruction": "Refactor everything",
                "file_paths": "core/main.py",
            })
            text = result[0].text
            assert "Opus Error" in text
            assert "CLI timeout" in text
            assert "Partial output" in text

    async def test_file_paths_parsing_with_spaces(self):
        from backend.core.tools.opus_types import DelegationResult

        mock_result = DelegationResult(
            success=True, response="done", files_included=[], execution_time=1.0,
        )

        with patch(
            "backend.core.tools.opus_executor.delegate_to_opus",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await self.tool({
                "instruction": "test",
                "file_paths": " core/a.py , core/b.py , ",
            })
            call_kwargs = mock_fn.call_args.kwargs
            assert call_kwargs["file_paths"] == ["core/a.py", "core/b.py"]

    async def test_empty_file_paths_string(self):
        from backend.core.tools.opus_types import DelegationResult

        mock_result = DelegationResult(
            success=True, response="done", files_included=[], execution_time=1.0,
        )

        with patch(
            "backend.core.tools.opus_executor.delegate_to_opus",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await self.tool({"instruction": "test", "file_paths": ""})
            call_kwargs = mock_fn.call_args.kwargs
            assert call_kwargs["file_paths"] == []

    async def test_model_defaults_to_opus(self):
        from backend.core.tools.opus_types import DelegationResult

        mock_result = DelegationResult(
            success=True, response="ok", files_included=[], execution_time=1.0,
        )

        with patch(
            "backend.core.tools.opus_executor.delegate_to_opus",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await self.tool({"instruction": "test"})
            call_kwargs = mock_fn.call_args.kwargs
            assert call_kwargs["model"] == "opus"

    async def test_sonnet_model_accepted(self):
        from backend.core.tools.opus_types import DelegationResult

        mock_result = DelegationResult(
            success=True, response="ok", files_included=[], execution_time=1.0,
        )

        with patch(
            "backend.core.tools.opus_executor.delegate_to_opus",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await self.tool({"instruction": "test", "model": "sonnet"})
            assert mock_fn.call_args.kwargs["model"] == "sonnet"

    async def test_haiku_model_accepted(self):
        from backend.core.tools.opus_types import DelegationResult

        mock_result = DelegationResult(
            success=True, response="ok", files_included=[], execution_time=1.0,
        )

        with patch(
            "backend.core.tools.opus_executor.delegate_to_opus",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await self.tool({"instruction": "test", "model": "haiku"})
            assert mock_fn.call_args.kwargs["model"] == "haiku"

    async def test_delegation_exception(self):
        with patch(
            "backend.core.tools.opus_executor.delegate_to_opus",
            new_callable=AsyncMock,
            side_effect=RuntimeError("CLI not installed"),
        ):
            result = await self.tool({"instruction": "test"})
            assert "Opus Error" in result[0].text
            assert "CLI not installed" in result[0].text


# ---------------------------------------------------------------------------
# google_deep_research_tool
# ---------------------------------------------------------------------------


class TestGoogleDeepResearch:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.opus_tools import google_deep_research_tool
        self.tool = google_deep_research_tool

    async def test_missing_query(self):
        result = await self.tool({"query": ""})
        assert "query parameter is required" in result[0].text

    async def test_no_query_key(self):
        result = await self.tool({})
        assert "query parameter is required" in result[0].text

    async def test_invalid_depth_zero(self):
        result = await self.tool({"query": "test", "depth": 0})
        assert "depth must be between 1 and 5" in result[0].text

    async def test_invalid_depth_too_high(self):
        result = await self.tool({"query": "test", "depth": 10})
        assert "depth must be between 1 and 5" in result[0].text

    async def test_invalid_depth_string(self):
        result = await self.tool({"query": "test", "depth": "deep"})
        assert "depth must be between 1 and 5" in result[0].text

    async def test_async_mode_default(self):
        """Default async_mode=True should call dispatch_async_research."""
        with patch(
            "backend.protocols.mcp.async_research.dispatch_async_research",
            return_value="Task abc123 started. Check with check_task_status.",
        ) as mock_dispatch:
            result = await self.tool({"query": "quantum computing"})
            text = result[0].text
            assert "abc123" in text or "started" in text
            mock_dispatch.assert_called_once_with("quantum computing", "google", 3)

    async def test_async_mode_explicit_true(self):
        with patch(
            "backend.protocols.mcp.async_research.dispatch_async_research",
            return_value="Dispatched",
        ) as mock_dispatch:
            result = await self.tool({
                "query": "test", "async_mode": True, "depth": 2,
            })
            mock_dispatch.assert_called_once_with("test", "google", 2)
            assert "Dispatched" in result[0].text

    async def test_sync_mode(self):
        """async_mode=False should call run_research_sync."""
        with patch(
            "backend.protocols.mcp.async_research.run_research_sync",
            new_callable=AsyncMock,
            return_value="# Research Results\n\nFindings...",
        ) as mock_sync:
            result = await self.tool({
                "query": "test", "async_mode": False, "depth": 4,
            })
            mock_sync.assert_called_once_with("test", "google", 4)
            assert "Research Results" in result[0].text

    async def test_async_dispatch_exception(self):
        with patch(
            "backend.protocols.mcp.async_research.dispatch_async_research",
            side_effect=ImportError("async_research not available"),
        ):
            result = await self.tool({"query": "test"})
            assert "Google Research Error" in result[0].text

    async def test_sync_exception(self):
        with patch(
            "backend.protocols.mcp.async_research.run_research_sync",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API key invalid"),
        ):
            result = await self.tool({"query": "test", "async_mode": False})
            assert "Google Research Error" in result[0].text

    async def test_depth_defaults_to_3(self):
        with patch(
            "backend.protocols.mcp.async_research.dispatch_async_research",
            return_value="OK",
        ) as mock_dispatch:
            await self.tool({"query": "test"})
            mock_dispatch.assert_called_once_with("test", "google", 3)

    async def test_valid_depth_boundaries(self):
        """Depth 1 and 5 are valid."""
        with patch(
            "backend.protocols.mcp.async_research.dispatch_async_research",
            return_value="OK",
        ) as mock_dispatch:
            result1 = await self.tool({"query": "t", "depth": 1})
            assert result1[0].text == "OK"

            result5 = await self.tool({"query": "t", "depth": 5})
            assert result5[0].text == "OK"
