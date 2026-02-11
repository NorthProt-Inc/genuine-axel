"""System monitoring and metrics tools for MCP.

This module provides tools for checking task status, tool metrics,
and overall system health.
"""

from typing import Any, Sequence
from mcp.types import TextContent
from . import register_tool
from backend.core.logging.logging import get_logger

_log = get_logger("mcp.monitoring_tools")


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
    """Check status of async tasks.

    Args:
        arguments: Dict with task_id or list_active flag

    Returns:
        TextContent with task status or summary
    """
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
    """Get execution metrics for MCP tools.

    Args:
        arguments: Dict with optional tool_name

    Returns:
        TextContent with call counts, success rates, durations
    """
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
    """Get overall system health status.

    Returns:
        TextContent with circuit breakers, caches, and task summary
    """
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


__all__ = [
    "check_task_status",
    "tool_metrics_tool",
    "system_status_tool",
]
