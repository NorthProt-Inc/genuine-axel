"""Data classes and constants for system_observer package."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

# Project root - 4 levels up from this file
AXEL_ROOT = Path(__file__).resolve().parents[4]


def _env_int(name: str, default: int) -> int:
    """Read integer from environment variable with fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Configuration from environment
MAX_FILE_SIZE = _env_int("MAX_FILE_SIZE", 10 * 1024 * 1024)
MAX_LOG_LINES = _env_int("MAX_LOG_LINES", 1000)
MAX_SEARCH_RESULTS = _env_int("MAX_SEARCH_RESULTS", 100)
SEARCH_CONTEXT_LINES = 2

# Allowed directories for code access
ALLOWED_CODE_DIRS = [
    "core",
    "memory",
    "llm",
    "media",
    "reasoning",
    "api",
    "scripts",
    "utils",
    "protocols",
    "mutations",
    "wake",
    "tests",
    "docs",
    "resources",
    "data",
]

# Allowed root-level files
ALLOWED_ROOT_FILES = [
    "config.py",
    "app.py",
    "server.py",
    "requirements.txt",
]

# Allowed log directories
ALLOWED_LOG_DIRS = [
    AXEL_ROOT / "logs",
    AXEL_ROOT / "data" / "logs",
]

# Allowed code file extensions
ALLOWED_CODE_EXTENSIONS = [
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".yaml", ".yml", ".env.example",
    ".txt", ".md", ".mdx",
    ".css", ".scss", ".html",
]

# Patterns to exclude from searches
EXCLUDED_PATTERNS = [
    "__pycache__",
    ".pyc",
    "node_modules",
    ".env",
    ".git",
    "chroma_db",
    "venv",
    ".next",
    "dist",
    "build",
    ".venv",
    "*.egg-info",
]

# Log file aliases for convenience
LOG_FILE_ALIASES = {
    "backend": "backend.log",
    "backend_error": "backend.error.log",
    "mcp": "mcp.log",
    "mcp_error": "mcp.error.log",
    "main": "axnmihn.log",
    "rvc": "ultimate_rvc.log",
    "app": "app.log",
}


@dataclass
class LogReadResult:
    """Result of reading log file."""

    success: bool
    content: str
    lines_read: int
    file_path: str
    error: Optional[str] = None
    filter_applied: Optional[str] = None


@dataclass
class SearchMatch:
    """Single search match with context."""

    file_path: str
    line_number: int
    content: str
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """Result of codebase search."""

    success: bool
    matches: List[SearchMatch] = field(default_factory=list)
    total_matches: int = 0
    files_searched: int = 0
    error: Optional[str] = None
    truncated: bool = False


__all__ = [
    "AXEL_ROOT",
    "MAX_FILE_SIZE",
    "MAX_LOG_LINES",
    "MAX_SEARCH_RESULTS",
    "SEARCH_CONTEXT_LINES",
    "ALLOWED_CODE_DIRS",
    "ALLOWED_ROOT_FILES",
    "ALLOWED_LOG_DIRS",
    "ALLOWED_CODE_EXTENSIONS",
    "EXCLUDED_PATTERNS",
    "LOG_FILE_ALIASES",
    "LogReadResult",
    "SearchMatch",
    "SearchResult",
]
