"""Tests for centralized configuration constants.

Validates that all magic numbers are defined in config.py with proper defaults
and support environment variable overrides.
"""

import os
from unittest.mock import patch


class TestTimeoutConstants:
    """Timeout constants merged from timeouts.py and scattered modules."""

    def test_timeout_api_call_default(self):
        from backend.config import TIMEOUT_API_CALL

        assert TIMEOUT_API_CALL == 180

    def test_timeout_stream_chunk_default(self):
        from backend.config import TIMEOUT_STREAM_CHUNK

        assert TIMEOUT_STREAM_CHUNK == 60

    def test_timeout_first_chunk_base_default(self):
        from backend.config import TIMEOUT_FIRST_CHUNK_BASE

        assert TIMEOUT_FIRST_CHUNK_BASE == 100

    def test_timeout_mcp_tool_default(self):
        from backend.config import TIMEOUT_MCP_TOOL

        assert TIMEOUT_MCP_TOOL == 300

    def test_timeout_deep_research_default(self):
        from backend.config import TIMEOUT_DEEP_RESEARCH

        assert TIMEOUT_DEEP_RESEARCH == 600

    def test_timeout_http_default(self):
        from backend.config import TIMEOUT_HTTP_DEFAULT

        assert TIMEOUT_HTTP_DEFAULT == 30.0

    def test_timeout_http_connect(self):
        from backend.config import TIMEOUT_HTTP_CONNECT

        assert TIMEOUT_HTTP_CONNECT == 5.0

    def test_timeout_env_override(self):
        """Environment variable should override default timeout via _get_int_env."""
        from backend.config import _get_int_env

        with patch.dict(os.environ, {"TIMEOUT_API_CALL": "300"}):
            assert _get_int_env("TIMEOUT_API_CALL", 180) == 300

    def test_timeout_env_invalid_falls_back(self):
        """Invalid env value should fall back to default."""
        from backend.config import _get_int_env

        with patch.dict(os.environ, {"TIMEOUT_API_CALL": "not_a_number"}):
            assert _get_int_env("TIMEOUT_API_CALL", 180) == 180


class TestSSEConstants:
    """SSE configuration constants from mcp_transport.py."""

    def test_sse_keepalive_interval_default(self):
        from backend.config import SSE_KEEPALIVE_INTERVAL

        assert SSE_KEEPALIVE_INTERVAL == 15

    def test_sse_connection_timeout_default(self):
        from backend.config import SSE_CONNECTION_TIMEOUT

        assert SSE_CONNECTION_TIMEOUT == 600

    def test_sse_retry_delay_default(self):
        from backend.config import SSE_RETRY_DELAY

        assert SSE_RETRY_DELAY == 3000


class TestRetryConstants:
    """Retry configuration constants scattered across modules."""

    def test_gemini_max_retries_default(self):
        from backend.config import GEMINI_MAX_RETRIES

        assert GEMINI_MAX_RETRIES == 5

    def test_gemini_retry_delay_base_default(self):
        from backend.config import GEMINI_RETRY_DELAY_BASE

        assert GEMINI_RETRY_DELAY_BASE == 2.0

    def test_stream_max_retries_default(self):
        from backend.config import STREAM_MAX_RETRIES

        assert STREAM_MAX_RETRIES == 5

    def test_embedding_max_retries_default(self):
        from backend.config import EMBEDDING_MAX_RETRIES

        assert EMBEDDING_MAX_RETRIES == 3


class TestFileLimitConstants:
    """File size and search limit constants."""

    def test_max_file_size_default(self):
        from backend.config import MAX_FILE_SIZE

        assert MAX_FILE_SIZE == 10 * 1024 * 1024

    def test_max_log_lines_default(self):
        from backend.config import MAX_LOG_LINES

        assert MAX_LOG_LINES == 1000

    def test_max_search_results_default(self):
        from backend.config import MAX_SEARCH_RESULTS

        assert MAX_SEARCH_RESULTS == 100


class TestMaxFileSizeConsistency:
    """MAX_FILE_SIZE should have the same value across all modules."""

    def test_system_observer_matches_config(self):
        from backend.config import MAX_FILE_SIZE as config_val
        from backend.core.tools.system_observer import MAX_FILE_SIZE as observer_val

        assert observer_val == config_val

    def test_file_tools_imports_from_config(self):
        from backend.config import MAX_FILE_SIZE as config_val
        from backend.core.mcp_tools.file_tools import MAX_FILE_SIZE as tools_val

        assert tools_val is config_val  # same object via import

    def test_system_observer_max_log_lines_matches_config(self):
        from backend.config import MAX_LOG_LINES as config_val
        from backend.core.tools.system_observer import MAX_LOG_LINES as observer_val

        assert observer_val == config_val

    def test_system_observer_max_search_results_matches_config(self):
        from backend.config import MAX_SEARCH_RESULTS as config_val
        from backend.core.tools.system_observer import MAX_SEARCH_RESULTS as observer_val

        assert observer_val == config_val


class TestReActConstants:
    """ReAct loop default configuration."""

    def test_react_max_loops_default(self):
        from backend.config import REACT_MAX_LOOPS

        assert REACT_MAX_LOOPS == 15

    def test_react_temperature_default(self):
        from backend.config import REACT_DEFAULT_TEMPERATURE

        assert REACT_DEFAULT_TEMPERATURE == 0.7

    def test_react_max_tokens_default(self):
        from backend.config import REACT_DEFAULT_MAX_TOKENS

        assert REACT_DEFAULT_MAX_TOKENS == 16384


class TestTimeoutsBackwardCompat:
    """timeouts.py TIMEOUTS object should use config.py values."""

    def test_timeouts_api_call_matches_config(self):
        from backend.config import TIMEOUT_API_CALL
        from backend.core.utils.timeouts import TIMEOUTS

        assert TIMEOUTS.API_CALL == TIMEOUT_API_CALL

    def test_timeouts_http_default_matches_config(self):
        from backend.config import TIMEOUT_HTTP_DEFAULT
        from backend.core.utils.timeouts import TIMEOUTS

        assert TIMEOUTS.HTTP_DEFAULT == TIMEOUT_HTTP_DEFAULT

    def test_timeouts_stream_chunk_matches_config(self):
        from backend.config import TIMEOUT_STREAM_CHUNK
        from backend.core.utils.timeouts import TIMEOUTS

        assert TIMEOUTS.STREAM_CHUNK == TIMEOUT_STREAM_CHUNK

    def test_service_timeouts_dict_available(self):
        from backend.core.utils.timeouts import SERVICE_TIMEOUTS

        assert "hass" in SERVICE_TIMEOUTS
        assert "default" in SERVICE_TIMEOUTS


class TestDecayNamedConstants:
    """Decay calculator magic numbers should be named constants."""

    def test_recency_age_hours_defined(self):
        from backend.memory.permanent.decay_calculator import RECENCY_AGE_HOURS

        assert RECENCY_AGE_HOURS == 168  # 1 week

    def test_recency_access_hours_defined(self):
        from backend.memory.permanent.decay_calculator import RECENCY_ACCESS_HOURS

        assert RECENCY_ACCESS_HOURS == 24

    def test_recency_boost_defined(self):
        from backend.memory.permanent.decay_calculator import RECENCY_BOOST

        assert RECENCY_BOOST == 1.3


class TestShutdownConstants:
    """Shutdown timeout constants from app.py."""

    def test_shutdown_task_timeout(self):
        from backend.config import SHUTDOWN_TASK_TIMEOUT

        assert SHUTDOWN_TASK_TIMEOUT == 3.0

    def test_shutdown_session_timeout(self):
        from backend.config import SHUTDOWN_SESSION_TIMEOUT

        assert SHUTDOWN_SESSION_TIMEOUT == 3.0

    def test_shutdown_http_pool_timeout(self):
        from backend.config import SHUTDOWN_HTTP_POOL_TIMEOUT

        assert SHUTDOWN_HTTP_POOL_TIMEOUT == 2.0
