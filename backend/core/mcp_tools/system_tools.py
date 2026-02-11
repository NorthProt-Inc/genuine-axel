"""System tools for MCP (Backward Compatibility Shim).

This module maintains backward compatibility by re-exporting all tools
from their new specialized modules:
- command_tools: run_command
- search_tools: search_codebase, search_codebase_regex
- log_tools: read_system_logs, list_available_logs, analyze_log_errors
- monitoring_tools: check_task_status, tool_metrics, system_status

All imports from this module will continue to work as before.
"""

# Re-export all tools for backward compatibility
from .command_tools import run_command
from .search_tools import search_codebase_tool, search_codebase_regex_tool
from .log_tools import (
    read_system_logs,
    list_available_logs_tool,
    analyze_log_errors,
)
from .monitoring_tools import (
    check_task_status,
    tool_metrics_tool,
    system_status_tool,
)

__all__ = [
    # Command tools
    "run_command",
    # Search tools
    "search_codebase_tool",
    "search_codebase_regex_tool",
    # Log tools
    "read_system_logs",
    "list_available_logs_tool",
    "analyze_log_errors",
    # Monitoring tools
    "check_task_status",
    "tool_metrics_tool",
    "system_status_tool",
]
