"""
Structured error types for MCP tools and application-wide error hierarchy.

Provides consistent error classification and handling across all tools.
Includes AxnmihnError base hierarchy (ADR-020 port from Axel).
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class ErrorCode(Enum):
    """
    Categorized error codes for MCP tools.

    Ranges:
    - E00x: Input validation
    - E10x: Home Assistant
    - E20x: Research/Web
    - E30x: Memory
    - E40x: System/General
    """

    # Input validation (E00x)
    INVALID_PARAMETER = "E001"
    MISSING_PARAMETER = "E002"
    PARAMETER_OUT_OF_RANGE = "E003"
    INVALID_FORMAT = "E004"

    # Home Assistant (E10x)
    HASS_UNREACHABLE = "E101"
    HASS_AUTH_FAILED = "E102"
    HASS_ENTITY_NOT_FOUND = "E103"
    HASS_SERVICE_FAILED = "E104"
    HASS_CIRCUIT_OPEN = "E105"

    # Research/Web (E20x)
    BROWSER_TIMEOUT = "E201"
    PAGE_LOAD_FAILED = "E202"
    SEARCH_NO_RESULTS = "E203"
    SEARCH_PROVIDER_ERROR = "E204"
    INVALID_URL = "E205"
    CONTENT_TOO_LARGE = "E206"

    # Memory (E30x)
    MEMORY_STORE_FAILED = "E301"
    MEMORY_RETRIEVE_FAILED = "E302"
    EMBEDDING_FAILED = "E303"
    GRAPH_QUERY_FAILED = "E304"
    MEMORY_NOT_FOUND = "E305"

    # System (E40x)
    RATE_LIMITED = "E401"
    CIRCUIT_OPEN = "E402"
    TIMEOUT = "E403"
    COMMAND_FAILED = "E404"
    FILE_NOT_FOUND = "E405"
    PERMISSION_DENIED = "E406"
    INTERNAL_ERROR = "E499"


# Error codes that are safe to retry
RETRYABLE_ERRORS = {
    ErrorCode.HASS_UNREACHABLE,
    ErrorCode.BROWSER_TIMEOUT,
    ErrorCode.PAGE_LOAD_FAILED,
    ErrorCode.SEARCH_PROVIDER_ERROR,
    ErrorCode.EMBEDDING_FAILED,
    ErrorCode.RATE_LIMITED,
    ErrorCode.TIMEOUT,
}


@dataclass
class ToolError:
    """
    Structured error for MCP tool responses.

    Attributes:
        code: Error classification code
        message: Human-readable error message
        details: Optional additional context
        retryable: Whether the operation can be retried
    """

    code: ErrorCode
    message: str
    details: Optional[dict[str, Any]] = None
    retryable: bool = False

    def __post_init__(self):
        # Auto-set retryable based on error code if not explicitly set
        if self.code in RETRYABLE_ERRORS and not self.retryable:
            self.retryable = True

    def to_response(self) -> str:
        """Format error for MCP tool response."""
        prefix = "[RETRYABLE] " if self.retryable else ""
        return f"{prefix}[{self.code.value}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }


class ToolException(Exception):
    """
    Exception wrapper for ToolError.

    Can be raised in tool handlers and caught for consistent error handling.
    """

    def __init__(self, error: ToolError):
        self.error = error
        super().__init__(error.to_response())


# ---------------------------------------------------------------------------
# Structured Error Hierarchy (ADR-020 port)
# ---------------------------------------------------------------------------


class AxnmihnError(Exception, ABC):
    """Abstract base for all typed application errors."""

    @abstractmethod
    def _abstract_guard(self) -> None: ...

    @property
    @abstractmethod
    def is_retryable(self) -> bool: ...

    @property
    @abstractmethod
    def http_status(self) -> int: ...

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__.upper().replace("ERROR", "").strip("_") or type(self).__name__
        self.timestamp = time.time()
        self.request_id = request_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "is_retryable": self.is_retryable,
            "http_status": self.http_status,
            "timestamp": self.timestamp,
            "request_id": self.request_id,
        }


class TransientError(AxnmihnError):
    is_retryable: bool = True
    http_status: int = 503

    def _abstract_guard(self) -> None: ...

    def __init__(self, message: str, *, code: str = "TRANSIENT", **kw: Any) -> None:
        super().__init__(message, code=code, **kw)


class PermanentError(AxnmihnError):
    is_retryable: bool = False
    http_status: int = 500

    def _abstract_guard(self) -> None: ...

    def __init__(self, message: str, *, code: str = "PERMANENT", **kw: Any) -> None:
        super().__init__(message, code=code, **kw)


class ValidationError(AxnmihnError):
    is_retryable: bool = False
    http_status: int = 400

    def _abstract_guard(self) -> None: ...

    def __init__(
        self, message: str, *, code: str = "VALIDATION", field: str | None = None, **kw: Any
    ) -> None:
        super().__init__(message, code=code, **kw)
        self.field = field


class AuthError(AxnmihnError):
    is_retryable: bool = False

    def _abstract_guard(self) -> None: ...

    def __init__(
        self, message: str, *, code: str = "AUTH", http_status: int = 401, **kw: Any
    ) -> None:
        super().__init__(message, code=code, **kw)
        self._http_status = http_status

    @property  # type: ignore[override]
    def http_status(self) -> int:
        return self._http_status


class ProviderError(AxnmihnError):
    is_retryable: bool = True
    http_status: int = 502

    def _abstract_guard(self) -> None: ...

    def __init__(
        self, message: str, *, provider: str, code: str = "PROVIDER", **kw: Any
    ) -> None:
        super().__init__(message, code=code, **kw)
        self.provider = provider


class ToolExecutionError(AxnmihnError):
    is_retryable: bool = False
    http_status: int = 500

    def _abstract_guard(self) -> None: ...

    def __init__(
        self, message: str, *, tool_name: str, code: str = "TOOL_EXECUTION", **kw: Any
    ) -> None:
        super().__init__(message, code=code, **kw)
        self.tool_name = tool_name


class TimeoutError(AxnmihnError):  # noqa: A001
    is_retryable: bool = True
    http_status: int = 504

    def _abstract_guard(self) -> None: ...

    def __init__(
        self, message: str, *, timeout_ms: int, code: str = "TIMEOUT_ERR", **kw: Any
    ) -> None:
        super().__init__(message, code=code, **kw)
        self.timeout_ms = timeout_ms
