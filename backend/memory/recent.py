import sqlite3
import threading
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
from contextlib import contextmanager
from backend.core.logging import get_logger
from backend.config import SQLITE_MEMORY_PATH
from backend.core.utils.timezone import VANCOUVER_TZ, now_vancouver

MESSAGE_EXPIRY_DAYS = 7

_log = get_logger("memory.recent")

class SessionArchive:

    def __init__(self, db_path: str = None):
        self.db_path = Path(db_path) if db_path else SQLITE_MEMORY_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _get_connection(self):

        with self._lock:
            if self._connection is None:
                self._connection = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    timeout=10.0
                )

                self._connection.execute("PRAGMA journal_mode=WAL")
                self._connection.execute("PRAGMA busy_timeout=5000")
                self._connection.execute("PRAGMA synchronous=NORMAL")

            try:
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise

    def _init_db(self):

        with self._get_connection() as conn:
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

            conn.commit()
            _log.debug("Database initialized", db_path=str(self.db_path))

    def save_session(
        self,
        session_id: str,
        summary: str,
        key_topics: List[str],
        emotional_tone: str,
        turn_count: int,
        started_at: datetime,
        ended_at: datetime,
        messages: List[Dict] = None
    ) -> bool:

        expires_at = datetime.now(VANCOUVER_TZ) + timedelta(days=MESSAGE_EXPIRY_DAYS)

        try:
            with self._get_connection() as conn:

                conn.execute("BEGIN IMMEDIATE")

                try:

                    messages_json = None
                    if messages:

                        cursor = conn.execute(
                            'SELECT messages_json FROM sessions WHERE session_id = ?',
                            (session_id,)
                        )
                        row = cursor.fetchone()
                        existing = []
                        if row and row[0]:
                            try:
                                existing = json.loads(row[0])
                            except json.JSONDecodeError:
                                pass

                        base_turn_id = len(existing)
                        for i, msg in enumerate(messages):
                            existing.append({
                                'turn_id': base_turn_id + i,
                                'role': msg.get('role', 'unknown'),
                                'content': msg.get('content', ''),
                                'timestamp': msg.get('timestamp', datetime.now(VANCOUVER_TZ).isoformat()),
                                'emotional_context': msg.get('emotional_context', 'neutral')
                            })
                        messages_json = json.dumps(existing, ensure_ascii=False)

                    conn.execute("""
                        INSERT OR REPLACE INTO sessions
                        (session_id, summary, key_topics, emotional_tone,
                         turn_count, started_at, ended_at, expires_at, messages_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        session_id,
                        summary,
                        json.dumps(key_topics, ensure_ascii=False),
                        emotional_tone,
                        turn_count,
                        started_at.isoformat(),
                        ended_at.isoformat(),
                        expires_at.isoformat(),
                        messages_json
                    ))

                    conn.commit()
                    _log.info("MEM session_save", session_id=session_id[:8], turns=turn_count)
                    return True

                except Exception as e:
                    conn.rollback()
                    raise

        except Exception as e:
            _log.error("Save session failed", error=str(e), session_id=session_id)
            return False

    def log_interaction(
        self,
        routing_decision: dict,
        conversation_id: str = None,
        turn_id: int = None,
        latency_ms: int = None,
        ttft_ms: int = None,
        tokens_in: int = None,
        tokens_out: int = None,
        tool_calls: list = None,
        refusal_detected: bool = False,
        response_text: str = None
    ) -> bool:

        try:

            style_metrics = {}
            if response_text:
                style_metrics = self._calculate_style_metrics(response_text)

            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO interaction_logs (
                        conversation_id, turn_id,
                        effective_model, tier, router_reason,
                        routing_features_json, manual_override,
                        latency_ms, ttft_ms, tokens_in, tokens_out,
                        tool_calls_json, refusal_detected,
                        response_chars, hedge_ratio, avg_sentence_len
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    conversation_id,
                    turn_id,
                    routing_decision.get("effective_model", "unknown"),
                    routing_decision.get("tier", "unknown"),
                    routing_decision.get("router_reason", "unknown"),
                    json.dumps(routing_decision.get("routing_features", {}), ensure_ascii=False),
                    1 if routing_decision.get("manual_override", False) else 0,
                    latency_ms,
                    ttft_ms,
                    tokens_in,
                    tokens_out,
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    1 if refusal_detected else 0,
                    len(response_text) if response_text else None,
                    style_metrics.get("hedge_ratio"),
                    style_metrics.get("avg_sentence_len"),
                ))
                conn.commit()

                _log.debug(
                    "Interaction logged",
                    tier=routing_decision.get("tier"),
                    router_reason=routing_decision.get("router_reason"),
                    latency_ms=latency_ms
                )
                return True

        except Exception as e:
            _log.error("Log interaction failed", error=str(e))
            return False

    def _calculate_style_metrics(self, response: str) -> dict:

        if not response or len(response) < 10:
            return {"hedge_ratio": 0.0, "avg_sentence_len": 0.0}

        hedge_phrases = [
            "아마도", "것 같아", "것 같습니다", "인 것 같아",
            "I think", "I'm not sure", "maybe", "perhaps",
            "probably", "확실하지 않지만", "추측이지만",
        ]

        import re
        sentences = re.split(r'[.!?。]', response)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return {"hedge_ratio": 0.0, "avg_sentence_len": 0.0}

        hedge_count = 0
        for sentence in sentences:
            sentence_lower = sentence.lower()
            if any(hedge in sentence_lower for hedge in hedge_phrases):
                hedge_count += 1

        hedge_ratio = hedge_count / len(sentences)
        avg_sentence_len = len(response) / len(sentences)

        return {
            "hedge_ratio": round(hedge_ratio, 3),
            "avg_sentence_len": round(avg_sentence_len, 1),
        }

    def get_recent_interaction_logs(self, limit: int = 20) -> List[Dict]:

        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM interaction_logs
                    ORDER BY ts DESC
                    LIMIT ?
                """, (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            _log.error("Get interaction logs failed", error=str(e))
            return []

    def get_recent_summaries(self, limit: int = 5, max_tokens: int = 2000) -> str:

        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row

                cursor = conn.execute("""
                    SELECT session_id, summary, key_topics, emotional_tone,
                           turn_count, started_at, ended_at, messages_json
                    FROM sessions
                    ORDER BY ended_at DESC
                    LIMIT ?
                """, (limit,))

                rows = cursor.fetchall()
                parts = []
                char_count = 0
                all_messages = []

                for row in rows:
                    ended = datetime.fromisoformat(row['ended_at'])
                    elapsed = datetime.now(VANCOUVER_TZ) - ended.replace(tzinfo=VANCOUVER_TZ)

                    if elapsed < timedelta(hours=1):
                        time_str = f"{int(elapsed.total_seconds() / 60)}분 전"
                    elif elapsed < timedelta(days=1):
                        time_str = f"{int(elapsed.total_seconds() / 3600)}시간 전"
                    else:
                        time_str = f"{elapsed.days}일 전"

                    topics = json.loads(row['key_topics']) if row['key_topics'] else []
                    topics_str = ", ".join(topics[:3]) if topics else "기록 없음"

                    summary_line = f"[{time_str}] {row['summary'][:150]} (주제: {topics_str})"
                    parts.append(summary_line)
                    char_count += len(summary_line)

                    if row['messages_json']:
                        try:
                            msgs = json.loads(row['messages_json'])
                            all_messages.extend(msgs)
                        except json.JSONDecodeError:
                            pass

                if all_messages:
                    from collections import Counter
                    date_counts = Counter()
                    for msg in all_messages:
                        ts = msg.get('timestamp', '')[:10]
                        if ts:
                            date_counts[ts] += 1

                    if date_counts:
                        parts.append("\n 날짜별 대화량:")
                        for d, cnt in sorted(date_counts.items(), reverse=True)[:10]:
                            parts.append(f"  {d}: {cnt}개")
                            char_count += 20

                if char_count < max_tokens * 2 and all_messages:
                    import random
                    older_msgs = [m for m in all_messages if m.get('timestamp', '')[:10] < (datetime.now(VANCOUVER_TZ) - timedelta(days=2)).strftime('%Y-%m-%d')]
                    if older_msgs:
                        samples = random.sample(older_msgs, min(5, len(older_msgs)))
                        parts.append("\n 과거 대화 샘플:")
                        for msg in samples:
                            date_str = msg.get('timestamp', '')[:10]
                            content_preview = msg.get('content', '')[:80].replace('\n', ' ')
                            parts.append(f"  [{date_str}] {msg.get('role', '?')}: {content_preview}...")

                return "\n".join(parts) if parts else "최근 대화 기록이 없습니다."

        except Exception as e:
            _log.error("Get summaries failed", error=str(e))
            return "기억 조회 중 오류 발생"

    def get_session_detail(self, session_id: str) -> Optional[Dict[str, Any]]:

        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row

                cursor = conn.execute("""
                    SELECT * FROM sessions WHERE session_id = ?
                """, (session_id,))
                session = cursor.fetchone()

                if not session:
                    return None

                session_dict = dict(session)

                messages = []
                if session_dict.get('messages_json'):
                    try:
                        messages = json.loads(session_dict['messages_json'])
                    except json.JSONDecodeError:
                        pass

                return {
                    "session": session_dict,
                    "messages": messages
                }

        except Exception as e:
            _log.error("Get session detail failed", error=str(e), session_id=session_id)
            return None

    def search_by_topic(self, topic: str, limit: int = 5) -> List[Dict]:

        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM sessions
                    WHERE key_topics LIKE ?
                    ORDER BY ended_at DESC
                    LIMIT ?
                """, (f"%{topic}%", limit))

                return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            _log.error("Topic search failed", error=str(e), topic=topic)
            return []

    def get_sessions_by_date(
        self,
        from_date: str,
        to_date: str = None,
        limit: int = 10,
        max_tokens: int = 3000
    ) -> str:

        if not to_date:
            to_date = from_date

        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row

                cursor = conn.execute("""
                    SELECT messages_json FROM sessions
                    WHERE messages_json IS NOT NULL
                """)

                all_messages = []
                for row in cursor.fetchall():
                    try:
                        msgs = json.loads(row['messages_json'])
                        for msg in msgs:
                            ts = msg.get('timestamp', '')[:10]
                            if from_date <= ts <= to_date:
                                all_messages.append(msg)
                    except json.JSONDecodeError:
                        pass

                all_messages.sort(key=lambda m: m.get('timestamp', ''))

                if not all_messages:
                    return f"{from_date} ~ {to_date} 기간에 대화 기록이 없습니다."

                messages = []
                char_count = 0

                for msg in all_messages[:limit * 2]:
                    try:
                        ts = msg.get('timestamp', '')[:16]
                        date_str = ts[5:10]
                        time_str = ts[11:16]
                    except (TypeError, IndexError):
                        date_str = "?"
                        time_str = "?"

                    role = msg.get('role', '?')
                    content = msg.get('content', '')[:200].replace('\n', ' ')

                    msg_line = f"[{date_str} {time_str}] {role}: {content}..."

                    if char_count + len(msg_line) > max_tokens * 2:
                        messages.append("...(더 많은 기록 있음)")
                        break

                    messages.append(msg_line)
                    char_count += len(msg_line)

                _log.debug("MEM qry_temporal", from_d=from_date, to_d=to_date, res=len(all_messages))

                return "\n".join(messages)

        except Exception as e:
            _log.error("Temporal message search failed", error=str(e))
            return "기억 조회 중 오류 발생"

    def get_time_since_last_session(self) -> Optional[timedelta]:

        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT ended_at FROM sessions
                    ORDER BY ended_at DESC LIMIT 1
                """)
                row = cursor.fetchone()

                if row:
                    last_ended = datetime.fromisoformat(row[0])
                    return datetime.now(VANCOUVER_TZ) - last_ended.replace(tzinfo=VANCOUVER_TZ)
                return None

        except Exception as e:
            _log.error("Get time since last session failed", error=str(e))
            return None

    def cleanup_expired(self) -> int:

        _log.debug("cleanup_expired called but message deletion is disabled (permanent archive)")
        return 0

    def get_stats(self) -> Dict[str, Any]:

        try:
            with self._get_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM sessions")
                session_count = cursor.fetchone()[0]

                cursor = conn.execute("SELECT messages_json FROM sessions WHERE messages_json IS NOT NULL")
                message_count = 0
                for row in cursor.fetchall():
                    try:
                        msgs = json.loads(row[0])
                        message_count += len(msgs)
                    except json.JSONDecodeError:
                        pass

                cursor = conn.execute("""
                    SELECT COUNT(*) FROM sessions
                    WHERE expires_at < datetime('now')
                """)
                expired_count = cursor.fetchone()[0]

                return {
                    "total_sessions": session_count,
                    "total_messages": message_count,
                    "expired_pending_cleanup": expired_count,
                    "expiry_days": MESSAGE_EXPIRY_DAYS,
                }

        except Exception as e:
            _log.error("Get stats failed", error=str(e))
            return {}

    def close(self, silent: bool = False):

        if self._connection:
            self._connection.close()
            self._connection = None
            if not silent:
                try:
                    _log.info("Database connection closed")
                except Exception:
                    pass

    def __del__(self):

        self.close(silent=True)
