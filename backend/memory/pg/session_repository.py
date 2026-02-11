"""M2 Sessions/Messages — PostgreSQL replacement for SQLite SessionRepository."""

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from psycopg2.extras import execute_batch

from backend.config import MESSAGE_ARCHIVE_AFTER_DAYS
from backend.core.logging import get_logger
from backend.core.utils.timezone import VANCOUVER_TZ

from .connection import PgConnectionManager

MESSAGE_EXPIRY_DAYS = MESSAGE_ARCHIVE_AFTER_DAYS

_log = get_logger("memory.pg.session")


class PgSessionRepository:
    """Drop-in replacement for ``SessionRepository`` backed by PostgreSQL.

    Maintains the same public API so ``SessionArchive`` delegates work transparently.
    """

    def __init__(self, conn_mgr: PgConnectionManager):
        self._conn = conn_mgr

    # ── Messages ─────────────────────────────────────────────────────

    def _ensure_session_exists(self, cur: Any, session_id: str, timestamp: str) -> None:
        """Create session row if it doesn't exist (avoids FK violation on messages)."""
        cur.execute(
            """INSERT INTO sessions (session_id, user_id, started_at)
               VALUES (%s, %s, %s)
               ON CONFLICT (session_id) DO NOTHING""",
            (session_id, "Mark", timestamp),
        )

    def save_message_immediate(
        self,
        session_id: str,
        role: str,
        content: str,
        timestamp: str,
        emotional_context: str = "neutral",
    ) -> bool:
        try:
            with self._conn.get_connection() as conn:
                with conn.cursor() as cur:
                    self._ensure_session_exists(cur, session_id, timestamp)

                    cur.execute(
                        "SELECT COALESCE(MAX(turn_id), -1) + 1 FROM messages WHERE session_id = %s",
                        (session_id,),
                    )
                    turn_id = cur.fetchone()[0]

                    cur.execute(
                        """INSERT INTO messages
                               (session_id, turn_id, role, content, timestamp, emotional_context)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON CONFLICT (session_id, turn_id, role) DO NOTHING""",
                        (session_id, turn_id, role, content, timestamp, emotional_context),
                    )
            _log.debug("MEM msg_saved", session=session_id[:8], turn=turn_id, role=role)
            return True
        except Exception as e:
            _log.error("Immediate save failed", error=str(e), session_id=session_id[:8])
            return False

    # ── Sessions ─────────────────────────────────────────────────────

    def save_session(
        self,
        session_id: str,
        summary: str,
        key_topics: List[str],
        emotional_tone: str,
        turn_count: int,
        started_at: datetime,
        ended_at: datetime,
        messages: List[Dict] = None,
    ) -> bool:
        try:
            with self._conn.get_connection() as conn:
                with conn.cursor() as cur:
                    # Upsert session first to satisfy FK on messages
                    cur.execute(
                        """INSERT INTO sessions
                               (session_id, user_id, summary, key_topics, emotional_tone,
                                turn_count, started_at, ended_at)
                           VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                           ON CONFLICT (session_id) DO UPDATE SET
                               summary = EXCLUDED.summary,
                               key_topics = EXCLUDED.key_topics,
                               emotional_tone = EXCLUDED.emotional_tone,
                               turn_count = EXCLUDED.turn_count,
                               ended_at = EXCLUDED.ended_at""",
                        (
                            session_id,
                            "Mark",
                            summary,
                            json.dumps(key_topics, ensure_ascii=False),
                            emotional_tone,
                            turn_count,
                            started_at.isoformat(),
                            ended_at.isoformat(),
                        ),
                    )

                    if messages:
                        cur.execute(
                            "SELECT COALESCE(MAX(turn_id), -1) + 1 FROM messages WHERE session_id = %s",
                            (session_id,),
                        )
                        base_turn_id = cur.fetchone()[0]

                        # PERF-025: Use execute_batch for batch insert
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
                        execute_batch(
                            cur,
                            """INSERT INTO messages
                                   (session_id, turn_id, role, content, timestamp, emotional_context)
                               VALUES (%s, %s, %s, %s, %s, %s)
                               ON CONFLICT (session_id, turn_id, role) DO NOTHING""",
                            message_data,
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

    # ── Queries ──────────────────────────────────────────────────────

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        try:
            return self._conn.execute_dict(
                """SELECT role, content, timestamp, turn_id
                   FROM messages WHERE session_id = %s ORDER BY turn_id ASC""",
                (session_id,),
            )
        except Exception as e:
            _log.error("Get session messages failed", error=str(e))
            return []

    def get_session_detail(self, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            rows = self._conn.execute_dict(
                "SELECT * FROM sessions WHERE session_id = %s",
                (session_id,),
            )
            if not rows:
                return None

            session_dict = rows[0]
            messages = self.get_session_messages(session_id)
            return {"session": session_dict, "messages": messages}
        except Exception as e:
            _log.error("Get session detail failed", error=str(e), session_id=session_id)
            return None

    @staticmethod
    def _escape_like(s: str) -> str:
        """Escape LIKE metacharacters for safe ILIKE patterns."""
        return re.sub(r"([%_\\])", r"\\\1", s)

    def search_by_topic(self, topic: str, limit: int = 5) -> List[Dict]:
        try:
            safe_topic = self._escape_like(topic)
            return self._conn.execute_dict(
                """SELECT * FROM sessions
                   WHERE key_topics @> %s::jsonb OR summary ILIKE %s
                   ORDER BY ended_at DESC NULLS LAST LIMIT %s""",
                (json.dumps([topic], ensure_ascii=False), f"%{safe_topic}%", limit),
            )
        except Exception as e:
            _log.error("Topic search failed", error=str(e), topic=topic)
            return []

    def get_sessions_by_date(
        self,
        from_date: str,
        to_date: str = None,
        limit: int = 10,
        max_tokens: int = 3000,
    ) -> str:
        if not to_date:
            to_date = from_date

        try:
            rows = self._conn.execute_dict(
                """SELECT role, content, timestamp, emotional_context
                   FROM messages
                   WHERE timestamp >= %s AND timestamp < (%s::date + INTERVAL '1 day')::text
                   ORDER BY timestamp ASC LIMIT %s""",
                (from_date, to_date, limit * 2),
            )

            if not rows:
                return f"{from_date} ~ {to_date} 기간에 대화 기록이 없습니다."

            parts: list[str] = []
            char_count = 0

            for row in rows:
                try:
                    ts = str(row.get("timestamp", ""))[:16]
                    date_str = ts[5:10] if len(ts) >= 10 else "?"
                    time_str = ts[11:16] if len(ts) >= 16 else "?"
                except (TypeError, IndexError):
                    date_str = "?"
                    time_str = "?"

                role = row.get("role", "?")
                content = str(row.get("content", ""))[:200].replace("\n", " ")
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
        try:
            rows = self._conn.execute_dict(
                """SELECT role, content, timestamp, emotional_context
                   FROM messages ORDER BY timestamp DESC LIMIT %s""",
                (limit * 20,),
            )

            if not rows:
                return "최근 대화 기록이 없습니다."

            parts: list[str] = []
            char_count = 0
            date_counts: Counter[str] = Counter()
            all_messages: list[dict] = []

            for row in rows:
                ts = str(row.get("timestamp", ""))[:10]
                if ts:
                    date_counts[ts] += 1
                all_messages.append(row)

            if date_counts:
                parts.append("날짜별 대화량:")
                for d, cnt in sorted(date_counts.items(), reverse=True)[:10]:
                    parts.append(f"  {d}: {cnt}개")
                    char_count += 20

            recent_msgs = sorted(
                all_messages, key=lambda m: str(m.get("timestamp", "")), reverse=True
            )[:20]
            if recent_msgs:
                parts.append("\n최근 대화:")
                for msg in recent_msgs:
                    ts = str(msg.get("timestamp", ""))[:16]
                    role = msg.get("role", "?")
                    content_preview = str(msg.get("content", ""))[:80].replace("\n", " ")
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
                    m for m in all_messages if str(m.get("timestamp", ""))[:10] < cutoff_date
                ]
                if older_msgs:
                    samples = random.sample(older_msgs, min(5, len(older_msgs)))
                    parts.append("\n과거 대화 샘플:")
                    for msg in samples:
                        date_str = str(msg.get("timestamp", ""))[:10] or "?"
                        content_preview = str(msg.get("content", ""))[:80].replace("\n", " ")
                        parts.append(
                            f"  [{date_str}] {msg.get('role', '?')}: {content_preview}..."
                        )

            return "\n".join(parts) if parts else "최근 대화 기록이 없습니다."
        except Exception as e:
            _log.error("Get summaries failed", error=str(e))
            return "기억 조회 중 오류 발생"

    def get_time_since_last_session(self) -> Optional[timedelta]:
        try:
            row = self._conn.execute_one(
                "SELECT ended_at FROM sessions ORDER BY ended_at DESC NULLS LAST LIMIT 1"
            )
            if row and row[0]:
                last_ended = row[0]
                if isinstance(last_ended, str):
                    last_ended = datetime.fromisoformat(last_ended)
                if last_ended.tzinfo is None:
                    last_ended = last_ended.replace(tzinfo=VANCOUVER_TZ)
                return datetime.now(VANCOUVER_TZ) - last_ended
            return None
        except Exception as e:
            _log.error("Get time since last session failed", error=str(e))
            return None

    def get_stats(self) -> Dict[str, Any]:
        try:
            session_row = self._conn.execute_one("SELECT COUNT(*) FROM sessions")
            message_row = self._conn.execute_one("SELECT COUNT(*) FROM messages")
            return {
                "total_sessions": session_row[0] if session_row else 0,
                "total_messages": message_row[0] if message_row else 0,
                "expired_pending_cleanup": 0,
                "expiry_days": MESSAGE_EXPIRY_DAYS,
            }
        except Exception as e:
            _log.error("Get stats failed", error=str(e))
            return {}

    def get_interaction_stats(self) -> Dict[str, Any]:
        try:
            # PERF-025: Combine into single query with CTEs
            result = self._conn.execute_dict(
                """WITH
                    by_model AS (
                        SELECT effective_model,
                               COUNT(*) as call_count,
                               AVG(latency_ms) as avg_latency_ms,
                               SUM(tokens_in) as total_tokens_in,
                               SUM(tokens_out) as total_tokens_out
                        FROM interaction_logs
                        GROUP BY effective_model
                    ),
                    by_tier AS (
                        SELECT tier,
                               COUNT(*) as call_count,
                               AVG(latency_ms) as avg_latency_ms,
                               SUM(tokens_in) as total_tokens_in,
                               SUM(tokens_out) as total_tokens_out
                        FROM interaction_logs
                        GROUP BY tier
                    ),
                    by_router AS (
                        SELECT router_reason, COUNT(*) as count
                        FROM interaction_logs
                        GROUP BY router_reason
                        ORDER BY count DESC LIMIT 10
                    ),
                    last_24h AS (
                        SELECT COUNT(*) as total_calls,
                               AVG(latency_ms) as avg_latency_ms,
                               SUM(tokens_in) as total_tokens_in,
                               SUM(tokens_out) as total_tokens_out
                        FROM interaction_logs
                        WHERE ts >= NOW() - INTERVAL '24 hours'
                    )
                SELECT
                    json_agg(DISTINCT jsonb_build_object(
                        'effective_model', by_model.effective_model,
                        'call_count', by_model.call_count,
                        'avg_latency_ms', by_model.avg_latency_ms,
                        'total_tokens_in', by_model.total_tokens_in,
                        'total_tokens_out', by_model.total_tokens_out
                    )) FILTER (WHERE by_model.effective_model IS NOT NULL) as models,
                    json_agg(DISTINCT jsonb_build_object(
                        'tier', by_tier.tier,
                        'call_count', by_tier.call_count,
                        'avg_latency_ms', by_tier.avg_latency_ms,
                        'total_tokens_in', by_tier.total_tokens_in,
                        'total_tokens_out', by_tier.total_tokens_out
                    )) FILTER (WHERE by_tier.tier IS NOT NULL) as tiers,
                    json_agg(DISTINCT jsonb_build_object(
                        'router_reason', by_router.router_reason,
                        'count', by_router.count
                    )) FILTER (WHERE by_router.router_reason IS NOT NULL) as reasons,
                    MAX(last_24h.total_calls) as last_24h_calls,
                    MAX(last_24h.avg_latency_ms) as last_24h_latency,
                    MAX(last_24h.total_tokens_in) as last_24h_tokens_in,
                    MAX(last_24h.total_tokens_out) as last_24h_tokens_out
                FROM by_model
                CROSS JOIN by_tier
                CROSS JOIN by_router
                CROSS JOIN last_24h
                """
            )

            if result:
                row = result[0]
                return {
                    "by_model": row.get("models") or [],
                    "by_tier": row.get("tiers") or [],
                    "by_router_reason": row.get("reasons") or [],
                    "last_24h": {
                        "total_calls": row.get("last_24h_calls") or 0,
                        "avg_latency_ms": row.get("last_24h_latency") or 0,
                        "total_tokens_in": row.get("last_24h_tokens_in") or 0,
                        "total_tokens_out": row.get("last_24h_tokens_out") or 0,
                    },
                }
            return {}
        except Exception as e:
            _log.error("Get interaction stats failed", error=str(e))
            return {}

    def get_expired_sessions(self, limit: int = 10) -> List[str]:
        rows = self._conn.execute(
            """SELECT session_id FROM sessions
               WHERE ended_at < NOW() - %s * INTERVAL '1 day' AND summary IS NULL
               LIMIT %s""",
            (MESSAGE_EXPIRY_DAYS, limit),
        )
        return [row[0] for row in rows]

    def get_session_messages_for_archive(self, session_id: str) -> List[Dict]:
        return self._conn.execute_dict(
            """SELECT id, turn_id, role, content, timestamp, emotional_context
               FROM messages WHERE session_id = %s ORDER BY turn_id ASC""",
            (session_id,),
        )

    def archive_session(self, session_id: str, messages: List[Dict], summary: str):
        with self._conn.get_connection() as conn:
            with conn.cursor() as cur:
                # PERF-025: Use execute_batch for batch insert
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
                execute_batch(
                    cur,
                    """INSERT INTO archived_messages
                           (session_id, turn_id, role, content, timestamp, emotional_context)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    message_data,
                )
                cur.execute(
                    "UPDATE sessions SET summary = %s WHERE session_id = %s",
                    (summary, session_id),
                )
