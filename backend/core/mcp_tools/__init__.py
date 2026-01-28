import importlib
import pkgutil
import logging
from typing import Callable, Dict, Any, Sequence, Optional
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
]

logger = logging.getLogger("axel-mcp-tools")

_tool_handlers: Dict[str, Callable] = {}

_tool_metadata: Dict[str, Dict[str, Any]] = {}

def register_tool(
    name: str,
    *,
    category: Optional[str] = None,
    description: Optional[str] = None,
    input_schema: Optional[dict] = None,
):

    def decorator(func: Callable):
        if name in _tool_handlers:
            logger.warning(f"Tool '{name}' is being re-registered, overwriting previous handler")

        _tool_handlers[name] = func
        _tool_metadata[name] = {
            "category": category,
            "module": func.__module__,
            "docstring": func.__doc__,
            "description": description,
            "input_schema": input_schema,
        }

        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

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

    tools = []
    for name, meta in _tool_metadata.items():
        if meta.get("input_schema") is None:

            logger.debug(f"Tool '{name}' missing input_schema, skipping schema generation")
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

def _load_all_tools():

    try:
        package = importlib.import_module("backend.core.mcp_tools")
        package_path = package.__path__

        for _, module_name, is_pkg in pkgutil.iter_modules(package_path):
            if not is_pkg and module_name.endswith("_tools"):
                try:
                    importlib.import_module(f"backend.core.mcp_tools.{module_name}")
                    logger.debug(f"Loaded tool module: {module_name}")
                except Exception as e:
                    logger.error(f"Failed to load tool module '{module_name}': {e}")

        logger.info(f"Tool registry initialized with {len(_tool_handlers)} tools")

    except Exception as e:
        logger.warning(f"Auto-loading tools failed (may be normal during initial setup): {e}")

_load_all_tools()
