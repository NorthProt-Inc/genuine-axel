"""Tests for session/meta data migration from axel PostgreSQL."""

import json
import pytest
from backend.memory.recent.connection import SQLiteConnectionManager
from backend.memory.recent.schema import SchemaManager


@pytest.fixture
def sqlite_db(tmp_path):
    """Initialized SQLite database for testing."""
    mgr = SQLiteConnectionManager(db_path=tmp_path / "test_sessions.db")
    SchemaManager(mgr).initialize()
    yield mgr
    mgr.close()


class TestSessionMigration:

    def test_session_roundtrip(self, sqlite_db):
        """Imported session should be queryable."""
        with sqlite_db.get_connection() as conn:
            conn.execute(
                """INSERT INTO sessions
                (session_id, summary, key_topics, emotional_tone,
                 turn_count, started_at, ended_at, messages_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "test-session-1",
                    "Discussion about Python",
                    '["python", "coding"]',
                    "positive",
                    5,
                    "2025-01-01T10:00:00",
                    "2025-01-01T11:00:00",
                    "[]",
                ),
            )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                ("test-session-1",),
            ).fetchone()

        assert row is not None
        assert row[1] == "test-session-1"

    def test_messages_ordered(self, sqlite_db):
        """Messages should preserve turn_id ordering."""
        with sqlite_db.get_connection() as conn:
            for i in range(5):
                conn.execute(
                    """INSERT INTO messages
                    (session_id, turn_id, role, content, timestamp)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        "session-A",
                        i,
                        "user" if i % 2 == 0 else "assistant",
                        f"Message {i}",
                        f"2025-01-01T10:{i:02d}:00",
                    ),
                )
            conn.commit()

            rows = conn.execute(
                "SELECT turn_id FROM messages WHERE session_id = ? ORDER BY turn_id",
                ("session-A",),
            ).fetchall()

        turn_ids = [r[0] for r in rows]
        assert turn_ids == [0, 1, 2, 3, 4]

    def test_access_patterns_imported(self, sqlite_db):
        """Access patterns should be queryable for hot memories."""
        with sqlite_db.get_connection() as conn:
            for i in range(3):
                conn.execute(
                    """INSERT INTO access_patterns
                    (query_text, matched_memory_ids, relevance_scores,
                     channel_id, created_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        f"query {i}",
                        json.dumps([f"mem-{i}"]),
                        json.dumps([0.9]),
                        "default",
                        "2025-01-01T10:00:00",
                    ),
                )
            conn.commit()

            rows = conn.execute(
                "SELECT * FROM access_patterns ORDER BY created_at DESC"
            ).fetchall()

        assert len(rows) == 3
