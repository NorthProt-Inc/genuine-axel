"""Tests for backend.core.logging.request_tracker module.

Covers: RequestTracker dataclass, start_request, get_tracker,
log_gateway, log_memory, log_search, end_request.
"""

import time
from unittest.mock import patch

import pytest

from backend.core.logging.logging import Colors
from backend.core.logging.request_tracker import (
    RequestTracker,
    start_request,
    get_tracker,
    log_gateway,
    log_memory,
    log_search,
    end_request,
    _current_request,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_tracker():
    """Ensure no leftover tracker between tests."""
    _current_request.set(None)
    yield
    _current_request.set(None)


@pytest.fixture(autouse=True)
def _patch_colors():
    """end_request() references Colors.DIM / .RESET / .INFO / .WARNING
    as class-level attributes.  Ensure they resolve to empty strings
    so the summary formatting does not raise AttributeError."""
    attrs = {"DIM": "", "RESET": "", "INFO": "", "WARNING": ""}
    for name, val in attrs.items():
        if not hasattr(Colors, name):
            setattr(Colors, name, val)
    yield
    for name in attrs:
        try:
            delattr(Colors, name)
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# RequestTracker dataclass
# ---------------------------------------------------------------------------
class TestRequestTracker:
    def test_defaults(self):
        tracker = RequestTracker()
        assert len(tracker.request_id) == 6
        assert tracker.input_preview == ""
        assert tracker.start_time > 0
        assert tracker.gateway_intent == ""
        assert tracker.gateway_model == ""
        assert tracker.llm_model == ""
        assert tracker.llm_tokens == 0
        assert tracker.search_results == 0
        assert tracker.tts_chars == 0

    def test_elapsed_ms(self):
        tracker = RequestTracker(start_time=time.time() - 0.1)
        elapsed = tracker.elapsed_ms()
        assert elapsed >= 90  # at least ~100ms with some tolerance
        assert elapsed < 1000

    def test_custom_fields(self):
        tracker = RequestTracker(
            input_preview="test input",
            gateway_intent="chat",
            gateway_model="gemini",
        )
        assert tracker.input_preview == "test input"
        assert tracker.gateway_intent == "chat"
        assert tracker.gateway_model == "gemini"


# ---------------------------------------------------------------------------
# start_request
# ---------------------------------------------------------------------------
class TestStartRequest:
    def test_creates_and_stores_tracker(self):
        tracker = start_request("hello world")
        assert tracker is not None
        assert get_tracker() is tracker
        assert tracker.input_preview == "hello world"

    def test_long_input_truncated(self):
        long_input = "a" * 50
        tracker = start_request(long_input)
        assert tracker.input_preview == "a" * 30 + "..."

    def test_newlines_replaced(self):
        tracker = start_request("line1\nline2")
        assert "\n" not in tracker.input_preview
        assert "line1 line2" == tracker.input_preview

    def test_short_input_not_truncated(self):
        tracker = start_request("short")
        assert tracker.input_preview == "short"

    def test_exactly_30_chars_not_truncated(self):
        exact = "x" * 30
        tracker = start_request(exact)
        assert tracker.input_preview == exact


# ---------------------------------------------------------------------------
# get_tracker
# ---------------------------------------------------------------------------
class TestGetTracker:
    def test_returns_none_when_no_request(self):
        assert get_tracker() is None

    def test_returns_current_tracker(self):
        tracker = start_request("test")
        assert get_tracker() is tracker


# ---------------------------------------------------------------------------
# log_gateway
# ---------------------------------------------------------------------------
class TestLogGateway:
    def test_updates_tracker(self):
        tracker = start_request("test")
        log_gateway("chat", "gemini-2.5-flash", 150.5)
        assert tracker.gateway_intent == "chat"
        assert tracker.gateway_model == "gemini-2.5-flash"
        assert tracker.gateway_ms == 150.5

    def test_no_crash_without_tracker(self):
        """log_gateway should be a no-op if no tracker is active."""
        log_gateway("chat", "gemini", 100.0)  # No exception


# ---------------------------------------------------------------------------
# log_memory
# ---------------------------------------------------------------------------
class TestLogMemory:
    def test_updates_tracker(self):
        tracker = start_request("test")
        log_memory(longterm=5, working=10, tokens=500)
        assert tracker.memory_longterm == 5
        assert tracker.memory_working == 10
        assert tracker.memory_tokens == 500

    def test_partial_update(self):
        tracker = start_request("test")
        log_memory(longterm=3)
        assert tracker.memory_longterm == 3
        assert tracker.memory_working == 0
        assert tracker.memory_tokens == 0

    def test_no_crash_without_tracker(self):
        log_memory(longterm=5)  # No exception


# ---------------------------------------------------------------------------
# log_search
# ---------------------------------------------------------------------------
class TestLogSearch:
    def test_updates_tracker(self):
        tracker = start_request("test")
        log_search("python async", 10, 250.0)
        assert tracker.search_query == "python async"
        assert tracker.search_results == 10
        assert tracker.search_ms == 250.0

    def test_no_crash_without_tracker(self):
        log_search("query", 5, 100.0)  # No exception


# ---------------------------------------------------------------------------
# end_request
# ---------------------------------------------------------------------------
class TestEndRequest:
    def test_clears_tracker(self):
        start_request("test")
        assert get_tracker() is not None
        end_request()
        assert get_tracker() is None

    def test_no_crash_without_tracker(self):
        end_request()  # No exception

    def test_summary_includes_request_id(self):
        tracker = start_request("hello world")
        with patch("backend.core.logging.request_tracker._log") as mock_logger:
            end_request()
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert "REQ summary" in call_args[0][0]
            summary = call_args[1].get("summary", "")
            assert tracker.request_id in summary

    def test_summary_includes_gateway_info(self):
        start_request("test")
        log_gateway("chat", "gemini-flash", 120.0)
        with patch("backend.core.logging.request_tracker._log") as mock_logger:
            end_request()
            summary = mock_logger.info.call_args[1].get("summary", "")
            assert "Gateway" in summary
            assert "chat" in summary
            assert "gemini-flash" in summary

    def test_summary_includes_memory_info(self):
        start_request("test")
        log_memory(longterm=5, working=3, tokens=1000)
        with patch("backend.core.logging.request_tracker._log") as mock_logger:
            end_request()
            summary = mock_logger.info.call_args[1].get("summary", "")
            assert "Memory" in summary
            assert "5 long-term" in summary

    def test_summary_includes_search_info(self):
        start_request("test")
        log_search("python", 8, 200.0)
        with patch("backend.core.logging.request_tracker._log") as mock_logger:
            end_request()
            summary = mock_logger.info.call_args[1].get("summary", "")
            assert "Search" in summary
            assert "8 results" in summary

    def test_summary_includes_llm_info(self):
        tracker = start_request("test")
        tracker.llm_model = "gemini-2.5-flash"
        tracker.llm_tokens = 500
        tracker.llm_ms = 2500.0
        with patch("backend.core.logging.request_tracker._log") as mock_logger:
            end_request()
            summary = mock_logger.info.call_args[1].get("summary", "")
            assert "LLM" in summary
            assert "gemini-2.5-flash" in summary

    def test_summary_includes_tts_info(self):
        tracker = start_request("test")
        tracker.tts_chars = 100
        tracker.tts_ms = 1500.0
        with patch("backend.core.logging.request_tracker._log") as mock_logger:
            end_request()
            summary = mock_logger.info.call_args[1].get("summary", "")
            assert "TTS" in summary
            assert "100 chars" in summary

    def test_summary_includes_hass_action(self):
        tracker = start_request("test")
        tracker.hass_action = "turn_on_light"
        with patch("backend.core.logging.request_tracker._log") as mock_logger:
            end_request()
            summary = mock_logger.info.call_args[1].get("summary", "")
            assert "Action" in summary
            assert "turn_on_light" in summary

    def test_summary_includes_total_time(self):
        start_request("test")
        with patch("backend.core.logging.request_tracker._log") as mock_logger:
            end_request()
            summary = mock_logger.info.call_args[1].get("summary", "")
            assert "total" in summary.lower()
