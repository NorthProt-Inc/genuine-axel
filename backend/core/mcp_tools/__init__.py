import importlib
import pkgutil
import time
from backend.core.logging.logging import get_logger
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, Any, Optional
from functools import wraps
from mcp.types import Tool

__all__ = [
    "register_tool",
    "get_tool_handler",
    "list_tools",
    "get_tools_by_category",
    "get_tool_metadata",
    "is_tool_registered",
    "get_tool_schemas",
    "get_tool_metrics",
    "get_all_metrics",
    "reset_metrics",
]

_log = get_logger("mcp.tools")

_tool_handlers: Dict[str, Callable] = {}

_tool_metadata: Dict[str, Dict[str, Any]] = {}


@dataclass
class ToolMetrics:
    """Metrics for a single tool."""
    call_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_duration_ms: float = 0.0
    last_call_at: Optional[float] = None
    last_error: Optional[str] = None
    last_error_at: Optional[float] = None

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.call_count if self.call_count > 0 else 0.0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.call_count if self.call_count > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "call_count": self.call_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "total_duration_ms": round(self.total_duration_ms, 2),
            "success_rate": f"{self.success_rate:.1%}",
            "last_call_at": self.last_call_at,
            "last_error": self.last_error[:100] if self.last_error else None,
            "last_error_at": self.last_error_at,
        }


_tool_metrics: Dict[str, ToolMetrics] = defaultdict(ToolMetrics)

def register_tool(
    name: str,
    *,
    category: Optional[str] = None,
    description: Optional[str] = None,
    input_schema: Optional[dict] = None,
):
    def decorator(func: Callable):
        if name in _tool_handlers:
            _log.warning("Tool re-registered, overwriting", tool=name)

        _tool_metadata[name] = {
            "category": category,
            "module": func.__module__,
            "docstring": func.__doc__,
            "description": description,
            "input_schema": input_schema,
        }

        @wraps(func)
        async def wrapper(*args, **kwargs):
            metrics = _tool_metrics[name]
            metrics.call_count += 1
            metrics.last_call_at = time.time()
            start_time = time.time()

            try:
                result = await func(*args, **kwargs)
                metrics.success_count += 1
                return result
            except Exception as e:
                metrics.error_count += 1
                metrics.last_error = str(e)
                metrics.last_error_at = time.time()
                raise
            finally:
                elapsed_ms = (time.time() - start_time) * 1000
                metrics.total_duration_ms += elapsed_ms

        _tool_handlers[name] = wrapper
        return wrapper
    return decorator

def get_tool_handler(name: str) -> Callable:
    if name not in _tool_handlers:
        available = ", ".join(sorted(_tool_handlers.keys())[:10])
        raise ValueError(f"Unknown tool: '{name}'. Available tools include: {available}...")
    return _tool_handlers[name]

def list_tools() -> list[str]:
    return sorted(_tool_handlers.keys())

def get_tools_by_category(category: str) -> list[str]:
    return [
        name for name, meta in _tool_metadata.items()
        if meta.get("category") == category
    ]

def get_tool_metadata(name: str) -> Optional[Dict[str, Any]]:
    return _tool_metadata.get(name)

def is_tool_registered(name: str) -> bool:
    return name in _tool_handlers

def get_tool_schemas() -> list[Tool]:
    """Build MCP tool schema list, filtering out disabled tools/categories.

    Note: Only affects schema visibility. get_tool_handler() is NOT filtered,
    so internal callers (e.g. Gemini backend) can still invoke any tool.
    """
    from backend.config import MCP_DISABLED_TOOLS, MCP_DISABLED_CATEGORIES

    tools = []
    for name, meta in _tool_metadata.items():
        if name in MCP_DISABLED_TOOLS:
            continue
        if meta.get("category") in MCP_DISABLED_CATEGORIES:
            continue
        if meta.get("input_schema") is None:
            _log.debug("Tool missing input_schema, skipping", tool=name)
            continue

        description = meta.get("description")
        if not description:
            docstring = meta.get("docstring", "")
            description = docstring.split("\n")[0].strip() if docstring else f"Tool: {name}"

        tools.append(Tool(
            name=name,
            description=description,
            inputSchema=meta["input_schema"]
        ))

    return tools

def get_tool_metrics(name: str) -> Optional[Dict[str, Any]]:
    """Get metrics for a specific tool."""
    if name not in _tool_metrics:
        return None
    return _tool_metrics[name].to_dict()


def get_all_metrics() -> Dict[str, Dict[str, Any]]:
    """Get metrics for all tools."""
    return {name: metrics.to_dict() for name, metrics in _tool_metrics.items()}


def reset_metrics(name: Optional[str] = None) -> None:
    """Reset metrics for a specific tool or all tools."""
    if name:
        if name in _tool_metrics:
            _tool_metrics[name] = ToolMetrics()
    else:
        _tool_metrics.clear()


def _load_all_tools():
    try:
        package = importlib.import_module("backend.core.mcp_tools")
        package_path = package.__path__

        for _, module_name, is_pkg in pkgutil.iter_modules(package_path):
            if not is_pkg and module_name.endswith("_tools"):
                try:
                    importlib.import_module(f"backend.core.mcp_tools.{module_name}")
                    _log.debug("Loaded tool module", module=module_name)
                except Exception as e:
                    _log.error("Failed to load tool module", module=module_name, err=str(e)[:100])

        _log.info("Tool registry initialized", tool_cnt=len(_tool_handlers))

    except Exception as e:
        _log.warning("Auto-loading tools failed (may be normal during initial setup)", err=str(e)[:100])

_load_all_tools()
