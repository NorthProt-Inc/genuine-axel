"""Session and message persistence operations."""

import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.config import MESSAGE_ARCHIVE_AFTER_DAYS
from backend.core.logging import get_logger
from backend.core.utils.timezone import VANCOUVER_TZ
from backend.memory.recent.connection import SQLiteConnectionManager

MESSAGE_EXPIRY_DAYS = MESSAGE_ARCHIVE_AFTER_DAYS

_log = get_logger("memory.recent.repository")


class SessionRepository:
    """Handles all session and message CRUD operations.

    Args:
        conn_mgr: SQLiteConnectionManager instance.
    """

    def __init__(self, conn_mgr: SQLiteConnectionManager):
        self._conn_mgr = conn_mgr

    def save_message_immediate(
        self,
        session_id: str,
        role: str,
        content: str,
        timestamp: str,
        emotional_context: str = "neutral",
    ) -> bool:
        """Save a message immediately with duplicate prevention."""
        try:
            with self._conn_mgr.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT MAX(turn_id) FROM messages WHERE session_id = ?",
                    (session_id,),
                )
                row = cursor.fetchone()
                turn_id = (row[0] if row[0] is not None else -1) + 1

                conn.execute(
                    """INSERT OR IGNORE INTO messages
                       (session_id, turn_id, role, content, timestamp, emotional_context)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (session_id, turn_id, role, content, timestamp, emotional_context),
                )
                conn.commit()
                _log.debug("MEM msg_saved", session=session_id[:8], turn=turn_id, role=role)
                return True
        except Exception as e:
            _log.error("Immediate save failed", error=str(e), session_id=session_id[:8])
            return False

    def save_session(
        self,
        session_id: str,
        summary: str,
        key_topics: List[str],
        emotional_tone: str,
        turn_count: int,
        started_at: datetime,
        ended_at: datetime,
        messages: Optional[List[Dict]] = None,
    ) -> bool:
        """Save session data with messages atomically."""
        expires_at = datetime.now(VANCOUVER_TZ) + timedelta(days=MESSAGE_EXPIRY_DAYS)

        try:
            with self._conn_mgr.transaction() as conn:
                if messages:
                    cursor = conn.execute(
                        "SELECT MAX(turn_id) FROM messages WHERE session_id = ?",
                        (session_id,),
                    )
                    row = cursor.fetchone()
                    base_turn_id = (row[0] if row[0] is not None else -1) + 1

                    # PERF-023: Use executemany for batch insert
                    message_data = [
                        (
                            session_id,
                            base_turn_id + i,
                            msg.get("role", "unknown"),
                            msg.get("content", ""),
                            msg.get("timestamp", datetime.now(VANCOUVER_TZ).isoformat()),
                            msg.get("emotional_context", "neutral"),
                        )
                        for i, msg in enumerate(messages)
                    ]
                    conn.executemany(
                        """INSERT OR IGNORE INTO messages
                           (session_id, turn_id, role, content, timestamp, emotional_context)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        message_data,
                    )

                conn.execute(
                    """INSERT OR REPLACE INTO sessions
                       (session_id, summary, key_topics, emotional_tone,
                        turn_count, started_at, ended_at, expires_at, messages_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                    (
                        session_id,
                        summary,
                        json.dumps(key_topics, ensure_ascii=False),
                        emotional_tone,
                        turn_count,
                        started_at.isoformat(),
                        ended_at.isoformat(),
                        expires_at.isoformat(),
                    ),
                )

            _log.info(
                "MEM session_save",
                session_id=session_id[:8],
                turns=turn_count,
                msgs=len(messages) if messages else 0,
            )
            return True
        except Exception as e:
            _log.error("Save session failed", error=str(e), session_id=session_id)
            return False

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Get messages for a session, ordered by turn_id."""
        try:
            with self._conn_mgr.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """SELECT role, content, timestamp, turn_id
                       FROM messages
                       WHERE session_id = ?
                       ORDER BY turn_id ASC""",
                    (session_id,),
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            _log.error("Get session messages failed", error=str(e))
            return []

    def get_session_detail(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata and messages."""
        try:
            with self._conn_mgr.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?",
                    (session_id,),
                )
                session = cursor.fetchone()

                if not session:
                    return None

                session_dict = dict(session)
                messages = []
                if session_dict.get("messages_json"):
                    try:
                        messages = json.loads(session_dict["messages_json"])
                    except json.JSONDecodeError:
                        pass

            if not messages:
                messages = self.get_session_messages(session_id)

            return {"session": session_dict, "messages": messages}
        except Exception as e:
            _log.error("Get session detail failed", error=str(e), session_id=session_id)
            return None

    def search_by_topic(self, topic: str, limit: int = 5) -> List[Dict]:
        """Search sessions by topic keyword."""
        try:
            with self._conn_mgr.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """SELECT * FROM sessions
                       WHERE key_topics LIKE ?
                       ORDER BY ended_at DESC LIMIT ?""",
                    (f"%{topic}%", limit),
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            _log.error("Topic search failed", error=str(e), topic=topic)
            return []

    def get_sessions_by_date(
        self,
        from_date: str,
        to_date: Optional[str] = None,
        limit: int = 10,
        max_tokens: int = 3000,
    ) -> str:
        """Query messages by date range, formatted as text."""
        if not to_date:
            to_date = from_date

        try:
            with self._conn_mgr.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """SELECT role, content, timestamp, emotional_context
                       FROM messages
                       WHERE timestamp >= ? AND timestamp < date(?, '+1 day')
                       ORDER BY timestamp ASC LIMIT ?""",
                    (from_date, to_date, limit * 2),
                )
                rows = cursor.fetchall()

            if not rows:
                return f"{from_date} ~ {to_date} 기간에 대화 기록이 없습니다."

            parts: list[str] = []
            char_count = 0

            for row in rows:
                try:
                    ts = row["timestamp"][:16] if row["timestamp"] else ""
                    date_str = ts[5:10] if len(ts) >= 10 else "?"
                    time_str = ts[11:16] if len(ts) >= 16 else "?"
                except (TypeError, IndexError):
                    date_str = "?"
                    time_str = "?"

                role = row["role"] or "?"
                content = (row["content"] or "")[:200].replace("\n", " ")
                msg_line = f"[{date_str} {time_str}] {role}: {content}..."

                if char_count + len(msg_line) > max_tokens * 2:
                    parts.append("...(더 많은 기록 있음)")
                    break
                parts.append(msg_line)
                char_count += len(msg_line)

            _log.debug("MEM qry_temporal", from_d=from_date, to_d=to_date, res=len(rows))
            return "\n".join(parts)
        except Exception as e:
            _log.error("Temporal message search failed", error=str(e))
            return "기억 조회 중 오류 발생"

    def get_recent_summaries(self, limit: int = 5, max_tokens: int = 2000) -> str:
        """Retrieve recent conversations grouped by date."""
        try:
            with self._conn_mgr.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """SELECT role, content, timestamp, emotional_context
                       FROM messages ORDER BY timestamp DESC LIMIT ?""",
                    (limit * 20,),
                )
                rows = cursor.fetchall()

            if not rows:
                return "최근 대화 기록이 없습니다."

            parts: list[str] = []
            char_count = 0
            date_counts: Counter[str] = Counter()
            all_messages: list[dict] = []

            for row in rows:
                ts = row["timestamp"][:10] if row["timestamp"] else ""
                if ts:
                    date_counts[ts] += 1
                all_messages.append(
                    {
                        "role": row["role"],
                        "content": row["content"],
                        "timestamp": row["timestamp"],
                        "emotional_context": row["emotional_context"],
                    }
                )

            if date_counts:
                parts.append("날짜별 대화량:")
                for d, cnt in sorted(date_counts.items(), reverse=True)[:10]:
                    parts.append(f"  {d}: {cnt}개")
                    char_count += 20

            # PERF-024: DB already orders by timestamp DESC, no need to re-sort
            recent_msgs = all_messages[:20]
            if recent_msgs:
                parts.append("\n최근 대화:")
                for msg in recent_msgs:
                    ts = msg.get("timestamp", "")[:16] if msg.get("timestamp") else ""
                    role = msg.get("role", "?")
                    content_preview = msg.get("content", "")[:80].replace("\n", " ")
                    msg_line = f"  [{ts}] {role}: {content_preview}..."
                    if char_count + len(msg_line) > max_tokens * 2:
                        parts.append("  ...(더 많은 기록 있음)")
                        break
                    parts.append(msg_line)
                    char_count += len(msg_line)

            if char_count < max_tokens * 2:
                import random

                cutoff_date = (datetime.now(VANCOUVER_TZ) - timedelta(days=2)).strftime(
                    "%Y-%m-%d"
                )
                older_msgs = [
                    m for m in all_messages if m.get("timestamp", "")[:10] < cutoff_date
                ]
                if older_msgs:
                    samples = random.sample(older_msgs, min(5, len(older_msgs)))
                    parts.append("\n과거 대화 샘플:")
                    for msg in samples:
                        date_str = (
                            msg.get("timestamp", "")[:10]
                            if msg.get("timestamp")
                            else "?"
                        )
                        content_preview = msg.get("content", "")[:80].replace("\n", " ")
                        parts.append(
                            f"  [{date_str}] {msg.get('role', '?')}: {content_preview}..."
                        )

            return "\n".join(parts) if parts else "최근 대화 기록이 없습니다."
        except Exception as e:
            _log.error("Get summaries failed", error=str(e))
            return "기억 조회 중 오류 발생"

    def get_time_since_last_session(self) -> Optional[timedelta]:
        """Get time elapsed since the last session ended."""
        try:
            with self._conn_mgr.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT ended_at FROM sessions ORDER BY ended_at DESC LIMIT 1"
                )
                row = cursor.fetchone()
                if row:
                    last_ended = datetime.fromisoformat(row[0])
                    return datetime.now(VANCOUVER_TZ) - last_ended.replace(
                        tzinfo=VANCOUVER_TZ
                    )
                return None
        except Exception as e:
            _log.error("Get time since last session failed", error=str(e))
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get session/message count statistics."""
        try:
            with self._conn_mgr.get_connection() as conn:
                # PERF-024: Combine 3 count queries into single query
                result = conn.execute(
                    """SELECT
                        (SELECT COUNT(*) FROM sessions) as session_count,
                        (SELECT COUNT(*) FROM messages) as message_count,
                        (SELECT COUNT(*) FROM sessions WHERE expires_at < datetime('now')) as expired_count
                    """
                ).fetchone()

                return {
                    "total_sessions": result[0],
                    "total_messages": result[1],
                    "expired_pending_cleanup": result[2],
                    "expiry_days": MESSAGE_EXPIRY_DAYS,
                }
        except Exception as e:
            _log.error("Get stats failed", error=str(e))
            return {}

    def get_interaction_stats(self) -> Dict[str, Any]:
        """Get usage statistics summary by model and tier."""
        try:
            with self._conn_mgr.get_connection() as conn:
                conn.row_factory = sqlite3.Row

                by_model = [
                    dict(row)
                    for row in conn.execute(
                        """SELECT effective_model,
                                  COUNT(*) as call_count,
                                  AVG(latency_ms) as avg_latency_ms,
                                  SUM(tokens_in) as total_tokens_in,
                                  SUM(tokens_out) as total_tokens_out
                           FROM interaction_logs
                           GROUP BY effective_model ORDER BY call_count DESC"""
                    ).fetchall()
                ]

                by_tier = [
                    dict(row)
                    for row in conn.execute(
                        """SELECT tier,
                                  COUNT(*) as call_count,
                                  AVG(latency_ms) as avg_latency_ms,
                                  SUM(tokens_in) as total_tokens_in,
                                  SUM(tokens_out) as total_tokens_out
                           FROM interaction_logs
                           GROUP BY tier ORDER BY call_count DESC"""
                    ).fetchall()
                ]

                by_router_reason = [
                    dict(row)
                    for row in conn.execute(
                        """SELECT router_reason, COUNT(*) as count
                           FROM interaction_logs
                           GROUP BY router_reason ORDER BY count DESC LIMIT 10"""
                    ).fetchall()
                ]

                last_24h = dict(
                    conn.execute(
                        """SELECT COUNT(*) as total_calls,
                                  AVG(latency_ms) as avg_latency_ms,
                                  SUM(tokens_in) as total_tokens_in,
                                  SUM(tokens_out) as total_tokens_out,
                                  SUM(CASE WHEN refusal_detected = 1 THEN 1 ELSE 0 END) as refusal_count
                           FROM interaction_logs
                           WHERE ts >= datetime('now', '-24 hours')"""
                    ).fetchone()
                )

                return {
                    "by_model": by_model,
                    "by_tier": by_tier,
                    "by_router_reason": by_router_reason,
                    "last_24h": last_24h,
                }
        except Exception as e:
            _log.error("Get interaction stats failed", error=str(e))
            return {}

    def get_expired_sessions(self, limit: int = 10) -> List[str]:
        """Get session IDs with expired and unsummarized sessions."""
        with self._conn_mgr.get_connection() as conn:
            cursor = conn.execute(
                """SELECT session_id FROM sessions
                   WHERE expires_at < datetime('now') AND summary IS NULL
                   LIMIT ?""",
                (limit,),
            )
            return [row[0] for row in cursor.fetchall()]

    def get_session_messages_for_archive(self, session_id: str) -> List[Dict]:
        """Get full message records for archiving."""
        with self._conn_mgr.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT id, turn_id, role, content, timestamp, emotional_context
                   FROM messages WHERE session_id = ? ORDER BY turn_id ASC""",
                (session_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def archive_session(self, session_id: str, messages: List[Dict], summary: str):
        """Archive messages and update session summary atomically."""
        with self._conn_mgr.transaction() as conn:
            # PERF-023: Use executemany for batch insert
            message_data = [
                (
                    session_id,
                    msg["turn_id"],
                    msg["role"],
                    msg["content"],
                    msg["timestamp"],
                    msg["emotional_context"],
                )
                for msg in messages
            ]
            conn.executemany(
                """INSERT INTO archived_messages
                   (session_id, turn_id, role, content, timestamp, emotional_context)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                message_data,
            )
            conn.execute(
                "UPDATE sessions SET summary = ? WHERE session_id = ?",
                (summary, session_id),
            )
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
