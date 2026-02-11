"""Tests for cross-channel session router (Wave 2.2)."""

import pytest

from backend.core.session.router import SessionRouter
from backend.core.session.state_machine import SessionState


class TestSessionRouter:
    """Tests for SessionRouter cross-channel session management."""

    def test_create_new_session(self):
        router = SessionRouter()
        session = router.resolve("user-1", "discord")
        assert session.user_id == "user-1"
        assert session.channel_id == "discord"
        assert session.state == SessionState.ACTIVE

    def test_resolve_existing_session(self):
        router = SessionRouter()
        s1 = router.resolve("user-1", "discord")
        s2 = router.resolve("user-1", "discord")
        assert s1.session_id == s2.session_id

    def test_cross_channel_creates_new_session(self):
        router = SessionRouter()
        s1 = router.resolve("user-1", "discord")
        s2 = router.resolve("user-1", "telegram")
        assert s1.session_id != s2.session_id

    def test_cross_channel_metadata(self):
        router = SessionRouter()
        router.resolve("user-1", "discord")
        s2 = router.resolve("user-1", "telegram")
        assert s2.previous_channel == "discord"

    def test_end_session(self):
        router = SessionRouter()
        session = router.resolve("user-1", "discord")
        router.end_session(session.session_id)
        new_session = router.resolve("user-1", "discord")
        assert new_session.session_id != session.session_id

    def test_get_user_sessions(self):
        router = SessionRouter()
        router.resolve("user-1", "discord")
        router.resolve("user-1", "telegram")
        sessions = router.get_user_sessions("user-1")
        assert len(sessions) == 2

    def test_update_activity(self):
        router = SessionRouter()
        session = router.resolve("user-1", "discord")
        old_activity = session.last_activity
        import time
        time.sleep(0.01)
        router.update_activity(session.session_id)
        updated = router.resolve("user-1", "discord")
        assert updated.last_activity >= old_activity

    def test_nonexistent_user_returns_empty(self):
        router = SessionRouter()
        sessions = router.get_user_sessions("nobody")
        assert sessions == []

    def test_session_has_id(self):
        router = SessionRouter()
        session = router.resolve("user-1", "cli")
        assert len(session.session_id) > 0
