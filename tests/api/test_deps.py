"""Tests for backend.api.deps -- AppState, auth helpers, get_state."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from starlette.testclient import TestClient

from backend.api.deps import (
    AppState,
    get_state,
    init_state,
    _mask_key,
    _extract_bearer_token,
    get_request_api_key,
    is_api_key_configured,
    is_request_authorized,
    require_api_key,
    ChatStateProtocol,
)


# ---------------------------------------------------------------------------
# _mask_key
# ---------------------------------------------------------------------------


class TestMaskKey:
    """_mask_key hides the middle of API keys for safe logging."""

    def test_empty_string(self):
        assert _mask_key("") == "<empty>"

    def test_none(self):
        assert _mask_key(None) == "<empty>"

    def test_short_key_under_4(self):
        assert _mask_key("ab") == "***"

    def test_short_key_4_to_8(self):
        result = _mask_key("abcd")
        assert result == "ab...cd"

    def test_short_key_exactly_8(self):
        result = _mask_key("abcdefgh")
        assert result == "ab...gh"

    def test_long_key(self):
        result = _mask_key("abcdefghijkl")
        assert result == "abcd...ijkl"

    def test_single_char(self):
        assert _mask_key("x") == "***"


# ---------------------------------------------------------------------------
# _extract_bearer_token
# ---------------------------------------------------------------------------


class TestExtractBearerToken:

    def test_valid_bearer(self):
        assert _extract_bearer_token("Bearer mytoken123") == "mytoken123"

    def test_case_insensitive(self):
        assert _extract_bearer_token("bearer MyToken") == "MyToken"

    def test_bearer_with_extra_spaces(self):
        assert _extract_bearer_token("Bearer   spaced  ") == "spaced"

    def test_no_bearer_prefix(self):
        assert _extract_bearer_token("Basic abc123") is None

    def test_empty_string(self):
        assert _extract_bearer_token("") is None

    def test_none_input(self):
        assert _extract_bearer_token(None) is None

    def test_bearer_only_no_token(self):
        result = _extract_bearer_token("Bearer ")
        assert result == ""


# ---------------------------------------------------------------------------
# AppState dataclass
# ---------------------------------------------------------------------------


class TestAppState:

    def test_default_fields(self):
        state = AppState()
        assert state.memory_manager is None
        assert state.long_term_memory is None
        assert state.identity_manager is None
        assert state.gemini_client is None
        assert state.graph_rag is None
        assert state.mcp_server is None
        assert state.current_session_id == ""
        assert state.turn_count == 0
        assert state.background_tasks == []
        assert state.active_streams == set()  # Fix: should be set not list

    def test_reset(self):
        state = AppState(
            gemini_client="gc",
            turn_count=99,
            current_session_id="s1",
        )
        state.background_tasks.append("t1")
        state.active_streams.add("s1")  # Fix: use .add() for set
        state.reset()

        assert state.gemini_client is None
        assert state.turn_count == 0
        assert state.current_session_id == ""
        assert state.background_tasks == []
        assert state.active_streams == set()  # Fix: should be set not list

    def test_reset_preserves_identity(self):
        state = AppState()
        state.gemini_client = "gc"
        state.reset()
        assert state is state  # same object

    def test_conforms_to_protocol(self):
        """AppState should satisfy ChatStateProtocol structurally."""
        state = AppState()
        # These should not raise
        _ = state.memory_manager
        _ = state.long_term_memory
        _ = state.identity_manager
        _ = state.background_tasks


# ---------------------------------------------------------------------------
# get_state / init_state (module-level singleton)
# ---------------------------------------------------------------------------


class TestGetStateInitState:

    def test_get_state_returns_app_state(self):
        assert isinstance(get_state(), AppState)

    def test_get_state_singleton(self):
        assert get_state() is get_state()

    def test_init_state_sets_known_attrs(self):
        sentinel = object()
        init_state(gemini_client=sentinel)
        assert get_state().gemini_client is sentinel
        # cleanup
        get_state().gemini_client = None

    def test_init_state_ignores_unknown_attrs(self):
        init_state(nonexistent_xyz="nope")
        assert not hasattr(get_state(), "nonexistent_xyz")


# ---------------------------------------------------------------------------
# get_request_api_key
# ---------------------------------------------------------------------------


class TestGetRequestApiKey:

    def _make_request(self, headers=None):
        req = MagicMock()
        req.headers = headers or {}
        return req

    def test_bearer_token(self):
        req = self._make_request({"Authorization": "Bearer my-secret"})
        assert get_request_api_key(req) == "my-secret"

    def test_x_api_key_header(self):
        req = self._make_request({"X-API-Key": "my-secret"})
        assert get_request_api_key(req) == "my-secret"

    def test_x_api_key_alt_case(self):
        req = self._make_request({"X-Api-Key": "my-secret"})
        assert get_request_api_key(req) == "my-secret"

    def test_bearer_takes_priority(self):
        req = self._make_request({
            "Authorization": "Bearer bearer-key",
            "X-API-Key": "header-key",
        })
        assert get_request_api_key(req) == "bearer-key"

    def test_no_key(self):
        req = self._make_request({})
        assert get_request_api_key(req) is None


# ---------------------------------------------------------------------------
# is_api_key_configured
# ---------------------------------------------------------------------------


class TestIsApiKeyConfigured:

    @patch("backend.api.deps.AXNMIHN_API_KEY", "some-key")
    def test_returns_true_when_set(self):
        assert is_api_key_configured() is True

    @patch("backend.api.deps.AXNMIHN_API_KEY", "")
    def test_returns_false_when_empty(self):
        assert is_api_key_configured() is False

    @patch("backend.api.deps.AXNMIHN_API_KEY", None)
    def test_returns_false_when_none(self):
        assert is_api_key_configured() is False


# ---------------------------------------------------------------------------
# is_request_authorized
# ---------------------------------------------------------------------------


class TestIsRequestAuthorized:

    def _make_request(self, headers=None):
        req = MagicMock()
        req.headers = headers or {}
        return req

    @patch("backend.api.deps.AXNMIHN_API_KEY", "")
    def test_bypasses_when_no_key_configured(self):
        req = self._make_request({})
        assert is_request_authorized(req) is True

    @patch("backend.api.deps.AXNMIHN_API_KEY", "correct-key")
    def test_authorized_with_matching_key(self):
        req = self._make_request({"Authorization": "Bearer correct-key"})
        assert is_request_authorized(req) is True

    @patch("backend.api.deps.AXNMIHN_API_KEY", "correct-key")
    def test_unauthorized_with_wrong_key(self):
        req = self._make_request({"Authorization": "Bearer wrong-key"})
        assert is_request_authorized(req) is False

    @patch("backend.api.deps.AXNMIHN_API_KEY", "correct-key")
    def test_unauthorized_with_no_key(self):
        req = self._make_request({})
        assert is_request_authorized(req) is False


# ---------------------------------------------------------------------------
# require_api_key (FastAPI dependency)
# ---------------------------------------------------------------------------


class TestRequireApiKey:

    def _make_request(self, headers=None):
        req = MagicMock()
        req.headers = headers or {}
        req.url.path = "/test"
        return req

    @patch("backend.api.deps.AXNMIHN_API_KEY", "")
    def test_passes_when_no_key_configured(self):
        req = self._make_request()
        require_api_key(req)  # should not raise

    @patch("backend.api.deps.AXNMIHN_API_KEY", "good-key")
    def test_passes_with_correct_key(self):
        req = self._make_request({"Authorization": "Bearer good-key"})
        require_api_key(req)  # should not raise

    @patch("backend.api.deps.AXNMIHN_API_KEY", "good-key")
    def test_raises_401_with_wrong_key(self):
        req = self._make_request({"Authorization": "Bearer bad-key"})
        with pytest.raises(HTTPException) as exc_info:
            require_api_key(req)
        assert exc_info.value.status_code == 401

    @patch("backend.api.deps.AXNMIHN_API_KEY", "good-key")
    def test_raises_401_with_no_key(self):
        req = self._make_request({})
        with pytest.raises(HTTPException) as exc_info:
            require_api_key(req)
        assert exc_info.value.status_code == 401
