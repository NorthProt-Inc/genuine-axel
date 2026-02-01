import asyncio
import subprocess
from typing import Any, Sequence
from mcp.types import TextContent
from . import register_tool
from backend.config import PROJECT_ROOT as AXEL_ROOT
from backend.core.logging.logging import get_logger

_log = get_logger("mcp.system_tools")

@register_tool(
    "run_command",
    category="system",
    description="""Execute a shell command on the host system.

CAPABILITIES:
- Full bash shell access
- sudo available WITHOUT password (NOPASSWD configured)
- Can install packages, manage services, modify system files

COMMON USES:
- sudo systemctl restart/stop/start <service>
- sudo apt install <package>
- git operations
- File operations outside project directory
- Process management (ps, kill, etc.)

CAUTION: You have full system access. Be careful with destructive commands.""",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to execute (sudo available without password)"},
            "cwd": {"type": "string", "description": "Working directory (default: project root)"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120)", "default": 120}
        },
        "required": ["command"]
    }
)
async def run_command(arguments: dict[str, Any]) -> Sequence[TextContent]:

    command = arguments.get("command", "")
    cwd = arguments.get("cwd", str(AXEL_ROOT))
    timeout = arguments.get("timeout", 120)
    _log.debug("TOOL invoke", fn="run_command", cmd=command[:80] if command else None, cwd=cwd[:40], timeout=timeout)

    if not command:
        _log.warning("TOOL fail", fn="run_command", err="command parameter required")
        return [TextContent(type="text", text="Error: command parameter is required")]

    if not isinstance(timeout, (int, float)) or timeout < 1 or timeout > 180:
        _log.warning("TOOL fail", fn="run_command", err="invalid timeout")
        return [TextContent(type="text", text="Error: timeout must be between 1 and 180 seconds")]

    try:

        result = await asyncio.to_thread(
            subprocess.run,
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=False,
            timeout=timeout
        )

        def safe_decode(data: bytes) -> str:

            modes = ["cp949", "utf-8", "latin-1"]
            for mode in modes:
                try:
                    return data.decode(mode)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="replace")

        stdout_str = safe_decode(result.stdout)
        stderr_str = safe_decode(result.stderr)

        output_parts = []
        if result.returncode == 0:
            _log.info("TOOL ok", fn="run_command", exit_code=0, stdout_len=len(stdout_str))
            output_parts.append(f"✓ Success (Exit: 0)")
        else:
            _log.warning("TOOL partial", fn="run_command", exit_code=result.returncode)
            output_parts.append(f"✗ Failed (Exit: {result.returncode})")

        if stdout_str.strip():
            output_parts.append(f"\n[Stdout]\n{stdout_str.strip()}")
        if stderr_str.strip():
            output_parts.append(f"\n[Stderr]\n{stderr_str.strip()}")

        return [TextContent(type="text", text="\n".join(output_parts))]

    except subprocess.TimeoutExpired:
        _log.warning("TOOL fail", fn="run_command", err="command timeout", timeout_sec=timeout)
        return [TextContent(type="text", text=f"✗ Timed out after {timeout}s")]
    except Exception as e:
        _log.error("TOOL fail", fn="run_command", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Execution Error: {str(e)}")]

@register_tool(
    "search_codebase",
    category="system",
    description="Search for keywords/patterns across Axel's codebase. Useful for finding function definitions, error patterns, or understanding how specific features are implemented.",
    input_schema={
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "String to search for (e.g., 'def process_', 'class ChatHandler', 'ERROR')"},
            "file_pattern": {"type": "string", "description": "File pattern to search (default: '*.py'). Use '*' for all files.", "default": "*.py"},
            "case_sensitive": {"type": "boolean", "description": "Whether search is case-sensitive (default: false)", "default": False},
            "max_results": {"type": "integer", "description": "Maximum results to return (default: 50)", "default": 50, "maximum": 100}
        },
        "required": ["keyword"]
    }
)
async def search_codebase_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:

    keyword = arguments.get("keyword", "")
    file_pattern = arguments.get("file_pattern", "*.py")
    case_sensitive = arguments.get("case_sensitive", False)
    max_results = arguments.get("max_results", 50)
    _log.debug("TOOL invoke", fn="search_codebase", keyword=keyword[:50] if keyword else None, pattern=file_pattern)

    if not keyword:
        _log.warning("TOOL fail", fn="search_codebase", err="keyword required")
        return [TextContent(type="text", text="✗ Error: keyword is required")]

    if not isinstance(max_results, int) or max_results < 1 or max_results > 100:
        _log.warning("TOOL fail", fn="search_codebase", err="invalid max_results")
        return [TextContent(type="text", text="Error: max_results must be between 1 and 100")]

    try:
        from backend.core.tools.system_observer import (
            search_codebase,
            format_search_results
        )

        result = await search_codebase(
            keyword=keyword,
            file_pattern=file_pattern,
            case_sensitive=case_sensitive,
            max_results=max_results
        )

        _log.info("TOOL ok", fn="search_codebase", res_len=result.get('total_matches', 0) if isinstance(result, dict) else 0)
        return [TextContent(type="text", text=format_search_results(result))]

    except Exception as e:
        _log.error("TOOL fail", fn="search_codebase", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Search Error: {str(e)}")]

@register_tool(
    "search_codebase_regex",
    category="system",
    description=r"Search codebase using regex patterns (advanced). Use for complex pattern matching like 'def \w+\(' to find all function definitions.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "file_pattern": {"type": "string", "description": "File pattern to search (default: '*.py')", "default": "*.py"},
            "case_sensitive": {"type": "boolean", "description": "Whether search is case-sensitive (default: false)", "default": False}
        },
        "required": ["pattern"]
    }
)
async def search_codebase_regex_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:

    pattern = arguments.get("pattern", "")
    file_pattern = arguments.get("file_pattern", "*.py")
    case_sensitive = arguments.get("case_sensitive", False)
    _log.debug("TOOL invoke", fn="search_codebase_regex", pattern=pattern[:50] if pattern else None, file_pattern=file_pattern)

    if not pattern:
        _log.warning("TOOL fail", fn="search_codebase_regex", err="pattern required")
        return [TextContent(type="text", text="✗ Error: pattern is required")]

    try:
        from backend.core.tools.system_observer import (
            search_codebase_regex,
            format_search_results
        )

        result = await search_codebase_regex(
            pattern=pattern,
            file_pattern=file_pattern,
            case_sensitive=case_sensitive
        )

        _log.info("TOOL ok", fn="search_codebase_regex", res_len=result.get('total_matches', 0) if isinstance(result, dict) else 0)
        return [TextContent(type="text", text=format_search_results(result))]

    except Exception as e:
        _log.error("TOOL fail", fn="search_codebase_regex", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Regex Search Error: {str(e)}")]

@register_tool(
    "read_system_logs",
    category="system",
    description="Read Axel's backend logs for self-debugging. Allows reading last N lines with optional keyword filtering. Security: Only reads from designated log directory.",
    input_schema={
        "type": "object",
        "properties": {
            "log_file": {
                "type": "string",
                "description": "Log file to read: 'backend' (default), 'backend_error', 'mcp', 'mcp_error', 'main', or full filename",
                "default": "backend.log"
            },
            "lines": {
                "type": "integer",
                "description": "Number of lines to read from the end (default: 50, max: 1000)",
                "default": 50,
                "minimum": 1,
                "maximum": 1000
            },
            "filter_keyword": {
                "type": "string",
                "description": "Optional keyword to filter logs (e.g., 'ERROR', 'WARNING', 'request_id')"
            }
        },
        "required": []
    }
)
async def read_system_logs(arguments: dict[str, Any]) -> Sequence[TextContent]:

    log_file = arguments.get("log_file", "backend.log")
    lines = arguments.get("lines", 50)
    filter_keyword = arguments.get("filter_keyword")
    _log.debug("TOOL invoke", fn="read_system_logs", log_file=log_file, lines=lines, filter_keyword=filter_keyword)

    if not isinstance(lines, int) or lines < 1 or lines > 1000:
        _log.warning("TOOL fail", fn="read_system_logs", err="invalid lines")
        return [TextContent(type="text", text="Error: lines must be between 1 and 1000")]

    try:
        from backend.core.tools.system_observer import read_logs

        result = await read_logs(
            log_file=log_file,
            lines=lines,
            filter_keyword=filter_keyword
        )

        if result.success:
            _log.info("TOOL ok", fn="read_system_logs", log_file=log_file, lines_read=result.lines_read)
            header = f"✓ Log: {result.file_path} ({result.lines_read} lines)"
            if result.filter_applied:
                header += f" [filter: {result.filter_applied}]"
            return [TextContent(type="text", text=f"{header}\n{'─' * 50}\n{result.content}")]
        else:
            _log.warning("TOOL partial", fn="read_system_logs", err=result.error[:100] if result.error else None)
            return [TextContent(type="text", text=f"✗ Log Error: {result.error}")]

    except Exception as e:
        _log.error("TOOL fail", fn="read_system_logs", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Log Read Error: {str(e)}")]

@register_tool(
    "list_available_logs",
    category="system",
    description="List all log files available for Axel to read. Use this to discover what logs exist.",
    input_schema={
        "type": "object",
        "properties": {},
        "required": []
    }
)
async def list_available_logs_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:

    _log.debug("TOOL invoke", fn="list_available_logs")

    try:
        from backend.core.tools.system_observer import list_available_logs

        result = await list_available_logs()

        if result.get("success"):
            logs = result.get("logs", [])
            aliases = result.get("aliases", {})

            _log.info("TOOL ok", fn="list_available_logs", res_len=len(logs))
            output = ["✓ Available Log Files:", ""]
            for log in logs:
                output.append(f"  • {log['name']} ({log['size_kb']} KB)")

            output.append("")
            output.append("Aliases:")
            for alias, filename in aliases.items():
                output.append(f"  • {alias} -> {filename}")

            return [TextContent(type="text", text="\n".join(output))]
        else:
            _log.warning("TOOL partial", fn="list_available_logs", err="failed to list logs")
            return [TextContent(type="text", text="✗ Failed to list logs")]

    except Exception as e:
        _log.error("TOOL fail", fn="list_available_logs", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Error: {str(e)}")]

@register_tool(
    "analyze_log_errors",
    category="system",
    description="Analyze recent logs for errors and warnings. Returns categorized error summary.",
    input_schema={
        "type": "object",
        "properties": {
            "log_file": {
                "type": "string",
                "description": "Log file to analyze (default: backend.log)",
                "default": "backend.log"
            },
            "lines": {
                "type": "integer",
                "description": "Number of recent lines to analyze (default: 500)",
                "default": 500
            }
        },
        "required": []
    }
)
async def analyze_log_errors(arguments: dict[str, Any]) -> Sequence[TextContent]:

    log_file = arguments.get("log_file", "backend.log")
    lines = arguments.get("lines", 500)
    _log.debug("TOOL invoke", fn="analyze_log_errors", log_file=log_file, lines=lines)

    if not isinstance(lines, int) or lines < 1 or lines > 5000:
        _log.warning("TOOL fail", fn="analyze_log_errors", err="invalid lines")
        return [TextContent(type="text", text="Error: lines must be between 1 and 5000")]

    try:
        from backend.core.tools.system_observer import analyze_recent_errors

        result = await analyze_recent_errors(
            log_file=log_file,
            lines=lines
        )

        if result.get("success"):
            errors = result.get("errors", [])
            warnings = result.get("warnings", [])
            summary = result.get("summary", "")

            _log.info("TOOL ok", fn="analyze_log_errors", err_cnt=len(errors), warn_cnt=len(warnings))
            output = [f"✓ Error Analysis ({log_file})", ""]

            if errors:
                output.append(f"Errors ({len(errors)}):")
                for err in errors[:10]:
                    output.append(f"  - {err}")

            if warnings:
                output.append(f"\nWarnings ({len(warnings)}):")
                for warn in warnings[:10]:
                    output.append(f"  - {warn}")

            if summary:
                output.append(f"\nSummary:\n{summary}")

            if not errors and not warnings:
                output.append("No errors or warnings found.")

            return [TextContent(type="text", text="\n".join(output))]
        else:
            _log.warning("TOOL partial", fn="analyze_log_errors", err=result.get('error', 'unknown')[:100])
            return [TextContent(type="text", text=f"✗ Analysis failed: {result.get('error')}")]

    except Exception as e:
        _log.error("TOOL fail", fn="analyze_log_errors", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Analysis Error: {str(e)}")]


@register_tool(
    "check_task_status",
    category="system",
    description="Check the status of an async task by ID. Use this to monitor long-running operations like Google Deep Research.",
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID returned when starting an async operation"
            },
            "list_active": {
                "type": "boolean",
                "description": "If true, list all active tasks instead of checking specific task_id",
                "default": False
            }
        },
        "required": []
    }
)
async def check_task_status(arguments: dict[str, Any]) -> Sequence[TextContent]:

    task_id = arguments.get("task_id")
    list_active = arguments.get("list_active", False)
    _log.debug("TOOL invoke", fn="check_task_status", task_id=task_id, list_active=list_active)

    try:
        from backend.core.utils.task_tracker import get_task_tracker

        tracker = get_task_tracker()

        if list_active:
            summary = tracker.get_all_tasks_summary()
            output = ["✓ Task Summary:", ""]
            output.append(f"Total tracked: {summary['total']}")

            if summary['by_status']:
                output.append("\nBy status:")
                for status, count in summary['by_status'].items():
                    output.append(f"  • {status}: {count}")

            if summary['active']:
                output.append("\nActive tasks:")
                for task in summary['active']:
                    progress = f"{task['progress']:.0%}" if task['progress'] else "0%"
                    output.append(f"  • [{task['task_id']}] {task['name']} - {progress}")
                    if task['progress_message']:
                        output.append(f"      {task['progress_message']}")
            else:
                output.append("\nNo active tasks.")

            _log.info("TOOL ok", fn="check_task_status", active=len(summary.get('active', [])))
            return [TextContent(type="text", text="\n".join(output))]

        if not task_id:
            return [TextContent(type="text", text="Error: task_id required, or use list_active=true")]

        task = tracker.get_task_dict(task_id)
        if not task:
            _log.warning("TOOL partial", fn="check_task_status", err="task not found")
            return [TextContent(type="text", text=f"✗ Task not found: {task_id}")]

        output = [f"✓ Task: {task['name']} [{task_id}]", ""]
        output.append(f"Status: {task['status']}")
        output.append(f"Progress: {task['progress']:.0%}")
        if task['progress_message']:
            output.append(f"Message: {task['progress_message']}")
        if task['duration_seconds']:
            output.append(f"Duration: {task['duration_seconds']:.1f}s")
        if task['error']:
            output.append(f"Error: {task['error']}")
        if task['has_result']:
            output.append("Result: Available (task completed)")

        _log.info("TOOL ok", fn="check_task_status", task_id=task_id, status=task['status'])
        return [TextContent(type="text", text="\n".join(output))]

    except Exception as e:
        _log.error("TOOL fail", fn="check_task_status", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Error: {str(e)}")]


@register_tool(
    "tool_metrics",
    category="system",
    description="Get execution metrics for MCP tools. Shows call counts, success rates, and average execution times.",
    input_schema={
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Specific tool name to get metrics for. If not provided, returns all metrics."
            }
        },
        "required": []
    }
)
async def tool_metrics_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:

    tool_name = arguments.get("tool_name")
    _log.debug("TOOL invoke", fn="tool_metrics", tool_name=tool_name)

    try:
        from . import get_tool_metrics, get_all_metrics

        if tool_name:
            metrics = get_tool_metrics(tool_name)
            if not metrics:
                return [TextContent(type="text", text=f"✗ No metrics found for tool: {tool_name}")]

            output = [f"✓ Metrics for {tool_name}:", ""]
            output.append(f"  Calls: {metrics['call_count']}")
            output.append(f"  Success: {metrics['success_count']} ({metrics['success_rate']})")
            output.append(f"  Errors: {metrics['error_count']}")
            output.append(f"  Avg Duration: {metrics['avg_duration_ms']:.1f}ms")
            if metrics['last_error']:
                output.append(f"  Last Error: {metrics['last_error']}")

            _log.info("TOOL ok", fn="tool_metrics", tool_name=tool_name)
            return [TextContent(type="text", text="\n".join(output))]

        all_metrics = get_all_metrics()
        if not all_metrics:
            return [TextContent(type="text", text="✓ No tool metrics recorded yet.")]

        output = ["✓ Tool Metrics Summary:", ""]

        # Sort by call count
        sorted_metrics = sorted(
            all_metrics.items(),
            key=lambda x: x[1]['call_count'],
            reverse=True
        )

        for name, m in sorted_metrics[:20]:  # Top 20
            output.append(f"  {name}:")
            output.append(f"    Calls: {m['call_count']} | Success: {m['success_rate']} | Avg: {m['avg_duration_ms']:.0f}ms")

        _log.info("TOOL ok", fn="tool_metrics", tools=len(all_metrics))
        return [TextContent(type="text", text="\n".join(output))]

    except Exception as e:
        _log.error("TOOL fail", fn="tool_metrics", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Error: {str(e)}")]


@register_tool(
    "system_status",
    category="system",
    description="Get overall system health status including circuit breakers, caches, and active tasks.",
    input_schema={
        "type": "object",
        "properties": {},
        "required": []
    }
)
async def system_status_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:

    _log.debug("TOOL invoke", fn="system_status")

    try:
        from backend.core.utils import (
            get_all_cache_stats,
            get_all_circuit_status,
        )
        from backend.core.utils.task_tracker import get_task_tracker
        from . import get_all_metrics

        output = ["✓ System Status", "═" * 40, ""]

        # Circuit Breakers
        circuits = get_all_circuit_status()
        output.append("Circuit Breakers:")
        for name, status in circuits.items():
            state = status['state']
            state_icon = "✅" if state == "closed" else ("⚠️" if state == "half_open" else "🔴")
            output.append(f"  {state_icon} {name}: {state}")
            if status['timeout_remaining'] > 0:
                output.append(f"      (retry in {status['timeout_remaining']:.0f}s)")

        output.append("")

        # Caches
        caches = get_all_cache_stats()
        if caches:
            output.append("Caches:")
            for name, stats in caches.items():
                output.append(f"  • {name}: {stats['size']}/{stats['maxsize']} (hit rate: {stats['hit_rate']})")
        else:
            output.append("Caches: None configured")

        output.append("")

        # Active Tasks
        tracker = get_task_tracker()
        active_tasks = tracker.list_active_tasks()
        output.append(f"Active Tasks: {len(active_tasks)}")
        for task in active_tasks[:5]:
            output.append(f"  • [{task.task_id}] {task.name}: {task.progress:.0%}")

        output.append("")

        # Tool Metrics Summary
        all_metrics = get_all_metrics()
        total_calls = sum(m['call_count'] for m in all_metrics.values())
        total_errors = sum(m['error_count'] for m in all_metrics.values())
        output.append(f"Tool Usage: {total_calls} calls ({total_errors} errors)")

        _log.info("TOOL ok", fn="system_status")
        return [TextContent(type="text", text="\n".join(output))]

    except Exception as e:
        _log.error("TOOL fail", fn="system_status", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Error: {str(e)}")]
