import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.core.logging import get_logger
from backend.config import CHROMADB_PATH

from ..current import TimestampedMessage
from ..permanent import LegacyMemoryMigrator
from ..event_buffer import StreamEvent, EventType

_log = get_logger("memory.unified.session")

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


class SessionMixin:
    """Mixin for session management, summarization, and querying."""

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

            # PERF-028: Batch fact and insight storage
            facts = summary_result.get("facts_discovered", [])
            insights = summary_result.get("insights_discovered", [])

            for fact in facts:
                self.long_term.add(
                    content=fact,
                    memory_type="fact",
                    importance=0.7,
                    source_session=session_id
                )

            for insight in insights:
                self.long_term.add(
                    content=insight,
                    memory_type="insight",
                    importance=0.6,
                    source_session=session_id
                )

        # M0: Push session_end event and clear buffer
        self.event_buffer.push(StreamEvent(
            type=EventType.SESSION_END,
            metadata={"session_id": session_id, "messages": len(messages)},
        ))
        self.event_buffer.clear()

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
        results: Dict[str, list[Any]] = {
            "working": [],
            "sessions": [],
            "long_term": [],
        }

        # PERF-028: Cache query_lower and access messages once
        query_lower = query.lower()
        for msg in self.working.messages:
            if query_lower in msg.content.lower():
                results["working"].append({
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                    "role": msg.role
                })

        if include_all:
            results["sessions"] = self.session_archive.search_by_topic(query, limit=3)

        results["long_term"] = self.long_term.query(query, n_results=5)

        return results

    def migrate_legacy_data(self, old_db_path: Optional[str] = None, dry_run: bool = True) -> Dict:
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
