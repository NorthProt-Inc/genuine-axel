"""System observer package - log reading, code search, and code browsing.

This package provides tools for observing system logs and codebase:
- Log reading and filtering
- Codebase search (keyword and regex)
- Source code browsing

All exports maintain backward compatibility with the original single-file module.
"""

# Import the types module to allow patching
from . import types

# Import data classes
from .types import (
    LogReadResult,
    SearchMatch,
    SearchResult,
    _env_int,
)

# Import log reader functions
from .log_reader import (
    read_logs,
    list_available_logs,
    analyze_recent_errors,
    format_log_result,
    _validate_log_path,
    _read_tail,
    _filter_lines,
)

# Import code searcher functions
from .code_searcher import (
    search_codebase,
    search_codebase_regex,
    format_search_results,
    _search_file,
    _is_path_excluded,
    _is_code_file_allowed,
)

# Import code browser functions
from .code_browser import (
    get_source_code,
    list_source_files,
    get_code_summary,
)

# Re-export constants from types module
# These are available at package level for backward compatibility
ALLOWED_CODE_DIRS = types.ALLOWED_CODE_DIRS
ALLOWED_LOG_DIRS = types.ALLOWED_LOG_DIRS
LOG_FILE_ALIASES = types.LOG_FILE_ALIASES
ALLOWED_CODE_EXTENSIONS = types.ALLOWED_CODE_EXTENSIONS
EXCLUDED_PATTERNS = types.EXCLUDED_PATTERNS
AXEL_ROOT = types.AXEL_ROOT
ALLOWED_ROOT_FILES = types.ALLOWED_ROOT_FILES
MAX_FILE_SIZE = types.MAX_FILE_SIZE
MAX_LOG_LINES = types.MAX_LOG_LINES
MAX_SEARCH_RESULTS = types.MAX_SEARCH_RESULTS
SEARCH_CONTEXT_LINES = types.SEARCH_CONTEXT_LINES

# Re-export all public APIs (maintains backward compatibility)
__all__ = [
    # Log reading
    "read_logs",
    "list_available_logs",
    "analyze_recent_errors",
    "LogReadResult",
    
    # Code searching
    "search_codebase",
    "search_codebase_regex",
    "SearchResult",
    "SearchMatch",
    
    # Code browsing
    "get_source_code",
    "list_source_files",
    "get_code_summary",
    
    # Formatting
    "format_search_results",
    "format_log_result",
    
    # Constants
    "ALLOWED_CODE_DIRS",
    "ALLOWED_LOG_DIRS",
    "LOG_FILE_ALIASES",
    "ALLOWED_CODE_EXTENSIONS",
    "EXCLUDED_PATTERNS",
    "AXEL_ROOT",
    "ALLOWED_ROOT_FILES",
    "MAX_FILE_SIZE",
    "MAX_LOG_LINES",
    "MAX_SEARCH_RESULTS",
    "SEARCH_CONTEXT_LINES",
    
    # Internal functions (for testing)
    "_validate_log_path",
    "_read_tail",
    "_filter_lines",
    "_search_file",
    "_is_path_excluded",
    "_is_code_file_allowed",
    "_env_int",
    
    # Types module for patching
    "types",
]
