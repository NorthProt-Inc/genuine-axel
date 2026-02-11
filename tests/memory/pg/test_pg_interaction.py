"""Tests for backend.memory.pg.interaction_logger — PgInteractionLogger.

Covers:
- log_interaction() success and failure
- _resolve_session_id() with existing and missing sessions
- get_recent_logs() success and failure
"""

from unittest.mock import MagicMock

import pytest

from backend.memory.pg.interaction_logger import PgInteractionLogger


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def logger(conn_mgr_with_mocks):
    return PgInteractionLogger(conn_mgr_with_mocks)


# ============================================================================
# log_interaction()
# ============================================================================

class TestLogInteraction:

    def test_success_returns_true(self, logger):
        # _resolve_session_id returns None when session not found
        logger._conn.execute_one.return_value = None
        logger._conn.execute.return_value = []

        result = logger.log_interaction(
            routing_decision={
                "effective_model": "claude-sonnet",
                "tier": "premium",
                "router_reason": "default",
            },
            conversation_id="conv-1",
            turn_id=0,
            latency_ms=150,
        )
        assert result is True
        logger._conn.execute.assert_called_once()

    def test_success_with_all_params(self, logger):
        logger._conn.execute_one.return_value = (1,)  # session exists
        logger._conn.execute.return_value = []

        result = logger.log_interaction(
            routing_decision={
                "effective_model": "claude-sonnet",
                "tier": "premium",
                "router_reason": "default",
                "error": None,
            },
            conversation_id="conv-1",
            turn_id=0,
            latency_ms=150,
            ttft_ms=50,
            tokens_in=100,
            tokens_out=200,
            tool_calls=[{"name": "search"}],
            refusal_detected=False,
            response_text="hello",
        )
        assert result is True

    def test_failure_returns_false(self, logger):
        logger._conn.execute.side_effect = Exception("db error")
        result = logger.log_interaction(
            routing_decision={"effective_model": "x", "tier": "y", "router_reason": "z"},
        )
        assert result is False

    def test_tool_calls_serialized_as_json(self, logger):
        logger._conn.execute_one.return_value = None
        logger._conn.execute.return_value = []

        logger.log_interaction(
            routing_decision={"effective_model": "x", "tier": "y", "router_reason": "z"},
            tool_calls=[{"name": "search", "args": {"q": "test"}}],
        )
        call_params = logger._conn.execute.call_args[0][1]
        # tool_calls is the 10th parameter (index 9)
        assert "search" in call_params[9]

    def test_no_tool_calls_serialized_as_empty_array(self, logger):
        logger._conn.execute_one.return_value = None
        logger._conn.execute.return_value = []

        logger.log_interaction(
            routing_decision={"effective_model": "x", "tier": "y", "router_reason": "z"},
            tool_calls=None,
        )
        call_params = logger._conn.execute.call_args[0][1]
        assert call_params[9] == "[]"


# ============================================================================
# _resolve_session_id()
# ============================================================================

class TestResolveSessionId:

    def test_returns_session_id_if_exists(self, logger):
        logger._conn.execute_one.return_value = (1,)
        result = logger._resolve_session_id("sess-1")
        assert result == "sess-1"

    def test_returns_none_if_not_exists(self, logger):
        logger._conn.execute_one.return_value = None
        result = logger._resolve_session_id("nonexistent")
        assert result is None

    def test_returns_none_for_none_input(self, logger):
        result = logger._resolve_session_id(None)
        assert result is None

    def test_returns_none_for_empty_string(self, logger):
        result = logger._resolve_session_id("")
        assert result is None


# ============================================================================
# get_recent_logs()
# ============================================================================

class TestGetRecentLogs:

    def test_returns_list(self, logger):
        logger._conn.execute_dict.return_value = [
            {"id": 1, "effective_model": "claude", "ts": "2025-01-01"},
        ]
        result = logger.get_recent_logs(limit=10)
        assert len(result) == 1

    def test_default_limit(self, logger):
        logger._conn.execute_dict.return_value = []
        logger.get_recent_logs()
        call_params = logger._conn.execute_dict.call_args[0][1]
        assert call_params == (20,)

    def test_custom_limit(self, logger):
        logger._conn.execute_dict.return_value = []
        logger.get_recent_logs(limit=5)
        call_params = logger._conn.execute_dict.call_args[0][1]
        assert call_params == (5,)

    def test_error_returns_empty(self, logger):
        logger._conn.execute_dict.side_effect = Exception("db error")
        result = logger.get_recent_logs()
        assert result == []
