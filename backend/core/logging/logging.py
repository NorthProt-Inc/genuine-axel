"""Backward compatibility shim — real implementations live in sub-modules."""

from .constants import (  # noqa: F401
    ABBREV,
    Colors,
    DEFAULT_LEVEL,
    LEVEL_STYLES,
    LOG_JSON,
    LOG_LEVEL,
    LOG_LEVEL_MAP,
    MODULE_ABBREV,
    MODULE_COLORS,
    VANCOUVER_TZ,
    _COLORS,
    _request_id,
    abbreviate,
    get_request_id,
    reset_request_id,
    set_request_id,
)
from .decorator import P, T, logged  # noqa: F401
from .formatters import JsonFormatter, PlainFormatter, SmartFormatter  # noqa: F401
from .structured_logger import (  # noqa: F401
    StructuredLogger,
    _loggers,
    get_logger,
    set_log_level,
)
