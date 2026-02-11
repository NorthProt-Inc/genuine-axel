"""Tests for backend.core.services.tool_service.ToolExecutionService."""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.services.tool_service import (
    ToolExecutionService,
    ToolResult,
    ToolExecutionResult,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _fc(name: str, args: dict | None = None) -> dict:
    """Shorthand to build a function-call dict."""
    d = {"name": name}
    if args is not None:
        d["args"] = args
    return d


# ── is_fire_and_forget ───────────────────────────────────────────────────


class TestIsFireAndForget:
    def test_known_tools(self):
        svc = ToolExecutionService()
        assert svc.is_fire_and_forget("store_memory") is True
        assert svc.is_fire_and_forget("add_memory") is True

    def test_unknown_tools(self):
        svc = ToolExecutionService()
        assert svc.is_fire_and_forget("web_search") is False
        assert svc.is_fire_and_forget("read_file") is False
        assert svc.is_fire_and_forget("") is False


# ── execute_tools ────────────────────────────────────────────────────────


class TestExecuteTools:
    async def test_no_client_returns_empty(self):
        svc = ToolExecutionService(mcp_client=None)
        result = await svc.execute_tools([_fc("web_search", {"q": "hi"})])
        assert isinstance(result, ToolExecutionResult)
        assert result.results == []
        assert result.deferred_tools == []
        assert result.observation == ""

    async def test_empty_function_calls(self, mock_mcp_client):
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        result = await svc.execute_tools([])
        assert result.results == []
        assert result.deferred_tools == []
        assert result.observation == ""

    async def test_immediate_success(self, mock_mcp_client):
        mock_mcp_client.call_tool.return_value = {
            "success": True,
            "result": "search results here",
        }
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        result = await svc.execute_tools([_fc("web_search", {"q": "test"})])

        assert len(result.results) == 1
        assert result.results[0].name == "web_search"
        assert result.results[0].success is True
        assert result.results[0].output == "search results here"
        assert result.deferred_tools == []
        assert "web_search" in result.observation

    async def test_immediate_failure(self, mock_mcp_client):
        mock_mcp_client.call_tool.return_value = {
            "success": False,
            "result": "rate limited",
        }
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        result = await svc.execute_tools([_fc("web_search")])

        assert len(result.results) == 1
        assert result.results[0].success is False
        assert result.results[0].output == "rate limited"

    async def test_deferred_tools_queued(self, mock_mcp_client):
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        result = await svc.execute_tools([
            _fc("store_memory", {"content": "remember this"}),
        ])

        # Deferred tool should not be executed immediately
        mock_mcp_client.call_tool.assert_not_awaited()

        assert len(result.deferred_tools) == 1
        assert result.deferred_tools[0] == ("store_memory", {"content": "remember this"})
        assert len(result.results) == 1
        assert result.results[0].name == "store_memory"
        assert result.results[0].output == "(deferred)"
        assert result.results[0].success is True
        assert "queued for background" in result.observation

    async def test_mixed_deferred_and_immediate(self, mock_mcp_client):
        mock_mcp_client.call_tool.return_value = {
            "success": True,
            "result": "found it",
        }
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        result = await svc.execute_tools([
            _fc("add_memory", {"content": "save"}),
            _fc("web_search", {"q": "hello"}),
            _fc("store_memory", {"content": "also save"}),
        ])

        # Only 1 immediate call should be made
        assert mock_mcp_client.call_tool.await_count == 1

        # 2 deferred + 1 immediate = 3 results
        assert len(result.results) == 3
        assert len(result.deferred_tools) == 2

        # Deferred results come first in order
        assert result.results[0].name == "add_memory"
        assert result.results[0].output == "(deferred)"
        assert result.results[1].name == "store_memory"
        assert result.results[1].output == "(deferred)"
        # Then immediate
        assert result.results[2].name == "web_search"
        assert result.results[2].output == "found it"

    async def test_multiple_immediate_parallel(self, mock_mcp_client):
        """Multiple immediate tools should all execute (via asyncio.gather)."""
        call_count = 0

        async def side_effect(name, args):
            nonlocal call_count
            call_count += 1
            return {"success": True, "result": f"result-{call_count}"}

        mock_mcp_client.call_tool.side_effect = side_effect
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        result = await svc.execute_tools([
            _fc("tool_a"),
            _fc("tool_b"),
            _fc("tool_c"),
        ])
        assert len(result.results) == 3
        assert all(r.success for r in result.results)
        assert call_count == 3


# ── _execute_single ──────────────────────────────────────────────────────


class TestExecuteSingle:
    async def test_success(self, mock_mcp_client):
        mock_mcp_client.call_tool.return_value = {
            "success": True,
            "result": "tool output",
        }
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        tool_result, output_line = await svc._execute_single("my_tool", {"key": "val"})

        assert tool_result.name == "my_tool"
        assert tool_result.success is True
        assert tool_result.output == "tool output"
        assert tool_result.error is None
        assert "my_tool" in output_line

    async def test_exception(self, mock_mcp_client):
        mock_mcp_client.call_tool.side_effect = RuntimeError("connection timeout")
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        tool_result, output_line = await svc._execute_single("bad_tool", {})

        assert tool_result.name == "bad_tool"
        assert tool_result.success is False
        assert tool_result.output == ""
        assert "connection timeout" in tool_result.error
        assert "Error" in output_line

    async def test_missing_success_key(self, mock_mcp_client):
        """If 'success' key is missing, .get defaults to False."""
        mock_mcp_client.call_tool.return_value = {"result": "partial"}
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        tool_result, _ = await svc._execute_single("tool_x", {})

        assert tool_result.success is False
        assert tool_result.output == "partial"

    async def test_missing_result_key(self, mock_mcp_client):
        """If 'result' key is missing, output defaults to empty string."""
        mock_mcp_client.call_tool.return_value = {"success": True}
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        tool_result, _ = await svc._execute_single("tool_y", {})

        assert tool_result.success is True
        assert tool_result.output == ""


# ── execute_deferred_tools ───────────────────────────────────────────────


class TestExecuteDeferredTools:
    async def test_success(self, mock_mcp_client):
        mock_mcp_client.call_tool.return_value = {"success": True}
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        await svc.execute_deferred_tools([
            ("store_memory", {"content": "a"}),
            ("add_memory", {"content": "b"}),
        ])
        assert mock_mcp_client.call_tool.await_count == 2

    async def test_no_client(self):
        svc = ToolExecutionService(mcp_client=None)
        # Should return without error
        await svc.execute_deferred_tools([("store_memory", {"content": "x"})])

    async def test_failure_continues(self, mock_mcp_client):
        """If one deferred tool fails, the rest still execute."""
        mock_mcp_client.call_tool.side_effect = [
            RuntimeError("boom"),
            {"success": True},
        ]
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        # Should not raise
        await svc.execute_deferred_tools([
            ("store_memory", {"content": "a"}),
            ("add_memory", {"content": "b"}),
        ])
        assert mock_mcp_client.call_tool.await_count == 2

    async def test_unsuccessful_result_logged(self, mock_mcp_client):
        """A tool returning success=False should not raise."""
        mock_mcp_client.call_tool.return_value = {
            "success": False,
            "error": "quota exceeded",
        }
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        await svc.execute_deferred_tools([("store_memory", {"content": "x"})])
        assert mock_mcp_client.call_tool.await_count == 1

    async def test_empty_list(self, mock_mcp_client):
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        await svc.execute_deferred_tools([])
        mock_mcp_client.call_tool.assert_not_awaited()


# ── spawn_deferred_task ──────────────────────────────────────────────────


class TestSpawnDeferredTask:
    async def test_no_tools_returns_none(self, mock_mcp_client):
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        bg = []
        result = svc.spawn_deferred_task([], bg)
        assert result is None
        assert bg == []

    async def test_creates_task(self, mock_mcp_client):
        mock_mcp_client.call_tool.return_value = {"success": True}
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        bg = []
        task = svc.spawn_deferred_task(
            [("store_memory", {"content": "x"})],
            bg,
        )

        assert task is not None
        assert isinstance(task, asyncio.Task)
        # Task should be added to background list
        assert task in bg

        # Let it finish
        await task
        # After completion, done callback removes it from bg
        # Allow one event-loop tick for the callback
        await asyncio.sleep(0)
        assert task not in bg

    async def test_done_callback_invoked(self, mock_mcp_client):
        mock_mcp_client.call_tool.return_value = {"success": True}
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        bg = []
        callback = MagicMock()

        task = svc.spawn_deferred_task(
            [("store_memory", {"content": "y"})],
            bg,
            done_callback=callback,
        )
        await task
        await asyncio.sleep(0)

        callback.assert_called_once_with(task)

    async def test_done_callback_on_error(self, mock_mcp_client):
        """Even if deferred execution encounters an error internally,
        the task itself should complete without raising (errors are caught)."""
        mock_mcp_client.call_tool.side_effect = RuntimeError("fail")
        svc = ToolExecutionService(mcp_client=mock_mcp_client)
        bg = []
        callback = MagicMock()

        task = svc.spawn_deferred_task(
            [("store_memory", {"content": "z"})],
            bg,
            done_callback=callback,
        )
        await task
        await asyncio.sleep(0)

        # Callback still fires (exception inside execute_deferred_tools is caught)
        callback.assert_called_once_with(task)
        assert task not in bg


# ── Dataclass tests ──────────────────────────────────────────────────────


class TestDataclasses:
    def test_tool_result_defaults(self):
        r = ToolResult(name="t", output="o", success=True)
        assert r.error is None

    def test_tool_result_with_error(self):
        r = ToolResult(name="t", output="", success=False, error="bad")
        assert r.error == "bad"

    def test_tool_execution_result_defaults(self):
        r = ToolExecutionResult()
        assert r.results == []
        assert r.deferred_tools == []
        assert r.observation == ""
