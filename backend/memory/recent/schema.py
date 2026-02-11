"""Database schema initialization and version-based migration."""

import sqlite3

from backend.core.logging import get_logger
from backend.memory.recent.connection import SQLiteConnectionManager

_log = get_logger("memory.recent.schema")

# Bump this when adding a new migration step.
CURRENT_SCHEMA_VERSION = 2


class SchemaManager:
    """Creates and migrates session archive database tables.

    Uses ``PRAGMA user_version`` to track schema versions so that
    migrations run exactly once per database file.

    Args:
        conn_mgr: SQLiteConnectionManager instance.
    """

    def __init__(self, conn_mgr: SQLiteConnectionManager):
        self._conn_mgr = conn_mgr

    def _get_version(self, conn: sqlite3.Connection) -> int:
        return conn.execute("PRAGMA user_version").fetchone()[0]

    def _set_version(self, conn: sqlite3.Connection, version: int):
        conn.execute(f"PRAGMA user_version = {version}")

    def initialize(self):
        """Create all tables/indexes and run pending migrations."""
        with self._conn_mgr.get_connection() as conn:
            current = self._get_version(conn)

            # ── v0 → v1: initial schema ─────────────────────────────
            if current < 1:
                self._create_initial_schema(conn)
                self._set_version(conn, 1)

            # v1 → v2: user_behavior_metrics + access_patterns tables
            if current < 2:
                self._migrate_v1_to_v2(conn)
                self._set_version(conn, 2)

            conn.commit()
            _log.debug(
                "Database schema initialized",
                version=self._get_version(conn),
            )

    def _create_initial_schema(self, conn: sqlite3.Connection):
        """Create v1 tables and indexes."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE,
                summary TEXT,
                key_topics TEXT,
                emotional_tone TEXT,
                turn_count INTEGER,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                messages_json TEXT
            )
        """)

        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN messages_json TEXT")
            _log.info("Added messages_json column to sessions table")
        except sqlite3.OperationalError:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                turn_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP,
                emotional_context TEXT
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_timestamp
            ON messages(timestamp DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_expires
            ON sessions(expires_at)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS interaction_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                conversation_id TEXT,
                turn_id INTEGER,
                effective_model TEXT NOT NULL,
                tier TEXT NOT NULL,
                router_reason TEXT NOT NULL,
                routing_features_json TEXT,
                manual_override INTEGER DEFAULT 0,
                latency_ms INTEGER,
                ttft_ms INTEGER,
                tokens_in INTEGER,
                tokens_out INTEGER,
                tool_calls_json TEXT,
                refusal_detected INTEGER DEFAULT 0,
                response_chars INTEGER,
                hedge_ratio REAL,
                avg_sentence_len REAL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_interaction_logs_ts
            ON interaction_logs(ts)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_interaction_logs_tier
            ON interaction_logs(tier, ts)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_interaction_logs_created
            ON interaction_logs(ts DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_interaction_logs_router
            ON interaction_logs(router_reason)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS archived_messages (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                turn_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP,
                emotional_context TEXT,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_archived_session
            ON archived_messages(session_id)
        """)

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection):
        """v1→v2: Add user_behavior_metrics and access_patterns tables."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_behavior_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                hourly_activity_rate TEXT NOT NULL DEFAULT '[]',
                avg_latency_ms REAL DEFAULT 1000.0,
                tool_usage_frequency REAL DEFAULT 0.0,
                session_duration_avg REAL DEFAULT 600.0,
                daily_active_hours REAL DEFAULT 4.0,
                peak_hours TEXT DEFAULT '[]',
                engagement_score REAL DEFAULT 0.5,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_text TEXT,
                matched_memory_ids TEXT,
                relevance_scores TEXT,
                channel_id TEXT DEFAULT 'default',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_access_patterns_created
            ON access_patterns(created_at DESC)
        """)

        _log.info("Migrated schema v1 → v2 (user_behavior_metrics, access_patterns)")
