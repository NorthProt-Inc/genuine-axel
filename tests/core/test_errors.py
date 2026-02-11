"""Tests for backend.core.errors."""

import pytest
from backend.core.errors import (
    ErrorCode,
    ToolError,
    ToolException,
    RETRYABLE_ERRORS,
)


# ---------------------------------------------------------------------------
# ErrorCode enum
# ---------------------------------------------------------------------------


class TestErrorCode:
    """Tests for the ErrorCode enum."""

    def test_input_validation_codes_start_with_e00(self):
        assert ErrorCode.INVALID_PARAMETER.value == "E001"
        assert ErrorCode.MISSING_PARAMETER.value == "E002"
        assert ErrorCode.PARAMETER_OUT_OF_RANGE.value == "E003"
        assert ErrorCode.INVALID_FORMAT.value == "E004"

    def test_hass_codes_start_with_e10(self):
        assert ErrorCode.HASS_UNREACHABLE.value == "E101"
        assert ErrorCode.HASS_AUTH_FAILED.value == "E102"
        assert ErrorCode.HASS_ENTITY_NOT_FOUND.value == "E103"
        assert ErrorCode.HASS_SERVICE_FAILED.value == "E104"
        assert ErrorCode.HASS_CIRCUIT_OPEN.value == "E105"

    def test_research_codes_start_with_e20(self):
        assert ErrorCode.BROWSER_TIMEOUT.value == "E201"
        assert ErrorCode.PAGE_LOAD_FAILED.value == "E202"
        assert ErrorCode.SEARCH_NO_RESULTS.value == "E203"
        assert ErrorCode.SEARCH_PROVIDER_ERROR.value == "E204"
        assert ErrorCode.INVALID_URL.value == "E205"
        assert ErrorCode.CONTENT_TOO_LARGE.value == "E206"

    def test_memory_codes_start_with_e30(self):
        assert ErrorCode.MEMORY_STORE_FAILED.value == "E301"
        assert ErrorCode.MEMORY_RETRIEVE_FAILED.value == "E302"
        assert ErrorCode.EMBEDDING_FAILED.value == "E303"
        assert ErrorCode.GRAPH_QUERY_FAILED.value == "E304"
        assert ErrorCode.MEMORY_NOT_FOUND.value == "E305"

    def test_system_codes_start_with_e40(self):
        assert ErrorCode.RATE_LIMITED.value == "E401"
        assert ErrorCode.CIRCUIT_OPEN.value == "E402"
        assert ErrorCode.TIMEOUT.value == "E403"
        assert ErrorCode.COMMAND_FAILED.value == "E404"
        assert ErrorCode.FILE_NOT_FOUND.value == "E405"
        assert ErrorCode.PERMISSION_DENIED.value == "E406"
        assert ErrorCode.INTERNAL_ERROR.value == "E499"

    def test_all_codes_unique(self):
        values = [e.value for e in ErrorCode]
        assert len(values) == len(set(values)), "Duplicate ErrorCode values found"

    def test_all_codes_are_strings(self):
        for code in ErrorCode:
            assert isinstance(code.value, str)


# ---------------------------------------------------------------------------
# RETRYABLE_ERRORS
# ---------------------------------------------------------------------------


class TestRetryableErrors:
    """Tests for the RETRYABLE_ERRORS set."""

    def test_retryable_errors_is_set(self):
        assert isinstance(RETRYABLE_ERRORS, set)

    def test_expected_retryable_codes(self):
        expected = {
            ErrorCode.HASS_UNREACHABLE,
            ErrorCode.BROWSER_TIMEOUT,
            ErrorCode.PAGE_LOAD_FAILED,
            ErrorCode.SEARCH_PROVIDER_ERROR,
            ErrorCode.EMBEDDING_FAILED,
            ErrorCode.RATE_LIMITED,
            ErrorCode.TIMEOUT,
        }
        assert RETRYABLE_ERRORS == expected

    def test_non_retryable_codes_excluded(self):
        non_retryable = {
            ErrorCode.INVALID_PARAMETER,
            ErrorCode.MISSING_PARAMETER,
            ErrorCode.HASS_AUTH_FAILED,
            ErrorCode.HASS_ENTITY_NOT_FOUND,
            ErrorCode.PERMISSION_DENIED,
            ErrorCode.INTERNAL_ERROR,
            ErrorCode.COMMAND_FAILED,
        }
        for code in non_retryable:
            assert code not in RETRYABLE_ERRORS


# ---------------------------------------------------------------------------
# ToolError
# ---------------------------------------------------------------------------


class TestToolError:
    """Tests for the ToolError dataclass."""

    def test_basic_creation(self):
        err = ToolError(code=ErrorCode.INVALID_PARAMETER, message="Bad param")
        assert err.code == ErrorCode.INVALID_PARAMETER
        assert err.message == "Bad param"
        assert err.details is None
        assert err.retryable is False

    def test_with_details(self):
        details = {"param": "query", "reason": "too long"}
        err = ToolError(
            code=ErrorCode.INVALID_PARAMETER,
            message="Bad param",
            details=details,
        )
        assert err.details == details

    def test_auto_retryable_for_retryable_code(self):
        """ToolError with a retryable code auto-sets retryable=True."""
        err = ToolError(code=ErrorCode.TIMEOUT, message="Timed out")
        assert err.retryable is True

    def test_auto_retryable_hass_unreachable(self):
        err = ToolError(code=ErrorCode.HASS_UNREACHABLE, message="HA down")
        assert err.retryable is True

    def test_auto_retryable_browser_timeout(self):
        err = ToolError(code=ErrorCode.BROWSER_TIMEOUT, message="Timeout")
        assert err.retryable is True

    def test_auto_retryable_rate_limited(self):
        err = ToolError(code=ErrorCode.RATE_LIMITED, message="Rate limited")
        assert err.retryable is True

    def test_non_retryable_code_stays_false(self):
        err = ToolError(code=ErrorCode.INVALID_PARAMETER, message="Bad param")
        assert err.retryable is False

    def test_explicitly_set_retryable_true_preserved(self):
        """Even with non-retryable code, explicit retryable=True is kept."""
        err = ToolError(
            code=ErrorCode.INVALID_PARAMETER,
            message="Bad",
            retryable=True,
        )
        assert err.retryable is True

    # -- to_response ---------------------------------------------------------

    def test_to_response_non_retryable(self):
        err = ToolError(code=ErrorCode.INVALID_PARAMETER, message="Bad param")
        response = err.to_response()
        assert response == "[E001] Bad param"
        assert "[RETRYABLE]" not in response

    def test_to_response_retryable(self):
        err = ToolError(code=ErrorCode.TIMEOUT, message="Timed out")
        response = err.to_response()
        assert response == "[RETRYABLE] [E403] Timed out"

    def test_to_response_format(self):
        err = ToolError(code=ErrorCode.MEMORY_NOT_FOUND, message="Not found")
        response = err.to_response()
        assert "[E305]" in response
        assert "Not found" in response

    # -- to_dict -------------------------------------------------------------

    def test_to_dict_structure(self):
        details = {"key": "value"}
        err = ToolError(
            code=ErrorCode.TIMEOUT,
            message="Timed out",
            details=details,
        )
        d = err.to_dict()
        assert d["code"] == "E403"
        assert d["message"] == "Timed out"
        assert d["details"] == details
        assert d["retryable"] is True

    def test_to_dict_none_details(self):
        err = ToolError(code=ErrorCode.INTERNAL_ERROR, message="Oops")
        d = err.to_dict()
        assert d["details"] is None
        assert d["retryable"] is False

    def test_to_dict_returns_plain_dict(self):
        err = ToolError(code=ErrorCode.INTERNAL_ERROR, message="Oops")
        d = err.to_dict()
        assert isinstance(d, dict)
        assert set(d.keys()) == {"code", "message", "details", "retryable"}


# ---------------------------------------------------------------------------
# ToolException
# ---------------------------------------------------------------------------


class TestToolException:
    """Tests for the ToolException class."""

    def test_is_exception(self):
        err = ToolError(code=ErrorCode.INTERNAL_ERROR, message="Fail")
        exc = ToolException(err)
        assert isinstance(exc, Exception)

    def test_stores_tool_error(self):
        err = ToolError(code=ErrorCode.INTERNAL_ERROR, message="Fail")
        exc = ToolException(err)
        assert exc.error is err

    def test_str_is_to_response(self):
        err = ToolError(code=ErrorCode.TIMEOUT, message="Slow")
        exc = ToolException(err)
        assert str(exc) == err.to_response()

    def test_can_be_raised_and_caught(self):
        err = ToolError(code=ErrorCode.FILE_NOT_FOUND, message="No file")
        with pytest.raises(ToolException) as exc_info:
            raise ToolException(err)
        assert exc_info.value.error.code == ErrorCode.FILE_NOT_FOUND
        assert "No file" in str(exc_info.value)

    def test_exception_retryable_flag(self):
        err = ToolError(code=ErrorCode.RATE_LIMITED, message="Too fast")
        exc = ToolException(err)
        assert exc.error.retryable is True

    def test_exception_non_retryable(self):
        err = ToolError(code=ErrorCode.PERMISSION_DENIED, message="Nope")
        exc = ToolException(err)
        assert exc.error.retryable is False
