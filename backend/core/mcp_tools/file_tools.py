from pathlib import Path
from typing import Any, Sequence
from mcp.types import TextContent
from . import register_tool
from backend.core.utils.path_validator import validate_path, sanitize_path
from backend.core.logging.logging import get_logger

_log = get_logger("mcp.file_tools")

MAX_FILE_SIZE = 10 * 1024 * 1024

@register_tool(
    "read_file",
    category="file",
    description="Read the contents of a file on the host system",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file"}
        },
        "required": ["path"]
    }
)
async def read_file(arguments: dict[str, Any]) -> Sequence[TextContent]:

    path_str = arguments.get("path", "")
    _log.debug("TOOL invoke", fn="read_file", path=path_str[:100] if path_str else None)

    if not path_str:
        _log.warning("TOOL fail", fn="read_file", err="path parameter required")
        return [TextContent(type="text", text="Error: path parameter is required")]

    path_str = sanitize_path(path_str)
    is_valid, error = validate_path(path_str, operation="read")

    if not is_valid:
        _log.warning("TOOL fail", fn="read_file", err=f"path validation: {error}"[:100])
        return [TextContent(type="text", text=f"Error: {error}")]

    try:
        path = Path(path_str).resolve()

        if not path.exists():
            _log.warning("TOOL fail", fn="read_file", err="file not found")
            return [TextContent(type="text", text=f"Error: File not found at {path}")]

        if not path.is_file():
            _log.warning("TOOL fail", fn="read_file", err="not a file")
            return [TextContent(type="text", text=f"Error: '{path}' is not a file")]

        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            _log.warning("TOOL fail", fn="read_file", err="file too large", size=file_size)
            return [TextContent(
                type="text",
                text=f"Error: File too large ({file_size:,} bytes). Max: {MAX_FILE_SIZE:,} bytes (10MB)"
            )]

        content = path.read_text(encoding="utf-8")
        _log.info("TOOL ok", fn="read_file", res_len=len(content))
        return [TextContent(type="text", text=content)]

    except UnicodeDecodeError:
        _log.warning("TOOL fail", fn="read_file", err="binary file")
        return [TextContent(type="text", text=f"Error: '{path}' is a binary file and cannot be read as text")]
    except PermissionError:
        _log.warning("TOOL fail", fn="read_file", err="permission denied")
        return [TextContent(type="text", text=f"Error: Permission denied for '{path}'")]
    except Exception as e:
        _log.error("TOOL fail", fn="read_file", err=str(e)[:100])
        return [TextContent(type="text", text=f"Error reading file: {str(e)}")]

@register_tool(
    "list_directory",
    category="file",
    description="List files and directories in a path",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to list"}
        },
        "required": ["path"]
    }
)
async def list_directory(arguments: dict[str, Any]) -> Sequence[TextContent]:

    path_str = arguments.get("path", "")
    _log.debug("TOOL invoke", fn="list_directory", path=path_str[:100] if path_str else None)

    if not path_str:
        _log.warning("TOOL fail", fn="list_directory", err="path parameter required")
        return [TextContent(type="text", text="Error: path parameter is required")]

    path_str = sanitize_path(path_str)
    is_valid, error = validate_path(path_str, operation="read")

    if not is_valid:
        _log.warning("TOOL fail", fn="list_directory", err=f"path validation: {error}"[:100])
        return [TextContent(type="text", text=f"Error: {error}")]

    try:
        path = Path(path_str).resolve()

        if not path.exists():
            _log.warning("TOOL fail", fn="list_directory", err="path not found")
            return [TextContent(type="text", text=f"Error: Path not found at {path}")]

        if not path.is_dir():
            _log.warning("TOOL fail", fn="list_directory", err="not a directory")
            return [TextContent(type="text", text=f"Error: '{path}' is not a directory")]

        items = []
        for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            type_str = "DIR" if item.is_dir() else "FILE"
            items.append(f"[{type_str}] {item.name}")

        if not items:
            _log.info("TOOL ok", fn="list_directory", res_len=0)
            return [TextContent(type="text", text=f"Directory '{path}' is empty")]

        _log.info("TOOL ok", fn="list_directory", res_len=len(items))
        return [TextContent(type="text", text="\n".join(items))]

    except PermissionError:
        _log.warning("TOOL fail", fn="list_directory", err="permission denied")
        return [TextContent(type="text", text=f"Error: Permission denied for '{path}'")]
    except Exception as e:
        _log.error("TOOL fail", fn="list_directory", err=str(e)[:100])
        return [TextContent(type="text", text=f"Error listing directory: {str(e)}")]

@register_tool(
    "get_source_code",
    category="file",
    description="Read source code from the project. Use relative paths from project root (e.g., 'core/chat_handler.py')",
    input_schema={
        "type": "object",
        "properties": {
            "relative_path": {"type": "string", "description": "Relative path to the source file from project root"}
        },
        "required": ["relative_path"]
    }
)
async def get_source_code(arguments: dict[str, Any]) -> Sequence[TextContent]:

    relative_path = arguments.get("relative_path", "")
    _log.debug("TOOL invoke", fn="get_source_code", relative_path=relative_path[:100] if relative_path else None)

    if not relative_path:
        _log.warning("TOOL fail", fn="get_source_code", err="relative_path parameter required")
        return [TextContent(type="text", text="Error: relative_path parameter is required")]

    try:

        from backend.core.tools.system_observer import get_source_code as _get_source_code

        content = _get_source_code(relative_path)

        if content:
            _log.info("TOOL ok", fn="get_source_code", res_len=len(content))
            return [TextContent(type="text", text=content)]
        else:
            _log.warning("TOOL fail", fn="get_source_code", err="could not read source")
            return [TextContent(type="text", text=f"Error: Could not read source code from {relative_path}")]

    except ImportError:

        from backend.config import PROJECT_ROOT

        path = PROJECT_ROOT / relative_path
        path_str = str(path)

        is_valid, error = validate_path(path_str, operation="read")
        if not is_valid:
            _log.warning("TOOL fail", fn="get_source_code", err=f"path validation: {error}"[:100])
            return [TextContent(type="text", text=f"Error: {error}")]

        if not path.exists():
            _log.warning("TOOL fail", fn="get_source_code", err="file not found")
            return [TextContent(type="text", text=f"Error: File not found at {path}")]

        try:
            content = path.read_text(encoding="utf-8")
            _log.info("TOOL ok", fn="get_source_code", res_len=len(content))
            return [TextContent(type="text", text=content)]
        except Exception as e:
            _log.error("TOOL fail", fn="get_source_code", err=str(e)[:100])
            return [TextContent(type="text", text=f"Error reading source: {e}")]

    except Exception as e:
        _log.error("TOOL fail", fn="get_source_code", err=str(e)[:100])
        return [TextContent(type="text", text=f"Error reading source code: {str(e)}")]
