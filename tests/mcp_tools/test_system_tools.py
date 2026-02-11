"""Tests for backend.core.mcp_tools.system_tools.

Covers run_command, search_codebase, search_codebase_regex,
read_system_logs, list_available_logs, analyze_log_errors,
check_task_status, tool_metrics, and system_status.
"""

import subprocess
from dataclasses import dataclass, field
from typing import Optional, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------


class TestRunCommand:
    """Tests for the run_command tool handler."""

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.system_tools import run_command

        self.run_command = run_command

    async def test_empty_command_returns_error(self):
        result = await self.run_command({"command": ""})
        assert len(result) == 1
        assert "command parameter is required" in result[0].text

    async def test_missing_command_key_returns_error(self):
        result = await self.run_command({})
        assert "command parameter is required" in result[0].text

    async def test_timeout_below_min_returns_error(self):
        result = await self.run_command({"command": "echo hi", "timeout": 0})
        assert "timeout must be between 1 and 180" in result[0].text

    async def test_timeout_above_max_returns_error(self):
        result = await self.run_command({"command": "echo hi", "timeout": 999})
        assert "timeout must be between 1 and 180" in result[0].text

    async def test_timeout_non_numeric_returns_error(self):
        result = await self.run_command({"command": "echo hi", "timeout": "fast"})
        assert "timeout must be between 1 and 180" in result[0].text

    @patch("backend.core.mcp_tools.command_tools.asyncio.to_thread")
    async def test_successful_command(self, mock_to_thread):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b"hello world"
        proc.stderr = b""
        mock_to_thread.return_value = proc

        result = await self.run_command({"command": "echo hello world"})
        text = result[0].text
        assert "Success" in text
        assert "hello world" in text

    @patch("backend.core.mcp_tools.command_tools.asyncio.to_thread")
    async def test_failed_command_nonzero_exit(self, mock_to_thread):
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = b""
        proc.stderr = b"not found"
        mock_to_thread.return_value = proc

        result = await self.run_command({"command": "false"})
        text = result[0].text
        assert "Failed" in text
        assert "Exit: 1" in text
        assert "not found" in text

    @patch("backend.core.mcp_tools.command_tools.asyncio.to_thread")
    async def test_command_with_stdout_and_stderr(self, mock_to_thread):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b"output line"
        proc.stderr = b"warning line"
        mock_to_thread.return_value = proc

        result = await self.run_command({"command": "mixed"})
        text = result[0].text
        assert "[Stdout]" in text
        assert "output line" in text
        assert "[Stderr]" in text
        assert "warning line" in text

    @patch("backend.core.mcp_tools.command_tools.asyncio.to_thread")
    async def test_command_timeout_expired(self, mock_to_thread):
        mock_to_thread.side_effect = subprocess.TimeoutExpired(cmd="sleep", timeout=5)

        result = await self.run_command({"command": "sleep 999", "timeout": 5})
        assert "Timed out" in result[0].text

    @patch("backend.core.mcp_tools.command_tools.asyncio.to_thread")
    async def test_command_generic_exception(self, mock_to_thread):
        mock_to_thread.side_effect = OSError("No such file")

        result = await self.run_command({"command": "badcmd"})
        assert "Execution Error" in result[0].text
        assert "No such file" in result[0].text

    @patch("backend.core.mcp_tools.command_tools.asyncio.to_thread")
    async def test_custom_cwd_is_forwarded(self, mock_to_thread):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b"ok"
        proc.stderr = b""
        mock_to_thread.return_value = proc

        await self.run_command({"command": "ls", "cwd": "/tmp"})
        call_kwargs = mock_to_thread.call_args
        # subprocess.run is the second positional arg
        assert call_kwargs.kwargs["cwd"] == "/tmp" or "/tmp" in str(call_kwargs)

    @patch("backend.core.mcp_tools.command_tools.asyncio.to_thread")
    async def test_korean_cp949_stdout_decoded(self, mock_to_thread):
        """Verify safe_decode handles cp949 bytes in stdout."""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "한국어".encode("cp949")
        proc.stderr = b""
        mock_to_thread.return_value = proc

        result = await self.run_command({"command": "echo"})
        text = result[0].text
        assert "한국어" in text


# ---------------------------------------------------------------------------
# search_codebase_tool
# ---------------------------------------------------------------------------


class TestSearchCodebaseTool:
    """Tests for the search_codebase MCP handler."""

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.system_tools import search_codebase_tool

        self.search_codebase_tool = search_codebase_tool

    async def test_empty_keyword_returns_error(self):
        result = await self.search_codebase_tool({"keyword": ""})
        assert "keyword is required" in result[0].text

    async def test_missing_keyword_returns_error(self):
        result = await self.search_codebase_tool({})
        assert "keyword is required" in result[0].text

    async def test_invalid_max_results_zero(self):
        result = await self.search_codebase_tool({"keyword": "x", "max_results": 0})
        assert "max_results must be between 1 and 100" in result[0].text

    async def test_invalid_max_results_too_high(self):
        result = await self.search_codebase_tool({"keyword": "x", "max_results": 200})
        assert "max_results must be between 1 and 100" in result[0].text

    async def test_successful_search(self):
        """Patch the inner imports and verify formatting."""
        from backend.core.tools.system_observer import SearchResult, SearchMatch

        mock_result = SearchResult(
            success=True,
            matches=[
                SearchMatch(
                    file_path="core/main.py",
                    line_number=10,
                    content="def process_request():",
                )
            ],
            total_matches=1,
            files_searched=5,
        )

        with (
            patch(
                "backend.core.tools.system_observer.search_codebase",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "backend.core.tools.system_observer.format_search_results",
                return_value="Found 1 matches in 5 files",
            ),
        ):
            result = await self.search_codebase_tool({"keyword": "process_request"})
            assert "Found 1 matches" in result[0].text

    async def test_search_exception_returns_error(self):
        with patch(
            "backend.core.tools.system_observer.search_codebase",
            new_callable=AsyncMock,
            side_effect=RuntimeError("disk full"),
        ):
            result = await self.search_codebase_tool({"keyword": "hello"})
            assert "Search Error" in result[0].text
            assert "disk full" in result[0].text


# ---------------------------------------------------------------------------
# search_codebase_regex_tool
# ---------------------------------------------------------------------------


class TestSearchCodebaseRegexTool:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.system_tools import search_codebase_regex_tool

        self.search_regex = search_codebase_regex_tool

    async def test_empty_pattern_returns_error(self):
        result = await self.search_regex({"pattern": ""})
        assert "pattern is required" in result[0].text

    async def test_missing_pattern_returns_error(self):
        result = await self.search_regex({})
        assert "pattern is required" in result[0].text

    async def test_successful_regex_search(self):
        from backend.core.tools.system_observer import SearchResult

        mock_result = SearchResult(
            success=True, matches=[], total_matches=0, files_searched=3
        )

        with (
            patch(
                "backend.core.tools.system_observer.search_codebase_regex",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "backend.core.tools.system_observer.format_search_results",
                return_value="No matches found (searched 3 files)",
            ),
        ):
            result = await self.search_regex({"pattern": r"def \w+\("})
            assert "No matches" in result[0].text or "searched" in result[0].text

    async def test_regex_exception_returns_error(self):
        with patch(
            "backend.core.tools.system_observer.search_codebase_regex",
            new_callable=AsyncMock,
            side_effect=ValueError("bad regex"),
        ):
            result = await self.search_regex({"pattern": "test"})
            assert "Regex Search Error" in result[0].text


# ---------------------------------------------------------------------------
# read_system_logs
# ---------------------------------------------------------------------------


class TestReadSystemLogs:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.system_tools import read_system_logs

        self.read_system_logs = read_system_logs

    async def test_invalid_lines_zero(self):
        result = await self.read_system_logs({"lines": 0})
        assert "lines must be between 1 and 1000" in result[0].text

    async def test_invalid_lines_too_high(self):
        result = await self.read_system_logs({"lines": 9999})
        assert "lines must be between 1 and 1000" in result[0].text

    async def test_invalid_lines_non_int(self):
        result = await self.read_system_logs({"lines": "many"})
        assert "lines must be between 1 and 1000" in result[0].text

    async def test_successful_log_read(self):
        from backend.core.tools.system_observer import LogReadResult

        mock_result = LogReadResult(
            success=True,
            content="2024-01-01 INFO some log line",
            lines_read=1,
            file_path="/var/log/backend.log",
        )

        with patch(
            "backend.core.tools.system_observer.read_logs",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.read_system_logs({})
            text = result[0].text
            assert "Log:" in text
            assert "1 lines" in text
            assert "some log line" in text

    async def test_log_read_with_filter(self):
        from backend.core.tools.system_observer import LogReadResult

        mock_result = LogReadResult(
            success=True,
            content="2024-01-01 ERROR failure",
            lines_read=1,
            file_path="/var/log/backend.log",
            filter_applied="ERROR",
        )

        with patch(
            "backend.core.tools.system_observer.read_logs",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.read_system_logs(
                {"filter_keyword": "ERROR"}
            )
            text = result[0].text
            assert "filter: ERROR" in text

    async def test_log_read_failure(self):
        from backend.core.tools.system_observer import LogReadResult

        mock_result = LogReadResult(
            success=False,
            content="",
            lines_read=0,
            file_path="missing.log",
            error="File not found",
        )

        with patch(
            "backend.core.tools.system_observer.read_logs",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.read_system_logs({"log_file": "missing.log"})
            assert "Log Error" in result[0].text
            assert "File not found" in result[0].text

    async def test_log_read_exception(self):
        with patch(
            "backend.core.tools.system_observer.read_logs",
            new_callable=AsyncMock,
            side_effect=PermissionError("access denied"),
        ):
            result = await self.read_system_logs({})
            assert "Log Read Error" in result[0].text


# ---------------------------------------------------------------------------
# list_available_logs_tool
# ---------------------------------------------------------------------------


class TestListAvailableLogs:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.system_tools import list_available_logs_tool

        self.list_logs = list_available_logs_tool

    async def test_successful_list(self):
        mock_result = {
            "success": True,
            "logs": [
                {"name": "backend.log", "size_kb": 123.45},
                {"name": "mcp.log", "size_kb": 67.89},
            ],
            "aliases": {"backend": "backend.log", "mcp": "mcp.log"},
        }

        with patch(
            "backend.core.tools.system_observer.list_available_logs",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.list_logs({})
            text = result[0].text
            assert "Available Log Files" in text
            assert "backend.log" in text
            assert "mcp.log" in text
            assert "Aliases" in text

    async def test_failed_list(self):
        mock_result = {"success": False}

        with patch(
            "backend.core.tools.system_observer.list_available_logs",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.list_logs({})
            assert "Failed to list logs" in result[0].text

    async def test_exception_returns_error(self):
        with patch(
            "backend.core.tools.system_observer.list_available_logs",
            new_callable=AsyncMock,
            side_effect=OSError("disk error"),
        ):
            result = await self.list_logs({})
            assert "Error" in result[0].text


# ---------------------------------------------------------------------------
# analyze_log_errors
# ---------------------------------------------------------------------------


class TestAnalyzeLogErrors:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.system_tools import analyze_log_errors

        self.analyze = analyze_log_errors

    async def test_invalid_lines_zero(self):
        result = await self.analyze({"lines": 0})
        assert "lines must be between 1 and 5000" in result[0].text

    async def test_invalid_lines_too_high(self):
        result = await self.analyze({"lines": 10000})
        assert "lines must be between 1 and 5000" in result[0].text

    async def test_successful_analysis_with_errors(self):
        mock_result = {
            "success": True,
            "errors": ["ERROR: connection lost", "ERROR: timeout"],
            "warnings": ["WARNING: slow query"],
            "summary": "2 errors, 1 warning",
        }

        with patch(
            "backend.core.tools.system_observer.analyze_recent_errors",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.analyze({})
            text = result[0].text
            assert "Error Analysis" in text
            assert "Errors (2)" in text
            assert "Warnings (1)" in text
            assert "Summary" in text

    async def test_analysis_no_errors(self):
        mock_result = {
            "success": True,
            "errors": [],
            "warnings": [],
            "summary": "",
        }

        with patch(
            "backend.core.tools.system_observer.analyze_recent_errors",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.analyze({})
            text = result[0].text
            assert "No errors or warnings found" in text

    async def test_analysis_failure(self):
        mock_result = {"success": False, "error": "File not readable"}

        with patch(
            "backend.core.tools.system_observer.analyze_recent_errors",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.analyze({})
            assert "Analysis failed" in result[0].text

    async def test_analysis_exception(self):
        with patch(
            "backend.core.tools.system_observer.analyze_recent_errors",
            new_callable=AsyncMock,
            side_effect=RuntimeError("crash"),
        ):
            result = await self.analyze({})
            assert "Analysis Error" in result[0].text


# ---------------------------------------------------------------------------
# check_task_status
# ---------------------------------------------------------------------------


class TestCheckTaskStatus:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.system_tools import check_task_status

        self.check = check_task_status

    async def test_no_task_id_and_no_list_returns_error(self):
        result = await self.check({})
        assert "task_id required" in result[0].text

    async def test_list_active_empty(self):
        mock_tracker = MagicMock()
        mock_tracker.get_all_tasks_summary.return_value = {
            "total": 0,
            "by_status": {},
            "active": [],
        }

        with patch(
            "backend.core.utils.task_tracker.get_task_tracker",
            return_value=mock_tracker,
        ):
            result = await self.check({"list_active": True})
            text = result[0].text
            assert "Task Summary" in text
            assert "No active tasks" in text

    async def test_list_active_with_tasks(self):
        mock_tracker = MagicMock()
        mock_tracker.get_all_tasks_summary.return_value = {
            "total": 2,
            "by_status": {"running": 1, "completed": 1},
            "active": [
                {
                    "task_id": "abc123",
                    "name": "Research",
                    "progress": 0.5,
                    "progress_message": "Fetching sources",
                }
            ],
        }

        with patch(
            "backend.core.utils.task_tracker.get_task_tracker",
            return_value=mock_tracker,
        ):
            result = await self.check({"list_active": True})
            text = result[0].text
            assert "Total tracked: 2" in text
            assert "abc123" in text
            assert "Research" in text
            assert "50%" in text

    async def test_specific_task_found(self):
        mock_tracker = MagicMock()
        mock_tracker.get_task_dict.return_value = {
            "name": "Deep Research",
            "status": "running",
            "progress": 0.75,
            "progress_message": "Analyzing",
            "duration_seconds": 42.5,
            "error": None,
            "has_result": False,
        }

        with patch(
            "backend.core.utils.task_tracker.get_task_tracker",
            return_value=mock_tracker,
        ):
            result = await self.check({"task_id": "xyz"})
            text = result[0].text
            assert "Deep Research" in text
            assert "75%" in text
            assert "42.5s" in text

    async def test_specific_task_not_found(self):
        mock_tracker = MagicMock()
        mock_tracker.get_task_dict.return_value = None

        with patch(
            "backend.core.utils.task_tracker.get_task_tracker",
            return_value=mock_tracker,
        ):
            result = await self.check({"task_id": "missing"})
            assert "Task not found" in result[0].text

    async def test_specific_task_with_error_and_result(self):
        mock_tracker = MagicMock()
        mock_tracker.get_task_dict.return_value = {
            "name": "FailedTask",
            "status": "failed",
            "progress": 1.0,
            "progress_message": None,
            "duration_seconds": 10.0,
            "error": "API limit exceeded",
            "has_result": True,
        }

        with patch(
            "backend.core.utils.task_tracker.get_task_tracker",
            return_value=mock_tracker,
        ):
            result = await self.check({"task_id": "err1"})
            text = result[0].text
            assert "API limit exceeded" in text
            assert "Result: Available" in text

    async def test_check_exception(self):
        with patch(
            "backend.core.utils.task_tracker.get_task_tracker",
            side_effect=ImportError("no module"),
        ):
            result = await self.check({"task_id": "x"})
            assert "Error" in result[0].text


# ---------------------------------------------------------------------------
# tool_metrics_tool
# ---------------------------------------------------------------------------


class TestToolMetricsTool:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.system_tools import tool_metrics_tool

        self.metrics = tool_metrics_tool

    async def test_specific_tool_metrics(self):
        mock_metrics = {
            "call_count": 10,
            "success_count": 9,
            "success_rate": "90.0%",
            "error_count": 1,
            "avg_duration_ms": 45.2,
            "last_error": "timeout",
        }

        with patch(
            "backend.core.mcp_tools.get_tool_metrics",
            return_value=mock_metrics,
        ):
            result = await self.metrics({"tool_name": "run_command"})
            text = result[0].text
            assert "Calls: 10" in text
            assert "Success: 9" in text
            assert "Avg Duration: 45.2ms" in text

    async def test_tool_not_found(self):
        with patch(
            "backend.core.mcp_tools.get_tool_metrics",
            return_value=None,
        ):
            result = await self.metrics({"tool_name": "nonexistent"})
            assert "No metrics found" in result[0].text

    async def test_all_metrics_empty(self):
        with patch(
            "backend.core.mcp_tools.get_all_metrics",
            return_value={},
        ):
            result = await self.metrics({})
            assert "No tool metrics recorded" in result[0].text

    async def test_all_metrics_with_data(self):
        mock_all = {
            "run_command": {
                "call_count": 50,
                "success_rate": "98.0%",
                "avg_duration_ms": 123,
            },
            "search_codebase": {
                "call_count": 30,
                "success_rate": "100.0%",
                "avg_duration_ms": 45,
            },
        }

        with patch(
            "backend.core.mcp_tools.get_all_metrics",
            return_value=mock_all,
        ):
            result = await self.metrics({})
            text = result[0].text
            assert "Tool Metrics Summary" in text
            assert "run_command" in text
            assert "search_codebase" in text

    async def test_metrics_exception(self):
        with patch(
            "backend.core.mcp_tools.get_tool_metrics",
            side_effect=RuntimeError("db error"),
        ):
            result = await self.metrics({"tool_name": "x"})
            assert "Error" in result[0].text


# ---------------------------------------------------------------------------
# system_status_tool
# ---------------------------------------------------------------------------


class TestSystemStatusTool:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.system_tools import system_status_tool

        self.status = system_status_tool

    async def test_system_status_success(self):
        mock_circuits = {
            "hass": {"state": "closed", "timeout_remaining": 0},
            "gemini": {"state": "open", "timeout_remaining": 30},
        }
        mock_caches = {
            "llm_cache": {"size": 10, "maxsize": 100, "hit_rate": "50.0%"},
        }
        mock_tracker = MagicMock()
        mock_tracker.list_active_tasks.return_value = []
        mock_all_metrics = {
            "run_command": {"call_count": 5, "error_count": 0},
        }

        with (
            patch(
                "backend.core.utils.get_all_circuit_status",
                return_value=mock_circuits,
            ),
            patch(
                "backend.core.utils.get_all_cache_stats",
                return_value=mock_caches,
            ),
            patch(
                "backend.core.utils.task_tracker.get_task_tracker",
                return_value=mock_tracker,
            ),
            patch(
                "backend.core.mcp_tools.get_all_metrics",
                return_value=mock_all_metrics,
            ),
        ):
            result = await self.status({})
            text = result[0].text
            assert "System Status" in text
            assert "Circuit Breakers" in text
            assert "hass" in text
            assert "Caches" in text
            assert "llm_cache" in text
            assert "Tool Usage: 5 calls" in text

    async def test_system_status_exception(self):
        with patch(
            "backend.core.utils.get_all_circuit_status",
            side_effect=RuntimeError("boom"),
        ):
            result = await self.status({})
            assert "Error" in result[0].text
