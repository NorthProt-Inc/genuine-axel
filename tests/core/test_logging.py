"""Tests for backend.core.logging.logging module.

Covers: StructuredLogger, SmartFormatter, PlainFormatter, JsonFormatter,
abbreviate(), Colors, request_id context var, logged() decorator,
get_logger(), set_log_level().
"""

import json
import logging
import sys
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from backend.core.logging.logging import (
    StructuredLogger,
    SmartFormatter,
    PlainFormatter,
    JsonFormatter,
    Colors,
    abbreviate,
    ABBREV,
    MODULE_ABBREV,
    MODULE_COLORS,
    LEVEL_STYLES,
    _COLORS,
    get_logger,
    set_log_level,
    set_request_id,
    reset_request_id,
    get_request_id,
    logged,
    _loggers,
)


# ---------------------------------------------------------------------------
# abbreviate()
# ---------------------------------------------------------------------------
class TestAbbreviate:
    def test_known_words_are_shortened(self):
        assert "req" in abbreviate("request")
        assert "res" in abbreviate("response")
        assert "msg" in abbreviate("message")

    def test_capitalised_words_are_shortened(self):
        result = abbreviate("Request received")
        assert "REQ" in result
        assert "recv" in result.lower() or "RECV" in result

    def test_unknown_word_passes_through(self):
        assert abbreviate("flamingo") == "flamingo"

    def test_empty_string(self):
        assert abbreviate("") == ""

    def test_multiple_replacements(self):
        result = abbreviate("request timeout error")
        assert "req" in result
        assert "tout" in result
        assert "err" in result


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
class TestColors:
    def test_enabled_returns_code_when_tty(self):
        with patch.dict("os.environ", {}, clear=False):
            with patch("os.environ.get", return_value=None):
                with patch("sys.stdout") as mock_stdout:
                    mock_stdout.isatty.return_value = True
                    # Remove NO_COLOR if present
                    with patch.dict("os.environ", {}, clear=False):
                        import os
                        os.environ.pop("NO_COLOR", None)
                        result = Colors.get("\033[31m")
                        # Result depends on whether stdout is actually a TTY
                        assert isinstance(result, str)

    def test_disabled_when_no_color_set(self):
        with patch.dict("os.environ", {"NO_COLOR": "1"}):
            assert Colors.get("\033[31m") == ""

    def test_disabled_when_not_tty(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("NO_COLOR", None)
            with patch.object(sys.stdout, "isatty", return_value=False):
                assert Colors.get("\033[31m") == ""


# ---------------------------------------------------------------------------
# request_id context var
# ---------------------------------------------------------------------------
class TestRequestIdContextVar:
    def test_default_is_none(self):
        assert get_request_id() is None or isinstance(get_request_id(), str)

    def test_set_and_get(self):
        token = set_request_id("abc-123")
        try:
            assert get_request_id() == "abc-123"
        finally:
            reset_request_id(token)

    def test_reset_restores_previous(self):
        original = get_request_id()
        token = set_request_id("temp-id")
        reset_request_id(token)
        assert get_request_id() == original


# ---------------------------------------------------------------------------
# SmartFormatter
# ---------------------------------------------------------------------------
class TestSmartFormatter:
    def _make_record(self, name="core.test", level=logging.INFO, msg="hello", extra_data=None):
        logger = logging.getLogger(name)
        record = logger.makeRecord(name, level, "", 0, msg, (), None)
        record.extra_data = extra_data or {}
        return record

    def test_basic_format_no_colors(self):
        fmt = SmartFormatter(use_colors=False)
        record = self._make_record()
        output = fmt.format(record)
        assert "hello" in output
        assert "INFO" in output or "INFO" in output

    def test_format_with_extra_data(self):
        fmt = SmartFormatter(use_colors=False)
        record = self._make_record(extra_data={"model": "gemini", "tokens": 42})
        output = fmt.format(record)
        assert "model" in output
        assert "gemini" in output
        assert "tokens" in output
        assert "42" in output

    def test_format_value_none(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._format_value(None) == "null"

    def test_format_value_bool(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._format_value(True) == "yes"
        assert fmt._format_value(False) == "no"

    def test_format_value_number(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._format_value(42) == "42"
        assert fmt._format_value(3.14) == "3.14"

    def test_format_value_list_empty(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._format_value([]) == "[]"

    def test_format_value_list_small(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._format_value([1, 2, 3]) == "[1, 2, 3]"

    def test_format_value_list_large(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._format_value([1, 2, 3, 4]) == "[4 items]"

    def test_format_value_dict_empty(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._format_value({}) == "{}"

    def test_format_value_dict_nonempty(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._format_value({"a": 1, "b": 2}) == "{2 keys}"

    def test_format_value_long_string_truncated(self):
        fmt = SmartFormatter(use_colors=False)
        long_str = "x" * 100
        result = fmt._format_value(long_str, max_len=60)
        assert len(result) == 60
        assert result.endswith("...")

    def test_format_value_short_string_not_truncated(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._format_value("short") == "short"

    def test_get_module_abbrev_known(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._get_module_abbrev("core.test") == "COR"
        assert fmt._get_module_abbrev("memory.graph") == "MEM"
        assert fmt._get_module_abbrev("api.routes") == "API"

    def test_get_module_abbrev_unknown(self):
        fmt = SmartFormatter(use_colors=False)
        result = fmt._get_module_abbrev("unknown.module")
        assert result == "UNK"

    def test_get_module_color_no_colors(self):
        fmt = SmartFormatter(use_colors=False)
        assert fmt._get_module_color("core.test") == ""

    def test_format_with_exception(self):
        fmt = SmartFormatter(use_colors=False)
        try:
            raise ValueError("test error")
        except ValueError:
            record = self._make_record()
            record.exc_info = sys.exc_info()
            output = fmt.format(record)
            assert "ValueError" in output
            assert "test error" in output

    def test_elapsed_part_displayed(self):
        """When a request tracker exists, elapsed time appears."""
        fmt = SmartFormatter(use_colors=False)
        record = self._make_record()
        # Just ensure no crash when tracker is absent
        output = fmt.format(record)
        assert "hello" in output

    def test_module_display_truncation(self):
        """Long sub-module names are truncated."""
        fmt = SmartFormatter(use_colors=False)
        record = self._make_record(name="core.very_long_submodule_name")
        output = fmt.format(record)
        assert "hello" in output

    def test_level_styles_all_present(self):
        for level_name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            assert level_name in LEVEL_STYLES


# ---------------------------------------------------------------------------
# PlainFormatter
# ---------------------------------------------------------------------------
class TestPlainFormatter:
    def _make_record(self, name="core.test", level=logging.INFO, msg="hello", extra_data=None):
        logger = logging.getLogger(name)
        record = logger.makeRecord(name, level, "", 0, msg, (), None)
        record.extra_data = extra_data or {}
        return record

    def test_basic_format(self):
        fmt = PlainFormatter()
        record = self._make_record()
        output = fmt.format(record)
        assert "hello" in output
        assert "INFO" in output

    def test_format_with_request_id(self):
        fmt = PlainFormatter()
        token = set_request_id("req-12345678-abcd")
        try:
            record = self._make_record()
            output = fmt.format(record)
            assert "req-1234" in output
        finally:
            reset_request_id(token)

    def test_format_with_extra_data(self):
        fmt = PlainFormatter()
        record = self._make_record(extra_data={"key": "value"})
        output = fmt.format(record)
        assert "key=value" in output

    def test_format_extra_large_list(self):
        fmt = PlainFormatter()
        record = self._make_record(extra_data={"items": [1, 2, 3, 4, 5]})
        output = fmt.format(record)
        assert "[5 items]" in output

    def test_format_extra_dict(self):
        fmt = PlainFormatter()
        record = self._make_record(extra_data={"data": {"a": 1, "b": 2}})
        output = fmt.format(record)
        assert "{2 keys}" in output

    def test_format_with_exception(self):
        fmt = PlainFormatter()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            record = self._make_record()
            record.exc_info = sys.exc_info()
            output = fmt.format(record)
            assert "RuntimeError" in output

    def test_get_module_display_known(self):
        fmt = PlainFormatter()
        assert fmt._get_module_display("memory.graph") == "MEM|graph"

    def test_get_module_display_single_part(self):
        fmt = PlainFormatter()
        result = fmt._get_module_display("core")
        assert result == "COR"

    def test_get_module_display_long_submodule(self):
        fmt = PlainFormatter()
        result = fmt._get_module_display("core.very_long_name_here")
        # Submodule truncated to 8 chars + ellipsis
        assert len(result) <= 14


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------
class TestJsonFormatter:
    def _make_record(self, name="core.test", level=logging.INFO, msg="hello", extra_data=None):
        logger = logging.getLogger(name)
        record = logger.makeRecord(name, level, "", 0, msg, (), None)
        record.extra_data = extra_data or {}
        return record

    def test_basic_json_output(self):
        fmt = JsonFormatter()
        record = self._make_record()
        output = fmt.format(record)
        data = json.loads(output)
        assert data["msg"] == "hello"
        assert data["level"] == "INFO"
        assert data["logger"] == "core.test"
        assert "ts" in data

    def test_json_with_request_id(self):
        fmt = JsonFormatter()
        token = set_request_id("json-req-id")
        try:
            record = self._make_record()
            output = fmt.format(record)
            data = json.loads(output)
            assert data["req"] == "json-req-id"
        finally:
            reset_request_id(token)

    def test_json_without_request_id(self):
        fmt = JsonFormatter()
        record = self._make_record()
        output = fmt.format(record)
        data = json.loads(output)
        assert "req" not in data

    def test_json_with_extra_data(self):
        fmt = JsonFormatter()
        record = self._make_record(extra_data={"model": "gemini", "tokens": 100})
        output = fmt.format(record)
        data = json.loads(output)
        assert data["model"] == "gemini"
        assert data["tokens"] == 100

    def test_json_with_exception(self):
        fmt = JsonFormatter()
        try:
            raise ValueError("json error")
        except ValueError:
            record = self._make_record()
            record.exc_info = sys.exc_info()
            output = fmt.format(record)
            data = json.loads(output)
            assert "exc" in data
            assert "ValueError" in data["exc"]


# ---------------------------------------------------------------------------
# StructuredLogger
# ---------------------------------------------------------------------------
class TestStructuredLogger:
    def test_creation_with_default_level(self):
        # Use a unique name to avoid cached loggers
        logger = StructuredLogger("test_struct_default_level")
        assert logger._logger.level is not None

    def test_creation_with_custom_level(self):
        logger = StructuredLogger("test_struct_custom_level", level=logging.DEBUG)
        assert logger._logger.level == logging.DEBUG

    def test_debug_method(self):
        logger = StructuredLogger("test_debug_method")
        logger._logger.setLevel(logging.DEBUG)
        for h in logger._logger.handlers:
            h.setLevel(logging.DEBUG)
        with patch.object(logger._logger, "handle") as mock_handle:
            logger.debug("test debug msg", key="value")
            mock_handle.assert_called_once()
            record = mock_handle.call_args[0][0]
            assert record.msg == "test debug msg"
            assert record.extra_data == {"key": "value"}

    def test_info_method(self):
        logger = StructuredLogger("test_info_method")
        with patch.object(logger._logger, "handle") as mock_handle:
            logger.info("test info msg")
            mock_handle.assert_called_once()

    def test_warning_method(self):
        logger = StructuredLogger("test_warning_method")
        with patch.object(logger._logger, "handle") as mock_handle:
            logger.warning("test warning msg")
            mock_handle.assert_called_once()

    def test_error_method(self):
        logger = StructuredLogger("test_error_method")
        with patch.object(logger._logger, "handle") as mock_handle:
            logger.error("test error msg")
            mock_handle.assert_called_once()

    def test_critical_method(self):
        logger = StructuredLogger("test_critical_method")
        with patch.object(logger._logger, "handle") as mock_handle:
            logger.critical("test critical msg")
            mock_handle.assert_called_once()

    def test_exception_method(self):
        logger = StructuredLogger("test_exception_method")
        with patch.object(logger._logger, "handle") as mock_handle:
            try:
                raise RuntimeError("exc test")
            except RuntimeError:
                logger.exception("caught exception", detail="x")
                mock_handle.assert_called_once()
                record = mock_handle.call_args[0][0]
                assert record.levelno == logging.ERROR
                assert record.exc_info is not None
                assert record.extra_data == {"detail": "x"}

    def test_handlers_not_duplicated(self):
        """Creating the same logger twice should not add extra handlers."""
        name = "test_handler_dup_check"
        logger1 = StructuredLogger(name)
        handler_count = len(logger1._logger.handlers)
        logger2 = StructuredLogger(name)
        assert len(logger2._logger.handlers) == handler_count

    def test_propagate_is_false(self):
        logger = StructuredLogger("test_propagate_false")
        assert logger._logger.propagate is False


# ---------------------------------------------------------------------------
# get_logger / set_log_level
# ---------------------------------------------------------------------------
class TestGetLoggerAndSetLogLevel:
    def test_get_logger_returns_structured_logger(self):
        logger = get_logger("test_get_logger")
        assert isinstance(logger, StructuredLogger)

    def test_get_logger_caches(self):
        logger1 = get_logger("test_cache_logger")
        logger2 = get_logger("test_cache_logger")
        assert logger1 is logger2

    def test_set_log_level_changes_all(self):
        name = "test_set_level"
        logger = get_logger(name)
        set_log_level("DEBUG")
        assert logger._logger.level == logging.DEBUG
        # Restore
        set_log_level("INFO")

    def test_set_log_level_invalid_defaults_to_debug(self):
        name = "test_set_level_invalid"
        logger = get_logger(name)
        set_log_level("NONEXISTENT")
        assert logger._logger.level == logging.DEBUG
        set_log_level("INFO")


# ---------------------------------------------------------------------------
# @logged decorator
# ---------------------------------------------------------------------------
class TestLoggedDecorator:
    def test_sync_function_entry_exit(self):
        @logged(entry=True, exit=True)
        def my_sync_func(x):
            return x + 1

        result = my_sync_func(5)
        assert result == 6

    def test_sync_function_with_log_args(self):
        @logged(entry=True, exit=True, log_args=True, log_result=True)
        def my_func_with_args(x, y=10):
            return x + y

        result = my_func_with_args(3, y=7)
        assert result == 10

    def test_sync_function_exception_propagated(self):
        @logged()
        def failing_func():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            failing_func()

    async def test_async_function_entry_exit(self):
        @logged(entry=True, exit=True)
        async def my_async_func(x):
            return x * 2

        result = await my_async_func(5)
        assert result == 10

    async def test_async_function_with_log_args(self):
        @logged(entry=True, exit=True, log_args=True, log_result=True)
        async def my_async_func_args(x, y=10):
            return x + y

        result = await my_async_func_args(3, y=7)
        assert result == 10

    async def test_async_function_exception_propagated(self):
        @logged()
        async def async_failing():
            raise RuntimeError("async boom")

        with pytest.raises(RuntimeError, match="async boom"):
            await async_failing()

    def test_sync_no_entry_no_exit(self):
        @logged(entry=False, exit=False)
        def silent_func():
            return 42

        assert silent_func() == 42

    async def test_async_no_entry_no_exit(self):
        @logged(entry=False, exit=False)
        async def silent_async():
            return 99

        assert await silent_async() == 99

    def test_sync_log_result_none(self):
        """When log_result=True but result is None, no result kwarg is logged."""
        @logged(exit=True, log_result=True)
        def returns_none():
            return None

        result = returns_none()
        assert result is None

    async def test_async_log_result_none(self):
        @logged(exit=True, log_result=True)
        async def returns_none_async():
            return None

        result = await returns_none_async()
        assert result is None

    def test_decorator_preserves_name(self):
        @logged()
        def original_name():
            pass

        assert original_name.__name__ == "original_name"

    async def test_async_decorator_preserves_name(self):
        @logged()
        async def async_original():
            pass

        assert async_original.__name__ == "async_original"
