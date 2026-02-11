"""Tests for backend.memory.pg.session_repository — PgSessionRepository.

Covers:
- save_message_immediate()
- save_session() with and without messages
- get_session_messages()
- get_session_detail() found and not found
- _escape_like()
- search_by_topic()
- get_sessions_by_date()
- get_recent_summaries()
- get_time_since_last_session()
- get_stats()
- get_interaction_stats()
- get_expired_sessions()
- get_session_messages_for_archive()
- archive_session()
"""

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.memory.pg.session_repository import PgSessionRepository


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def repo(conn_mgr_with_mocks):
    return PgSessionRepository(conn_mgr_with_mocks)


# ============================================================================
# save_message_immediate()
# ============================================================================

class TestSaveMessageImmediate:

    def test_success(self, conn_mgr_with_mocks):
        """save_message_immediate uses get_connection directly, so we mock it."""
        fake_cursor = MagicMock()
        fake_cursor.fetchone.return_value = (0,)
        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _fake_gc():
            yield fake_conn

        conn_mgr_with_mocks.get_connection = _fake_gc
        repo = PgSessionRepository(conn_mgr_with_mocks)

        result = repo.save_message_immediate(
            session_id="sess-1",
            role="user",
            content="hello",
            timestamp="2025-01-01T00:00:00",
        )
        assert result is True

    def test_failure_returns_false(self, conn_mgr_with_mocks):
        @contextmanager
        def _raise():
            raise Exception("db error")
            yield  # pragma: no cover

        conn_mgr_with_mocks.get_connection = _raise
        repo = PgSessionRepository(conn_mgr_with_mocks)

        result = repo.save_message_immediate("s", "user", "msg", "ts")
        assert result is False


# ============================================================================
# save_session()
# ============================================================================

class TestSaveSession:

    def test_success_without_messages(self, conn_mgr_with_mocks):
        fake_cursor = MagicMock()
        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _fake_gc():
            yield fake_conn

        conn_mgr_with_mocks.get_connection = _fake_gc
        repo = PgSessionRepository(conn_mgr_with_mocks)

        result = repo.save_session(
            session_id="sess-1",
            summary="test summary",
            key_topics=["topic1"],
            emotional_tone="neutral",
            turn_count=5,
            started_at=datetime(2025, 1, 1),
            ended_at=datetime(2025, 1, 1, 1, 0),
        )
        assert result is True

    def test_success_with_messages(self, conn_mgr_with_mocks):
        fake_cursor = MagicMock()
        fake_cursor.fetchone.return_value = (0,)
        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _fake_gc():
            yield fake_conn

        conn_mgr_with_mocks.get_connection = _fake_gc
        repo = PgSessionRepository(conn_mgr_with_mocks)

        messages = [
            {"role": "user", "content": "hi", "timestamp": "2025-01-01T00:00:00"},
            {"role": "assistant", "content": "hello"},
        ]
        with patch("backend.memory.pg.session_repository.execute_batch") as mock_eb:
            result = repo.save_session(
                session_id="sess-1",
                summary="summary",
                key_topics=["topic"],
                emotional_tone="positive",
                turn_count=2,
                started_at=datetime(2025, 1, 1),
                ended_at=datetime(2025, 1, 1, 0, 5),
                messages=messages,
            )
        assert result is True
        # 1 fetchone (for turn_id) + 1 session insert = 2 execute calls
        assert fake_cursor.execute.call_count == 2
        # 1 execute_batch call for messages
        mock_eb.assert_called_once()

    def test_failure_returns_false(self, conn_mgr_with_mocks):
        @contextmanager
        def _raise():
            raise Exception("db error")
            yield  # pragma: no cover

        conn_mgr_with_mocks.get_connection = _raise
        repo = PgSessionRepository(conn_mgr_with_mocks)

        result = repo.save_session("s", "sum", [], "neutral", 0, datetime.now(), datetime.now())
        assert result is False


# ============================================================================
# get_session_messages()
# ============================================================================

class TestGetSessionMessages:

    def test_returns_messages(self, repo):
        repo._conn.execute_dict.return_value = [
            {"role": "user", "content": "hi", "timestamp": "ts", "turn_id": 0}
        ]
        result = repo.get_session_messages("sess-1")
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_returns_empty_on_error(self, repo):
        repo._conn.execute_dict.side_effect = Exception("db error")
        result = repo.get_session_messages("sess-1")
        assert result == []


# ============================================================================
# get_session_detail()
# ============================================================================

class TestGetSessionDetail:

    def test_found(self, repo):
        repo._conn.execute_dict.side_effect = [
            [{"session_id": "sess-1", "summary": "test"}],  # session query
            [{"role": "user", "content": "hi"}],  # messages query
        ]
        result = repo.get_session_detail("sess-1")
        assert result is not None
        assert "session" in result
        assert "messages" in result

    def test_not_found(self, repo):
        repo._conn.execute_dict.return_value = []
        result = repo.get_session_detail("nonexistent")
        assert result is None

    def test_error_returns_none(self, repo):
        repo._conn.execute_dict.side_effect = Exception("db error")
        result = repo.get_session_detail("sess-1")
        assert result is None


# ============================================================================
# _escape_like()
# ============================================================================

class TestEscapeLike:

    def test_no_metacharacters(self):
        assert PgSessionRepository._escape_like("hello") == "hello"

    def test_percent_escaped(self):
        assert PgSessionRepository._escape_like("50%") == r"50\%"

    def test_underscore_escaped(self):
        assert PgSessionRepository._escape_like("a_b") == r"a\_b"

    def test_backslash_escaped(self):
        assert PgSessionRepository._escape_like(r"a\b") == r"a\\b"

    def test_multiple_metacharacters(self):
        result = PgSessionRepository._escape_like("a%b_c")
        assert result == r"a\%b\_c"


# ============================================================================
# search_by_topic()
# ============================================================================

class TestSearchByTopic:

    def test_returns_results(self, repo):
        repo._conn.execute_dict.return_value = [{"session_id": "s1", "summary": "test"}]
        result = repo.search_by_topic("python")
        assert len(result) == 1

    def test_error_returns_empty(self, repo):
        repo._conn.execute_dict.side_effect = Exception("db error")
        result = repo.search_by_topic("python")
        assert result == []


# ============================================================================
# get_sessions_by_date()
# ============================================================================

class TestGetSessionsByDate:

    def test_returns_formatted_text(self, repo):
        repo._conn.execute_dict.return_value = [
            {"role": "user", "content": "hello world", "timestamp": "2025-01-15T14:30:00",
             "emotional_context": "neutral"},
        ]
        result = repo.get_sessions_by_date("2025-01-15")
        assert "user" in result
        assert "hello world" in result

    def test_no_results(self, repo):
        repo._conn.execute_dict.return_value = []
        result = repo.get_sessions_by_date("2025-01-15")
        assert "기록이 없습니다" in result

    def test_default_to_date(self, repo):
        repo._conn.execute_dict.return_value = []
        repo.get_sessions_by_date("2025-01-15")
        call_params = repo._conn.execute_dict.call_args[0][1]
        assert call_params[0] == "2025-01-15"  # from_date
        assert call_params[1] == "2025-01-15"  # to_date (defaulted)

    def test_error_returns_error_message(self, repo):
        repo._conn.execute_dict.side_effect = Exception("db error")
        result = repo.get_sessions_by_date("2025-01-15")
        assert "오류" in result

    def test_truncation_on_large_result(self, repo):
        rows = [
            {"role": "user", "content": "x" * 200, "timestamp": "2025-01-15T14:30:00",
             "emotional_context": "neutral"}
            for _ in range(500)
        ]
        repo._conn.execute_dict.return_value = rows
        result = repo.get_sessions_by_date("2025-01-15", max_tokens=50)
        assert "더 많은 기록" in result


# ============================================================================
# get_recent_summaries()
# ============================================================================

class TestGetRecentSummaries:

    def test_returns_formatted_text(self, repo):
        repo._conn.execute_dict.return_value = [
            {"role": "user", "content": "hello", "timestamp": "2025-01-15T14:30:00",
             "emotional_context": "neutral"},
        ]
        result = repo.get_recent_summaries()
        assert "user" in result.lower() or "대화" in result

    def test_empty_returns_message(self, repo):
        repo._conn.execute_dict.return_value = []
        result = repo.get_recent_summaries()
        assert "기록이 없습니다" in result

    def test_error_returns_error_message(self, repo):
        repo._conn.execute_dict.side_effect = Exception("db error")
        result = repo.get_recent_summaries()
        assert "오류" in result


# ============================================================================
# get_time_since_last_session()
# ============================================================================

class TestGetTimeSinceLastSession:

    def test_returns_timedelta_from_datetime(self, repo):
        from backend.core.utils.timezone import VANCOUVER_TZ
        recent = datetime.now(VANCOUVER_TZ) - timedelta(hours=1)
        repo._conn.execute_one.return_value = (recent,)
        result = repo.get_time_since_last_session()
        assert isinstance(result, timedelta)
        assert result.total_seconds() > 0

    def test_returns_timedelta_from_string(self, repo):
        from backend.core.utils.timezone import VANCOUVER_TZ
        recent = (datetime.now(VANCOUVER_TZ) - timedelta(hours=1)).isoformat()
        repo._conn.execute_one.return_value = (recent,)
        result = repo.get_time_since_last_session()
        assert isinstance(result, timedelta)

    def test_naive_datetime_gets_timezone(self, repo):
        recent = datetime.now() - timedelta(hours=1)
        repo._conn.execute_one.return_value = (recent,)
        result = repo.get_time_since_last_session()
        assert isinstance(result, timedelta)

    def test_no_session_returns_none(self, repo):
        repo._conn.execute_one.return_value = None
        result = repo.get_time_since_last_session()
        assert result is None

    def test_null_ended_at_returns_none(self, repo):
        repo._conn.execute_one.return_value = (None,)
        result = repo.get_time_since_last_session()
        assert result is None

    def test_error_returns_none(self, repo):
        repo._conn.execute_one.side_effect = Exception("db error")
        result = repo.get_time_since_last_session()
        assert result is None


# ============================================================================
# get_stats()
# ============================================================================

class TestGetStats:

    def test_returns_stats_dict(self, repo):
        repo._conn.execute_one.side_effect = [(10,), (100,)]
        result = repo.get_stats()
        assert result["total_sessions"] == 10
        assert result["total_messages"] == 100
        assert "expiry_days" in result

    def test_error_returns_empty(self, repo):
        repo._conn.execute_one.side_effect = Exception("db error")
        result = repo.get_stats()
        assert result == {}


# ============================================================================
# get_interaction_stats()
# ============================================================================

class TestGetInteractionStats:

    def test_returns_stats(self, repo):
        repo._conn.execute_dict.side_effect = [
            [{"effective_model": "claude", "call_count": 5}],  # by_model
            [{"tier": "premium", "call_count": 5}],  # by_tier
            [{"router_reason": "default", "count": 5}],  # by_router_reason
            [{"total_calls": 10, "avg_latency_ms": 100}],  # last_24h
        ]
        result = repo.get_interaction_stats()
        assert "by_model" in result
        assert "by_tier" in result
        assert "by_router_reason" in result
        assert "last_24h" in result

    def test_error_returns_empty(self, repo):
        repo._conn.execute_dict.side_effect = Exception("db error")
        result = repo.get_interaction_stats()
        assert result == {}


# ============================================================================
# get_expired_sessions()
# ============================================================================

class TestGetExpiredSessions:

    def test_returns_session_ids(self, repo):
        repo._conn.execute.return_value = [("sess-1",), ("sess-2",)]
        result = repo.get_expired_sessions()
        assert result == ["sess-1", "sess-2"]

    def test_empty_list(self, repo):
        repo._conn.execute.return_value = []
        result = repo.get_expired_sessions()
        assert result == []


# ============================================================================
# get_session_messages_for_archive()
# ============================================================================

class TestGetSessionMessagesForArchive:

    def test_returns_messages(self, repo):
        repo._conn.execute_dict.return_value = [
            {"id": 1, "turn_id": 0, "role": "user", "content": "hi",
             "timestamp": "ts", "emotional_context": "neutral"}
        ]
        result = repo.get_session_messages_for_archive("sess-1")
        assert len(result) == 1


# ============================================================================
# archive_session()
# ============================================================================

class TestArchiveSession:

    def test_archives_messages_and_updates_summary(self, conn_mgr_with_mocks):
        fake_cursor = MagicMock()
        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _fake_gc():
            yield fake_conn

        conn_mgr_with_mocks.get_connection = _fake_gc
        repo = PgSessionRepository(conn_mgr_with_mocks)

        messages = [
            {"turn_id": 0, "role": "user", "content": "hi",
             "timestamp": "ts", "emotional_context": "neutral"},
        ]
        with patch("backend.memory.pg.session_repository.execute_batch") as mock_eb:
            repo.archive_session("sess-1", messages, "summary text")
        # 1 update (sessions) = 1 execute call
        assert fake_cursor.execute.call_count == 1
        # 1 execute_batch call for archived_messages
        mock_eb.assert_called_once()
