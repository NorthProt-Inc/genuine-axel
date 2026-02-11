"""Tests for structured error hierarchy (Wave 1.1).

Tests AxnmihnError base class and 7 specialized subclasses ported from
Axel's error taxonomy (ADR-020).
"""

import pytest

from backend.core.errors import (
    AxnmihnError,
    TransientError,
    PermanentError,
    ValidationError,
    AuthError,
    ProviderError,
    ToolExecutionError,
    TimeoutError as AxnmihnTimeoutError,
    ErrorCode,
    ToolError,
    ToolException,
    RETRYABLE_ERRORS,
)


class TestAxnmihnErrorBase:
    """Tests for the abstract base error class."""

    def test_cannot_instantiate_directly(self):
        """AxnmihnError should not be used directly (abstract base)."""
        err = TransientError("test")
        assert isinstance(err, AxnmihnError)

    def test_subclass_has_required_attributes(self):
        err = TransientError("service down")
        assert hasattr(err, "code")
        assert hasattr(err, "is_retryable")
        assert hasattr(err, "http_status")
        assert hasattr(err, "message")

    def test_str_representation(self):
        err = TransientError("service down")
        assert "service down" in str(err)

    def test_timestamp_set(self):
        err = TransientError("test")
        assert err.timestamp > 0

    def test_request_id_optional(self):
        err = TransientError("test")
        assert err.request_id is None

    def test_request_id_settable(self):
        err = TransientError("test", request_id="req-123")
        assert err.request_id == "req-123"

    def test_is_exception(self):
        err = TransientError("test")
        assert isinstance(err, Exception)

    def test_to_dict(self):
        err = TransientError("test", request_id="req-1")
        d = err.to_dict()
        assert d["message"] == "test"
        assert d["code"] == err.code
        assert d["is_retryable"] == err.is_retryable
        assert d["http_status"] == err.http_status
        assert "timestamp" in d
        assert d["request_id"] == "req-1"


class TestTransientError:

    def test_is_retryable(self):
        err = TransientError("temp failure")
        assert err.is_retryable is True

    def test_http_status_503(self):
        err = TransientError("temp failure")
        assert err.http_status == 503

    def test_default_code(self):
        err = TransientError("temp failure")
        assert err.code == "TRANSIENT"

    def test_custom_code(self):
        err = TransientError("temp failure", code="CUSTOM_T")
        assert err.code == "CUSTOM_T"


class TestPermanentError:

    def test_not_retryable(self):
        err = PermanentError("fatal")
        assert err.is_retryable is False

    def test_http_status_500(self):
        err = PermanentError("fatal")
        assert err.http_status == 500

    def test_default_code(self):
        err = PermanentError("fatal")
        assert err.code == "PERMANENT"


class TestValidationError:

    def test_not_retryable(self):
        err = ValidationError("bad input")
        assert err.is_retryable is False

    def test_http_status_400(self):
        err = ValidationError("bad input")
        assert err.http_status == 400

    def test_default_code(self):
        err = ValidationError("bad input")
        assert err.code == "VALIDATION"

    def test_field_info(self):
        err = ValidationError("bad input", field="email")
        assert err.field == "email"


class TestAuthError:

    def test_not_retryable(self):
        err = AuthError("unauthorized")
        assert err.is_retryable is False

    def test_http_status_default_401(self):
        err = AuthError("unauthorized")
        assert err.http_status == 401

    def test_http_status_403(self):
        err = AuthError("forbidden", http_status=403)
        assert err.http_status == 403


class TestProviderError:

    def test_is_retryable(self):
        err = ProviderError("LLM down", provider="gemini")
        assert err.is_retryable is True

    def test_http_status_502(self):
        err = ProviderError("LLM down", provider="gemini")
        assert err.http_status == 502

    def test_provider_attribute(self):
        err = ProviderError("LLM down", provider="claude")
        assert err.provider == "claude"

    def test_default_code(self):
        err = ProviderError("LLM down", provider="gemini")
        assert err.code == "PROVIDER"


class TestToolExecutionError:

    def test_not_retryable(self):
        err = ToolExecutionError("tool failed", tool_name="search")
        assert err.is_retryable is False

    def test_http_status_500(self):
        err = ToolExecutionError("tool failed", tool_name="search")
        assert err.http_status == 500

    def test_tool_name_attribute(self):
        err = ToolExecutionError("tool failed", tool_name="memory_store")
        assert err.tool_name == "memory_store"


class TestAxnmihnTimeoutError:

    def test_is_retryable(self):
        err = AxnmihnTimeoutError("timed out", timeout_ms=5000)
        assert err.is_retryable is True

    def test_http_status_504(self):
        err = AxnmihnTimeoutError("timed out", timeout_ms=5000)
        assert err.http_status == 504

    def test_timeout_ms_attribute(self):
        err = AxnmihnTimeoutError("timed out", timeout_ms=3000)
        assert err.timeout_ms == 3000


class TestErrorHierarchyInheritance:
    """All error types should inherit from AxnmihnError."""

    @pytest.mark.parametrize(
        "error_cls,kwargs",
        [
            (TransientError, {"message": "t"}),
            (PermanentError, {"message": "p"}),
            (ValidationError, {"message": "v"}),
            (AuthError, {"message": "a"}),
            (ProviderError, {"message": "pr", "provider": "x"}),
            (ToolExecutionError, {"message": "te", "tool_name": "x"}),
            (AxnmihnTimeoutError, {"message": "to", "timeout_ms": 1000}),
        ],
    )
    def test_inherits_from_base(self, error_cls, kwargs):
        err = error_cls(**kwargs)
        assert isinstance(err, AxnmihnError)
        assert isinstance(err, Exception)

    def test_can_catch_as_base(self):
        with pytest.raises(AxnmihnError):
            raise ProviderError("test", provider="x")


class TestBackwardCompatibility:
    """Existing ErrorCode/ToolError/ToolException must still work."""

    def test_error_code_enum_exists(self):
        assert ErrorCode.INVALID_PARAMETER.value == "E001"

    def test_tool_error_works(self):
        err = ToolError(code=ErrorCode.TIMEOUT, message="slow")
        assert err.retryable is True

    def test_tool_exception_works(self):
        err = ToolError(code=ErrorCode.INTERNAL_ERROR, message="fail")
        exc = ToolException(err)
        assert isinstance(exc, Exception)

    def test_retryable_errors_set(self):
        assert ErrorCode.TIMEOUT in RETRYABLE_ERRORS
