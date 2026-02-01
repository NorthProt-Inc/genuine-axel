import asyncio
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from backend.core.utils.timezone import VANCOUVER_TZ, now_vancouver
if TYPE_CHECKING:
    from google.genai import Client as GenaiClient
from backend.core.logging import get_logger

_log = get_logger("memory.unified")

from backend.config import (
    MAX_CONTEXT_TOKENS,
    MEMORY_WORKING_BUDGET,
    MEMORY_LONG_TERM_BUDGET,
    MEMORY_SESSION_ARCHIVE_BUDGET,
    MEMORY_TIME_CONTEXT_BUDGET,
    CHROMADB_PATH,
)

from .current import WorkingMemory, TimestampedMessage
from .recent import SessionArchive
from .permanent import LongTermMemory, LegacyMemoryMigrator
from .memgpt import MemGPTManager, MemGPTConfig
from .graph_rag import GraphRAG, KnowledgeGraph

SESSION_SUMMARY_PROMPT = """
다음 대화를 분석하고 요약해주세요.

## 대화 내용:
{conversation}

## 응답 형식 (JSON):
{{
    "summary": "대화의 핵심 내용을 1-2문장으로 요약",
    "key_topics": ["토픽1", "토픽2", "토픽3"],
    "emotional_tone": "전반적인 감정 톤 (positive/neutral/negative/mixed)",
    "facts_discovered": ["발견된 사실들"],
    "insights_discovered": ["발견된 통찰들"]
}}
"""

class MemoryManager:

    MAX_CONTEXT_TOKENS = MAX_CONTEXT_TOKENS
    WORKING_BUDGET = MEMORY_WORKING_BUDGET
    LONG_TERM_BUDGET = MEMORY_LONG_TERM_BUDGET
    TIME_CONTEXT_BUDGET = MEMORY_TIME_CONTEXT_BUDGET
    SESSION_ARCHIVE_BUDGET = MEMORY_SESSION_ARCHIVE_BUDGET

    def __init__(
        self,
        model: Any = None,
        working_memory: WorkingMemory = None,
        session_archive: SessionArchive = None,
        long_term_memory: LongTermMemory = None,
    ):
        self.model = model
        self.working = working_memory or WorkingMemory()
        self.session_archive = session_archive or SessionArchive()
        self.long_term = long_term_memory or LongTermMemory()

        self._last_session_end: Optional[datetime] = None

        self.memgpt = MemGPTManager(
            long_term_memory=self.long_term,
            model=model,
            config=MemGPTConfig()
        )

        self.knowledge_graph = KnowledgeGraph()
        self.graph_rag = GraphRAG(model=model, graph=self.knowledge_graph)

        self._write_lock = threading.Lock()
        self._read_semaphore = threading.Semaphore(5)

    LOG_PATTERNS = [
        "[Tavily]", "[TTS Error]", "[Memory]", "[System]",
        "[Router]", "[LLM]", "[Error]", "[Warning]",
        "[Keywords]", "[Long-term Memory", "[Current]",
        "FutureWarning:", "DeprecationWarning:",
        "Permission denied", "Traceback",
    ]

    def add_message(self, role: str, content: str, emotional_context: str = "neutral"):

        if any(pattern in content for pattern in self.LOG_PATTERNS):
            _log.debug("Filtered log pattern from memory")
            return None

        with self._write_lock:
            msg = self.working.add(role, content, emotional_context)

            # 매 턴 SQL 저장 추가
            if msg and self.session_archive:
                try:
                    self.session_archive.save_message_immediate(
                        session_id=self.working.session_id,
                        role=msg.role,
                        content=msg.content,
                        timestamp=msg.timestamp.isoformat(),
                        emotional_context=msg.emotional_context
                    )
                except Exception as e:
                    _log.warning("Immediate message save failed", error=str(e))

            return msg

    def get_working_context(self) -> str:

        return self.working.get_context()

    def build_smart_context(
        self,
        current_query: str
    ) -> str:

        return self._build_smart_context_sync(current_query)

    def _build_smart_context_sync(self, current_query: str) -> str:

        context_parts = []

        time_context = self._build_time_context()
        if time_context:
            context_parts.append(f"## 시간 컨텍스트\n{time_context}")

        working_context = self.working.get_progressive_context()
        if working_context:
            context_parts.append(f"## 현재 대화 (최근 {self.working.get_turn_count()}턴, Progressive)\n{working_context}")

        if current_query:

            from .temporal import parse_temporal_query
            temporal_filter = parse_temporal_query(current_query)

            try:
                selected_memories, tokens_used = self.memgpt.context_budget_select(
                    current_query,
                    self.LONG_TERM_BUDGET,
                    None,
                    temporal_filter
                )
                if selected_memories:
                    memory_lines = []
                    for mem in selected_memories:
                        score_str = f"[{mem.score:.2f}]" if mem.score else ""
                        memory_lines.append(f"- {score_str} {mem.content[:200]}...")
                    context_parts.append(f"## 관련 장기 기억 ({len(selected_memories)}개, {tokens_used} tokens)\n" + "\n".join(memory_lines))
            except Exception as e:
                _log.warning("MemGPT selection failed (sync)", error=str(e))

            try:
                if temporal_filter:
                    filter_type = temporal_filter.get("type")
                    if filter_type == "exact":
                        from_date = temporal_filter.get("date")
                        session_context = self.session_archive.get_sessions_by_date(
                            from_date, None, 5, self.SESSION_ARCHIVE_BUDGET
                        )
                    elif filter_type == "range":
                        from_date = temporal_filter.get("from")
                        to_date = temporal_filter.get("to")
                        session_context = self.session_archive.get_sessions_by_date(
                            from_date, to_date, 10, self.SESSION_ARCHIVE_BUDGET
                        )
                    else:
                        session_context = self.session_archive.get_recent_summaries(10, self.SESSION_ARCHIVE_BUDGET)
                else:
                    session_context = self.session_archive.get_recent_summaries(10, self.SESSION_ARCHIVE_BUDGET)

                if session_context and "최근 대화 기록이 없습니다" not in session_context:
                    context_parts.append(f"## 최근 세션 기록\n{session_context}")
            except Exception as e:
                _log.debug("Session archive fetch failed (sync)", error=str(e))

            try:
                if self.graph_rag:
                    graph_result = self.graph_rag.query_sync(current_query)
                    if graph_result and graph_result.context:
                        context_parts.append(f"## 관계 기반 지식\n{graph_result.context}")
            except Exception as e:
                _log.debug("GraphRAG query skipped (sync)", error=str(e))

        context_text = "\n\n".join(context_parts)
        max_chars = self.MAX_CONTEXT_TOKENS * 4
        if max_chars > 0 and len(context_text) > max_chars:
            suffix = "\n... (truncated)"
            keep = max_chars - len(suffix)
            if keep > 0:
                context_text = context_text[:keep].rstrip() + suffix
            else:
                context_text = context_text[:max_chars]

        return context_text

    async def _build_smart_context_async(
        self,
        current_query: str
    ) -> str:

        import asyncio
        context_parts = []

        time_context = self._build_time_context()
        if time_context:
            context_parts.append(f"## 시간 컨텍스트\n{time_context}")

        working_context = self.working.get_progressive_context()
        if working_context:
            context_parts.append(f"## 현재 대화 (최근 {self.working.get_turn_count()}턴, Progressive)\n{working_context}")

        if current_query:

            from .temporal import parse_temporal_query
            temporal_filter = parse_temporal_query(current_query)

            if temporal_filter:
                _log.debug("Temporal filter detected", filter_type=temporal_filter.get("type"))

            async def get_memgpt_context():
                try:
                    return await asyncio.to_thread(
                        self.memgpt.context_budget_select,
                        current_query,
                        self.LONG_TERM_BUDGET,
                        None,
                        temporal_filter
                    )
                except Exception as e:
                    _log.warning("MemGPT selection failed", error=str(e))
                    return None, 0

            async def get_session_archive_context():
                try:

                    if temporal_filter:
                        filter_type = temporal_filter.get("type")
                        if filter_type == "exact":
                            from_date = temporal_filter.get("date")
                            return await asyncio.to_thread(
                                self.session_archive.get_sessions_by_date,
                                from_date,
                                None,
                                5,
                                self.SESSION_ARCHIVE_BUDGET
                            )
                        elif filter_type == "range":
                            from_date = temporal_filter.get("from")
                            to_date = temporal_filter.get("to")
                            return await asyncio.to_thread(
                                self.session_archive.get_sessions_by_date,
                                from_date,
                                to_date,
                                10,
                                self.SESSION_ARCHIVE_BUDGET
                            )

                    return await asyncio.to_thread(
                        self.session_archive.get_recent_summaries,
                        10,
                        self.SESSION_ARCHIVE_BUDGET
                    )
                except Exception as e:
                    _log.debug("Session archive fetch failed", error=str(e))
                    return ""

            async def get_graph_context():
                if not self.graph_rag:
                    return None
                try:
                    return await asyncio.to_thread(
                        self.graph_rag.query_sync,
                        current_query
                    )
                except Exception as e:
                    _log.debug("GraphRAG query skipped", error=str(e))
                    return None

            results = await asyncio.gather(
                get_memgpt_context(),
                get_session_archive_context(),
                get_graph_context(),
                return_exceptions=True
            )

            memgpt_result = results[0] if not isinstance(results[0], Exception) else None
            session_context = results[1] if not isinstance(results[1], Exception) else None
            graph_result = results[2] if not isinstance(results[2], Exception) else None

            for i, (name, res) in enumerate(zip(["longterm", "sessions", "graph"], results)):
                if isinstance(res, Exception):
                    _log.warning("Memory task failed", task=name, error=str(res)[:100])

            if memgpt_result:
                selected_memories, tokens_used = memgpt_result
                if selected_memories:
                    memory_lines = []
                    for mem in selected_memories:
                        score_str = f"[{mem.score:.2f}]" if mem.score else ""
                        memory_lines.append(f"- {score_str} {mem.content[:200]}...")

                    context_parts.append(f"## 관련 장기 기억 ({len(selected_memories)}개, {tokens_used} tokens)\n" + "\n".join(memory_lines))
                    _log.debug("MEM longterm_qry", selected=len(selected_memories), tokens=tokens_used)

            if session_context:
                if session_context and "최근 대화 기록이 없습니다" not in session_context:
                    context_parts.append(f"## 최근 세션 기록\n{session_context}")

            if graph_result:
                if graph_result.context:
                    context_parts.append(f"## 관계 기반 지식\n{graph_result.context}")
                    _log.debug("MEM graph_qry", entities=len(graph_result.entities), rels=len(graph_result.relations))

        context_text = "\n\n".join(context_parts)
        max_chars = self.MAX_CONTEXT_TOKENS * 4
        if max_chars > 0 and len(context_text) > max_chars:
            suffix = "\n... (truncated)"
            keep = max_chars - len(suffix)
            if keep > 0:
                context_text = context_text[:keep].rstrip() + suffix
            else:
                context_text = context_text[:max_chars]
            _log.debug("MEM context_truncated", chars=len(context_text), limit=max_chars)
        return context_text

    def _build_time_context(self) -> str:

        now = datetime.now(VANCOUVER_TZ)
        lines = []

        lines.append(f"현재 시각: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')}) PST")

        time_since = self.session_archive.get_time_since_last_session()
        if time_since:
            if time_since < timedelta(hours=1):
                elapsed_str = f"{int(time_since.total_seconds() / 60)}분 전"
            elif time_since < timedelta(days=1):
                elapsed_str = f"{int(time_since.total_seconds() / 3600)}시간 전"
            else:
                elapsed_str = f"{time_since.days}일 전"
            lines.append(f"마지막 대화: {elapsed_str}")

        elapsed_context = self.working.get_time_elapsed_context()
        if elapsed_context:
            lines.append(elapsed_context)

        return "\n".join(lines)

    async def end_session(
        self,
        allow_llm_summary: bool = True,
        summary_timeout_seconds: Optional[float] = None,
        allow_fallback_summary: bool = True
    ) -> Dict[str, Any]:

        if not self.working:
            return {"status": "no_session"}

        session_id = self.working.session_id
        messages = self.working.get_messages()

        if not messages:
            return {"status": "empty_session"}

        summary_result = None
        if allow_llm_summary:
            try:
                if summary_timeout_seconds:
                    summary_result = await asyncio.wait_for(
                        self._summarize_session(messages),
                        timeout=summary_timeout_seconds
                    )
                else:
                    summary_result = await self._summarize_session(messages)
            except asyncio.TimeoutError:
                _log.warning("Session summarization timed out", timeout=summary_timeout_seconds)
            except Exception as e:
                _log.warning("Session summarization failed", error=str(e))

        if not summary_result and allow_fallback_summary:
            summary_result = self._build_fallback_summary(messages)

        if summary_result:

            self.session_archive.save_session(
                session_id=session_id,
                summary=summary_result.get("summary", "요약 없음"),
                key_topics=summary_result.get("key_topics", []),
                emotional_tone=summary_result.get("emotional_tone", "neutral"),
                turn_count=len(messages) // 2,
                started_at=messages[0].timestamp if messages else datetime.now(),
                ended_at=messages[-1].timestamp if messages else datetime.now(),
                messages=[m.to_dict() for m in messages]
            )

            for fact in summary_result.get("facts_discovered", []):
                self.long_term.add(
                    content=fact,
                    memory_type="fact",
                    importance=0.7,
                    source_session=session_id
                )

            for insight in summary_result.get("insights_discovered", []):
                self.long_term.add(
                    content=insight,
                    memory_type="insight",
                    importance=0.6,
                    source_session=session_id
                )

        self.working.reset_session()
        self._last_session_end = datetime.now()

        return {
            "status": "session_ended",
            "session_id": session_id,
            "messages_processed": len(messages),
            "summary": summary_result.get("summary") if summary_result else None,
        }

    async def _summarize_session(self, messages: List[TimestampedMessage]) -> Optional[Dict]:

        if not self.model or not messages:
            return None

        conversation = "\n".join([
            f"[{m.get_relative_time()} | {m.timestamp.strftime('%H:%M')}] {m.role}: {m.content}"
            for m in messages
        ])

        prompt = SESSION_SUMMARY_PROMPT.format(conversation=conversation)

        try:
            import asyncio

            response = await asyncio.to_thread(
                self.model.generate_content_sync,
                contents=prompt,
                stream=False
            )
            text = response.text

            import json
            json_start = text.find('{')
            json_end = text.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                return json.loads(text[json_start:json_end])

        except Exception as e:
            _log.warning("Summarization error", error=str(e))

        return None

    def _build_fallback_summary(self, messages: List[TimestampedMessage]) -> Dict[str, Any]:

        def _last_for(role_names: set) -> str:
            for msg in reversed(messages):
                if msg.role.lower() in role_names:
                    return msg.content
            return ""

        last_user = _last_for({"user", "mark"})
        last_assistant = _last_for({"assistant", "axel", "ai"})

        summary_parts = []
        if last_user:
            summary_parts.append(f"User: {last_user[:200]}")
        if last_assistant:
            summary_parts.append(f"Assistant: {last_assistant[:200]}")

        summary_text = "요약 생성 실패. 최근 대화 요약: " + " / ".join(summary_parts) if summary_parts else "요약 생성 실패."

        return {
            "summary": summary_text,
            "key_topics": [],
            "emotional_tone": "neutral",
            "facts_discovered": [],
            "insights_discovered": [],
        }

    def query(self, query: str, include_all: bool = False) -> Dict[str, Any]:

        results = {
            "working": [],
            "sessions": [],
            "long_term": [],
        }

        for msg in self.working.messages:
            if query.lower() in msg.content.lower():
                results["working"].append({
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                    "role": msg.role
                })

        if include_all:
            results["sessions"] = self.session_archive.search_by_topic(query, limit=3)

        results["long_term"] = self.long_term.query(query, n_results=5)

        return results

    def migrate_legacy_data(self, old_db_path: str = None, dry_run: bool = True) -> Dict:
        old_db_path = old_db_path or str(CHROMADB_PATH)
        """Migrate data from old ChromaDB."""
        migrator = LegacyMemoryMigrator(
            old_db_path=old_db_path,
            new_long_term=self.long_term
        )
        return migrator.migrate(dry_run=dry_run)

    def get_stats(self) -> Dict[str, Any]:

        return {
            "working": {
                "messages": len(self.working),
                "turns": self.working.get_turn_count(),
                "max_turns": self.working.MAX_TURNS,
                "session_id": self.working.session_id,
            },
            "sessions": self.session_archive.get_stats(),
            "long_term": self.long_term.get_stats(),
        }
