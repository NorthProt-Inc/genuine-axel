"""Tests for backend.core.utils.timeouts."""

import os
from unittest.mock import patch

import pytest
from backend.core.utils.timeouts import (
    Timeouts,
    TIMEOUTS,
    SERVICE_TIMEOUTS,
    _env_int,
    _env_float,
)


# ---------------------------------------------------------------------------
# _env_int
# ---------------------------------------------------------------------------


class TestEnvInt:
    """Tests for the _env_int helper."""

    def test_returns_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_ENV_INT_UNSET", None)
            assert _env_int("TEST_ENV_INT_UNSET", 42) == 42

    def test_reads_int_from_env(self):
        with patch.dict(os.environ, {"TEST_ENV_INT": "100"}):
            assert _env_int("TEST_ENV_INT", 0) == 100

    def test_invalid_value_returns_default(self):
        with patch.dict(os.environ, {"TEST_ENV_INT_BAD": "not_a_number"}):
            assert _env_int("TEST_ENV_INT_BAD", 99) == 99

    def test_empty_string_returns_default(self):
        with patch.dict(os.environ, {"TEST_ENV_INT_EMPTY": ""}):
            assert _env_int("TEST_ENV_INT_EMPTY", 55) == 55

    def test_negative_int(self):
        with patch.dict(os.environ, {"TEST_ENV_INT_NEG": "-5"}):
            assert _env_int("TEST_ENV_INT_NEG", 0) == -5

    def test_zero(self):
        with patch.dict(os.environ, {"TEST_ENV_INT_ZERO": "0"}):
            assert _env_int("TEST_ENV_INT_ZERO", 99) == 0


# ---------------------------------------------------------------------------
# _env_float
# ---------------------------------------------------------------------------


class TestEnvFloat:
    """Tests for the _env_float helper."""

    def test_returns_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_ENV_FLOAT_UNSET", None)
            assert _env_float("TEST_ENV_FLOAT_UNSET", 3.14) == 3.14

    def test_reads_float_from_env(self):
        with patch.dict(os.environ, {"TEST_ENV_FLOAT": "2.5"}):
            assert _env_float("TEST_ENV_FLOAT", 0.0) == 2.5

    def test_reads_int_as_float(self):
        with patch.dict(os.environ, {"TEST_ENV_FLOAT_INT": "10"}):
            assert _env_float("TEST_ENV_FLOAT_INT", 0.0) == 10.0

    def test_invalid_value_returns_default(self):
        with patch.dict(os.environ, {"TEST_ENV_FLOAT_BAD": "abc"}):
            assert _env_float("TEST_ENV_FLOAT_BAD", 1.5) == 1.5

    def test_empty_string_returns_default(self):
        with patch.dict(os.environ, {"TEST_ENV_FLOAT_EMPTY": ""}):
            assert _env_float("TEST_ENV_FLOAT_EMPTY", 7.7) == 7.7

    def test_negative_float(self):
        with patch.dict(os.environ, {"TEST_ENV_FLOAT_NEG": "-3.5"}):
            assert _env_float("TEST_ENV_FLOAT_NEG", 0.0) == -3.5

    def test_zero_float(self):
        with patch.dict(os.environ, {"TEST_ENV_FLOAT_ZERO": "0.0"}):
            assert _env_float("TEST_ENV_FLOAT_ZERO", 99.0) == 0.0


# ---------------------------------------------------------------------------
# Timeouts dataclass
# ---------------------------------------------------------------------------


class TestTimeouts:
    """Tests for the Timeouts frozen dataclass."""

    def test_is_frozen(self):
        t = Timeouts()
        with pytest.raises(AttributeError):
            t.API_CALL = 999

    def test_default_api_call(self):
        t = Timeouts()
        assert isinstance(t.API_CALL, int)
        assert t.API_CALL > 0

    def test_default_stream_chunk(self):
        t = Timeouts()
        assert isinstance(t.STREAM_CHUNK, int)
        assert t.STREAM_CHUNK > 0

    def test_default_first_chunk_base(self):
        t = Timeouts()
        assert isinstance(t.FIRST_CHUNK_BASE, int)
        assert t.FIRST_CHUNK_BASE > 0

    def test_default_deep_research(self):
        t = Timeouts()
        assert isinstance(t.DEEP_RESEARCH, int)
        assert t.DEEP_RESEARCH > 0

    def test_default_http_default(self):
        t = Timeouts()
        assert isinstance(t.HTTP_DEFAULT, float)
        assert t.HTTP_DEFAULT > 0

    def test_default_http_connect(self):
        t = Timeouts()
        assert isinstance(t.HTTP_CONNECT, float)
        assert t.HTTP_CONNECT > 0

    def test_default_http_hass(self):
        t = Timeouts()
        assert isinstance(t.HTTP_HASS, float)
        assert t.HTTP_HASS > 0

    def test_http_deepgram_constant(self):
        t = Timeouts()
        assert t.HTTP_DEEPGRAM == 30.0

    def test_circuit_breaker_default(self):
        t = Timeouts()
        assert t.CIRCUIT_BREAKER_DEFAULT == 30

    def test_circuit_breaker_rate_limit(self):
        t = Timeouts()
        assert t.CIRCUIT_BREAKER_RATE_LIMIT == 300

    def test_circuit_breaker_server_error(self):
        t = Timeouts()
        assert t.CIRCUIT_BREAKER_SERVER_ERROR == 60

    def test_deep_research_larger_than_api_call(self):
        """DEEP_RESEARCH should be larger than a normal API_CALL timeout."""
        t = Timeouts()
        assert t.DEEP_RESEARCH >= t.API_CALL


# ---------------------------------------------------------------------------
# TIMEOUTS singleton
# ---------------------------------------------------------------------------


class TestTimeoutsSingleton:
    """Tests for the module-level TIMEOUTS instance."""

    def test_is_timeouts_instance(self):
        assert isinstance(TIMEOUTS, Timeouts)

    def test_api_call_matches_default(self):
        # When no env override, should use default 180
        assert TIMEOUTS.API_CALL == _env_int("TIMEOUT_API_CALL", 180)

    def test_stream_chunk_matches_default(self):
        assert TIMEOUTS.STREAM_CHUNK == _env_int("TIMEOUT_STREAM_CHUNK", 60)

    def test_http_default_matches_env(self):
        assert TIMEOUTS.HTTP_DEFAULT == _env_float("TIMEOUT_HTTP_DEFAULT", 30.0)


# ---------------------------------------------------------------------------
# SERVICE_TIMEOUTS dict
# ---------------------------------------------------------------------------


class TestServiceTimeouts:
    """Tests for the SERVICE_TIMEOUTS dict."""

    def test_is_dict(self):
        assert isinstance(SERVICE_TIMEOUTS, dict)

    def test_has_required_keys(self):
        assert "hass" in SERVICE_TIMEOUTS
        assert "deepgram" in SERVICE_TIMEOUTS
        assert "tts" in SERVICE_TIMEOUTS
        assert "default" in SERVICE_TIMEOUTS

    def test_all_values_are_floats(self):
        for key, value in SERVICE_TIMEOUTS.items():
            assert isinstance(value, (int, float)), f"{key} is not numeric"
            assert value > 0, f"{key} timeout should be positive"

    def test_hass_matches_timeouts(self):
        assert SERVICE_TIMEOUTS["hass"] == TIMEOUTS.HTTP_HASS

    def test_deepgram_matches_timeouts(self):
        assert SERVICE_TIMEOUTS["deepgram"] == TIMEOUTS.HTTP_DEEPGRAM

    def test_default_matches_timeouts(self):
        assert SERVICE_TIMEOUTS["default"] == TIMEOUTS.HTTP_DEFAULT

    def test_tts_includes_buffer(self):
        """TTS timeout is the base TTS timeout + 5s buffer."""
        base_tts = _env_float("TTS_SYNTHESIS_TIMEOUT", 30.0)
        assert SERVICE_TIMEOUTS["tts"] == base_tts + 5.0
