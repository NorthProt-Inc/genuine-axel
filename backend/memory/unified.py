import asyncio
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from backend.core.utils.timezone import VANCOUVER_TZ
if TYPE_CHECKING:
    pass
from backend.core.logging import get_logger
from backend.core.utils.text import truncate_text

_log = get_logger("memory.unified")

from backend.config import (
    MAX_CONTEXT_TOKENS,
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
    LONG_TERM_BUDGET = MEMORY_LONG_TERM_BUDGET
    SESSION_ARCHIVE_BUDGET = MEMORY_SESSION_ARCHIVE_BUDGET
    TIME_CONTEXT_BUDGET = MEMORY_TIME_CONTEXT_BUDGET

    def __init__(
        self,
        client: Any = None,
        model_name: str | None = None,
        working_memory: WorkingMemory = None,
        session_archive: SessionArchive = None,
        long_term_memory: LongTermMemory = None,
        # Backward compat: accept model= kwarg and ignore it
        model: Any = None,
    ):
        from google import genai

        if client is None and model is None:
            from backend.core.utils.gemini_client import get_gemini_client
            client = get_gemini_client()
        elif client is None and isinstance(model, genai.Client):
            # Accept genai.Client passed as model= for backward compat
            client = model
        elif client is None and model is not None:
            # Legacy GenerativeModelWrapper — extract .client
            client = getattr(model, "client", None)

        self.client = client
        self.model_name = model_name
        if not self.model_name:
            from backend.core.utils.gemini_client import get_model_name
            self.model_name = get_model_name()

        self.working = working_memory or WorkingMemory()
        self.session_archive = session_archive or SessionArchive()
        self.long_term = long_term_memory or LongTermMemory()

        self._last_session_end: Optional[datetime] = None

        self.memgpt = MemGPTManager(
            long_term_memory=self.long_term,
            client=client,
            model_name=self.model_name,
            config=MemGPTConfig()
        )

        self.knowledge_graph = KnowledgeGraph()
        self.graph_rag = GraphRAG(client=client, model_name=self.model_name, graph=self.knowledge_graph)

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
        """Add a message to working memory with immediate SQL persistence.

        Args:
            role: Message role (user/assistant)
            content: Message content
            emotional_context: Emotional tone

        Returns:
            TimestampedMessage or None if filtered
        """
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
        """Get current working memory context as formatted string."""
        return self.working.get_context()

    def build_smart_context(
        self,
        current_query: str
    ) -> str:
        """Build intelligent context from all memory sources.

        Args:
            current_query: Current user query for relevance scoring

        Returns:
            Formatted context string with time, working, long-term, and graph data
        """
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
        context_text = truncate_text(context_text, self.MAX_CONTEXT_TOKENS * 4)

        return context_text

    def _build_time_context(self) -> str:
        """Build time-aware context with current time and session info."""
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
        """End current session with summarization and archival.

        Args:
            allow_llm_summary: Enable LLM-based summarization
            summary_timeout_seconds: Timeout for summary generation
            allow_fallback_summary: Use simple summary if LLM fails

        Returns:
            Dict with session status and summary
        """
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
        """Generate LLM summary of session messages.

        Args:
            messages: List of session messages

        Returns:
            Summary dict with topics, tone, facts, insights or None
        """
        if not self.client or not messages:
            return None

        conversation = "\n".join([
            f"[{m.get_relative_time()} | {m.timestamp.strftime('%H:%M')}] {m.role}: {m.content}"
            for m in messages
        ])

        prompt = SESSION_SUMMARY_PROMPT.format(conversation=conversation)

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            text = response.text if response.text else ""

            import json
            json_start = text.find('{')
            json_end = text.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                return json.loads(text[json_start:json_end])

        except Exception as e:
            _log.warning("Summarization error", error=str(e))

        return None

    def _build_fallback_summary(self, messages: List[TimestampedMessage]) -> Dict[str, Any]:
        """Build simple summary from last messages when LLM fails.

        Args:
            messages: List of session messages

        Returns:
            Minimal summary dict
        """
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
        """Search across all memory sources.

        Args:
            query: Search query
            include_all: Include session archive results

        Returns:
            Dict with results from working, sessions, and long_term
        """
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
        """Migrate data from old ChromaDB to new storage.

        Args:
            old_db_path: Path to old database
            dry_run: Preview without actual migration

        Returns:
            Migration statistics dict
        """
        old_db_path = old_db_path or str(CHROMADB_PATH)
        migrator = LegacyMemoryMigrator(
            old_db_path=old_db_path,
            new_long_term=self.long_term
        )
        return migrator.migrate(dry_run=dry_run)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics from all memory components.

        Returns:
            Dict with working, sessions, and long_term stats
        """
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

    # === Facade Methods for ChatHandler ===

    def get_session_id(self) -> str:
        """Get current session ID."""
        return self.working.session_id if self.working else "unknown"

    def get_turn_count(self) -> int:
        """Get current turn count."""
        return self.working.get_turn_count() if self.working else 0

    def is_working_available(self) -> bool:
        """Check if working memory is available."""
        return self.working is not None

    def is_session_archive_available(self) -> bool:
        """Check if session archive is available."""
        return self.session_archive is not None

    def is_graph_rag_available(self) -> bool:
        """Check if GraphRAG is available."""
        return self.graph_rag is not None

    def get_time_elapsed_context(self) -> Optional[str]:
        """Get time elapsed context from working memory."""
        if self.working:
            return self.working.get_time_elapsed_context()
        return None

    def get_progressive_context(self, full_turns: int = 40) -> str:
        """Get progressive context from working memory."""
        if self.working:
            return self.working.get_progressive_context(full_turns=full_turns)
        return ""

    async def save_working_to_disk(self) -> bool:
        """Save working memory to disk (async wrapper)."""
        if not self.working:
            return False
        try:
            return await asyncio.to_thread(self.working.save_to_disk)
        except Exception:
            return False
