import sqlite3
import threading
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
from contextlib import contextmanager
from backend.core.logging import get_logger
from backend.config import SQLITE_MEMORY_PATH, MESSAGE_ARCHIVE_AFTER_DAYS, MESSAGE_SUMMARY_MODEL
from backend.core.utils.timezone import VANCOUVER_TZ, now_vancouver
from backend.core.utils.text_utils import sanitize_memory_text

# MESSAGE_ARCHIVE_AFTER_DAYS는 config.py에서 가져옴
MESSAGE_EXPIRY_DAYS = MESSAGE_ARCHIVE_AFTER_DAYS

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

            # messages 테이블 생성 (메시지 직접 저장용)
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

            # archived_messages 테이블 - 축약된 원본 메시지 백업용
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

            conn.commit()
            _log.debug("Database initialized", db_path=str(self.db_path))

    def save_message_immediate(
        self,
        session_id: str,
        role: str,
        content: str,
        timestamp: str,
        emotional_context: str = "neutral"
    ) -> bool:
        """매 턴 즉시 저장 - 중복 방지 포함"""
        try:
            # 텍스트 정제 (이모지, 특수문자 제거)
            content = sanitize_memory_text(content)

            with self._get_connection() as conn:
                # 현재 최대 turn_id 조회
                cursor = conn.execute(
                    'SELECT MAX(turn_id) FROM messages WHERE session_id = ?',
                    (session_id,)
                )
                row = cursor.fetchone()
                turn_id = (row[0] or -1) + 1

                conn.execute("""
                    INSERT OR IGNORE INTO messages
                    (session_id, turn_id, role, content, timestamp, emotional_context)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (session_id, turn_id, role, content, timestamp, emotional_context))

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
        messages: List[Dict] = None
    ) -> bool:
        """세션 저장 - messages는 messages 테이블에 직접 저장"""
        expires_at = datetime.now(VANCOUVER_TZ) + timedelta(days=MESSAGE_EXPIRY_DAYS)

        try:
            with self._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")

                try:
                    # messages 테이블에 직접 저장
                    if messages:
                        # 현재 최대 turn_id 조회
                        cursor = conn.execute(
                            'SELECT MAX(turn_id) FROM messages WHERE session_id = ?',
                            (session_id,)
                        )
                        row = cursor.fetchone()
                        base_turn_id = (row[0] or -1) + 1

                        for i, msg in enumerate(messages):
                            conn.execute("""
                                INSERT OR IGNORE INTO messages (session_id, turn_id, role, content, timestamp, emotional_context)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                session_id,
                                base_turn_id + i,
                                msg.get('role', 'unknown'),
                                msg.get('content', ''),
                                msg.get('timestamp', datetime.now(VANCOUVER_TZ).isoformat()),
                                msg.get('emotional_context', 'neutral')
                            ))

                    # sessions 테이블 업데이트 (summary=NULL, messages_json=NULL)
                    conn.execute("""
                        INSERT OR REPLACE INTO sessions
                        (session_id, summary, key_topics, emotional_tone,
                         turn_count, started_at, ended_at, expires_at, messages_json)
                        VALUES (?, NULL, ?, ?, ?, ?, ?, ?, NULL)
                    """, (
                        session_id,
                        json.dumps(key_topics, ensure_ascii=False),
                        emotional_tone,
                        turn_count,
                        started_at.isoformat(),
                        ended_at.isoformat(),
                        expires_at.isoformat(),
                    ))

                    conn.commit()
                    _log.info("MEM session_save", session_id=session_id[:8], turns=turn_count, msgs=len(messages) if messages else 0)
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
        """messages 테이블에서 직접 최근 대화 조회 (날짜별 그룹핑)"""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row

                # messages 테이블에서 직접 조회
                cursor = conn.execute("""
                    SELECT role, content, timestamp, emotional_context
                    FROM messages
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit * 20,))  # 충분히 많이 가져옴

                rows = cursor.fetchall()
                if not rows:
                    return "최근 대화 기록이 없습니다."

                parts = []
                char_count = 0

                # 날짜별 대화량 집계
                from collections import Counter
                date_counts = Counter()
                all_messages = []

                for row in rows:
                    ts = row['timestamp'][:10] if row['timestamp'] else ''
                    if ts:
                        date_counts[ts] += 1
                    all_messages.append({
                        'role': row['role'],
                        'content': row['content'],
                        'timestamp': row['timestamp'],
                        'emotional_context': row['emotional_context']
                    })

                # 날짜별 대화량 표시
                if date_counts:
                    parts.append("날짜별 대화량:")
                    for d, cnt in sorted(date_counts.items(), reverse=True)[:10]:
                        parts.append(f"  {d}: {cnt}개")
                        char_count += 20

                # 최근 메시지 샘플 (시간순 정렬)
                recent_msgs = sorted(all_messages, key=lambda m: m.get('timestamp', ''), reverse=True)[:20]
                if recent_msgs:
                    parts.append("\n최근 대화:")
                    for msg in recent_msgs:
                        ts = msg.get('timestamp', '')[:16] if msg.get('timestamp') else ''
                        role = msg.get('role', '?')
                        content_preview = msg.get('content', '')[:80].replace('\n', ' ')
                        msg_line = f"  [{ts}] {role}: {content_preview}..."
                        if char_count + len(msg_line) > max_tokens * 2:
                            parts.append("  ...(더 많은 기록 있음)")
                            break
                        parts.append(msg_line)
                        char_count += len(msg_line)

                # 과거 대화 샘플
                if char_count < max_tokens * 2:
                    import random
                    cutoff_date = (datetime.now(VANCOUVER_TZ) - timedelta(days=2)).strftime('%Y-%m-%d')
                    older_msgs = [m for m in all_messages if m.get('timestamp', '')[:10] < cutoff_date]
                    if older_msgs:
                        samples = random.sample(older_msgs, min(5, len(older_msgs)))
                        parts.append("\n과거 대화 샘플:")
                        for msg in samples:
                            date_str = msg.get('timestamp', '')[:10] if msg.get('timestamp') else '?'
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
        """messages 테이블에서 직접 날짜 범위로 조회"""
        if not to_date:
            to_date = from_date

        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row

                # messages 테이블에서 날짜 범위로 직접 조회
                cursor = conn.execute("""
                    SELECT role, content, timestamp, emotional_context
                    FROM messages
                    WHERE timestamp >= ? AND timestamp < date(?, '+1 day')
                    ORDER BY timestamp ASC
                    LIMIT ?
                """, (from_date, to_date, limit * 2))

                rows = cursor.fetchall()
                if not rows:
                    return f"{from_date} ~ {to_date} 기간에 대화 기록이 없습니다."

                messages = []
                char_count = 0

                for row in rows:
                    try:
                        ts = row['timestamp'][:16] if row['timestamp'] else ''
                        date_str = ts[5:10] if len(ts) >= 10 else "?"
                        time_str = ts[11:16] if len(ts) >= 16 else "?"
                    except (TypeError, IndexError):
                        date_str = "?"
                        time_str = "?"

                    role = row['role'] or '?'
                    content = (row['content'] or '')[:200].replace('\n', ' ')

                    msg_line = f"[{date_str} {time_str}] {role}: {content}..."

                    if char_count + len(msg_line) > max_tokens * 2:
                        messages.append("...(더 많은 기록 있음)")
                        break

                    messages.append(msg_line)
                    char_count += len(msg_line)

                _log.debug("MEM qry_temporal", from_d=from_date, to_d=to_date, res=len(rows))

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

    async def summarize_expired(self, llm_client=None) -> Dict[str, int]:
        """
        MESSAGE_ARCHIVE_AFTER_DAYS 지난 세션의 메시지를 축약 처리:
        1. 만료된 세션의 메시지 조회
        2. LLM으로 세션 단위 요약 생성
        3. 원본 메시지를 archived_messages로 이동
        4. sessions.summary에 요약 저장
        5. messages 테이블에서 원본 삭제

        Returns: {"sessions_processed": N, "messages_archived": M}
        """
        result = {"sessions_processed": 0, "messages_archived": 0}

        try:
            with self._get_connection() as conn:
                # 만료된 세션 조회 (summary가 NULL인 것만)
                cursor = conn.execute("""
                    SELECT session_id FROM sessions
                    WHERE expires_at < datetime('now')
                    AND summary IS NULL
                    LIMIT 10
                """)
                expired_sessions = [row[0] for row in cursor.fetchall()]

                if not expired_sessions:
                    _log.debug("No expired sessions to summarize")
                    return result

                _log.info("Summarizing expired sessions", count=len(expired_sessions))

                for session_id in expired_sessions:
                    try:
                        # 해당 세션의 메시지 조회
                        conn.row_factory = sqlite3.Row
                        cursor = conn.execute("""
                            SELECT id, turn_id, role, content, timestamp, emotional_context
                            FROM messages
                            WHERE session_id = ?
                            ORDER BY turn_id ASC
                        """, (session_id,))
                        messages = cursor.fetchall()

                        if not messages:
                            continue

                        # LLM으로 요약 생성
                        summary = await self._generate_session_summary(messages, llm_client)

                        if not summary:
                            _log.warning("Failed to generate summary", session_id=session_id[:8])
                            continue

                        # 트랜잭션으로 원자적 처리
                        conn.execute("BEGIN IMMEDIATE")
                        try:
                            # 1. archived_messages로 원본 이동
                            for msg in messages:
                                conn.execute("""
                                    INSERT INTO archived_messages
                                    (session_id, turn_id, role, content, timestamp, emotional_context)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                """, (
                                    session_id,
                                    msg['turn_id'],
                                    msg['role'],
                                    msg['content'],
                                    msg['timestamp'],
                                    msg['emotional_context']
                                ))

                            # 2. sessions.summary 업데이트
                            conn.execute("""
                                UPDATE sessions SET summary = ? WHERE session_id = ?
                            """, (summary, session_id))

                            # 3. messages 테이블에서 삭제
                            conn.execute("""
                                DELETE FROM messages WHERE session_id = ?
                            """, (session_id,))

                            conn.commit()

                            result["sessions_processed"] += 1
                            result["messages_archived"] += len(messages)

                            _log.info(
                                "Session summarized",
                                session_id=session_id[:8],
                                messages=len(messages),
                                summary_len=len(summary)
                            )

                        except Exception as e:
                            conn.rollback()
                            raise

                    except Exception as e:
                        _log.error("Session summarize failed", session_id=session_id[:8], error=str(e))
                        continue

        except Exception as e:
            _log.error("Summarize expired failed", error=str(e))

        return result

    async def _generate_session_summary(self, messages: List[Any], llm_client=None) -> Optional[str]:
        """세션 메시지들을 LLM으로 요약"""
        if not messages:
            return None

        # 메시지 포맷팅
        conversation_text = []
        for msg in messages[:50]:  # 최대 50개 메시지만
            role = msg['role'] if msg['role'] else 'unknown'
            content = (msg['content'] or '')[:500]  # 각 메시지 500자 제한
            conversation_text.append(f"{role}: {content}")

        full_conversation = "\n".join(conversation_text)

        prompt = f"""다음 대화를 간결하게 요약해주세요.

대화 내용:
{full_conversation[:5000]}

요약 규칙:
- 핵심 주제와 결론만 포함
- 2-3문장으로 요약
- 사용자가 요청한 것과 AI가 제공한 것 중심
- 중요한 정보(이름, 날짜, 결정사항)는 보존

요약:"""

        try:
            if llm_client:
                response = await llm_client.generate(prompt, max_tokens=300)
            else:
                # LLM 클라이언트가 없으면 기본 요약 생성
                from backend.llm import get_llm_client
                llm = get_llm_client("gemini", MESSAGE_SUMMARY_MODEL)
                response = await llm.generate(prompt, max_tokens=300)

            if response:
                return response.strip()
            return None

        except Exception as e:
            _log.warning("Summary generation failed", error=str(e))
            return None

    def cleanup_expired(self) -> int:

        _log.debug("cleanup_expired called but message deletion is disabled (use summarize_expired instead)")
        return 0

    def get_stats(self) -> Dict[str, Any]:
        """messages 테이블에서 직접 통계 조회"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM sessions")
                session_count = cursor.fetchone()[0]

                # messages 테이블에서 직접 카운트
                cursor = conn.execute("SELECT COUNT(*) FROM messages")
                message_count = cursor.fetchone()[0]

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
