"""
Context building service for ChatHandler.

Assembles context from 4-tier memory system for LLM prompts.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Dict, Any, List

from backend.core.context_optimizer import ContextOptimizer, get_dynamic_system_prompt
from backend.core.logging import get_logger, request_tracker as rt
from backend.core.utils.text import truncate_text
from backend.core.utils.timezone import VANCOUVER_TZ
from backend.config import (
    MAX_CODE_CONTEXT_CHARS,
    MAX_CODE_FILE_CHARS,
    MEMORY_LONG_TERM_BUDGET,
    MEMORY_SESSION_ARCHIVE_BUDGET,
    CONTEXT_WORKING_TURNS,
    CONTEXT_FULL_TURNS,
    CONTEXT_MAX_CHARS,
    CONTEXT_IO_TIMEOUT,
)

if TYPE_CHECKING:
    from backend.memory.unified import MemoryManager
    from backend.memory.permanent import LongTermMemory
    from backend.core.identity.ai_brain import IdentityManager

_log = get_logger("services.context")

# Default context building configuration
DEFAULT_CONTEXT_CONFIG = {
    "working_turns": CONTEXT_WORKING_TURNS,
    "full_turns": CONTEXT_FULL_TURNS,
    "chromadb_limit": 100,
    "use_graphrag": True,
    "max_context_chars": CONTEXT_MAX_CHARS,
}


def _format_as_bullets(items: List[str], max_items: int = 10) -> str:
    """Format items as bullet list."""
    if not items:
        return ""
    formatted = []
    for item in items[:max_items]:
        item = item.strip()
        if not item:
            continue
        if len(item) > 200:
            item = item[:197] + "..."
        formatted.append(f"- {item}")
    if len(items) > max_items:
        formatted.append(f"- ... ({len(items) - max_items} more)")
    return "\n".join(formatted)


def _truncate_text(text: str, max_chars: int, label: str = "") -> str:
    """Truncate text to max_chars with suffix indicator.

    Delegates to the shared truncate_text utility. Logs when truncation
    occurs and a label is provided.
    """
    if label and text and len(text) > max_chars > 0:
        _log.debug("CTX truncate", section=label, chars=len(text), limit=max_chars)
    return truncate_text(text, max_chars)


def _format_memory_age(timestamp_str: str, now: datetime = None) -> str:
    """Format memory age as human-readable string."""
    from datetime import timezone as tz

    if not timestamp_str:
        return ""

    try:
        if 'T' in timestamp_str:
            mem_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            mem_time = datetime.fromisoformat(timestamp_str)

        if mem_time.tzinfo is None:
            mem_time = mem_time.replace(tzinfo=tz.utc)

        now_time = now or datetime.now(tz.utc)
        delta = now_time - mem_time

        hours = delta.total_seconds() / 3600
        days = delta.days

        if hours < 1:
            return "방금"
        elif hours < 24:
            return f"{int(hours)}시간 전"
        elif days == 1:
            return "어제"
        elif days < 7:
            return f"{days}일 전"
        elif days < 30:
            weeks = days // 7
            return f"{weeks}주 전"
        elif days < 365:
            months = days // 30
            return f"{months}개월 전"
        else:
            return mem_time.strftime("%Y-%m-%d")
    except Exception:
        return ""


@dataclass
class ClassificationResult:
    """Query classification for context building."""
    needs_search: bool = False
    needs_tools: bool = False
    needs_code: bool = False


@dataclass
class ContextResult:
    """Result from context building."""
    system_prompt: str
    stats: Dict[str, Any] = field(default_factory=dict)
    turn_count: int = 0
    elapsed_ms: float = 0.0


class ContextService:
    """Service for building context from memory systems."""

    def __init__(
        self,
        memory_manager: Optional['MemoryManager'] = None,
        long_term_memory: Optional['LongTermMemory'] = None,
        identity_manager: Optional['IdentityManager'] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """Initialize context service.

        Args:
            memory_manager: Unified memory manager
            long_term_memory: Long-term memory storage
            identity_manager: Identity/persona manager
            config: Context building configuration
        """
        self.memory_manager = memory_manager
        self.long_term = long_term_memory
        self.identity_manager = identity_manager
        self.config = config or DEFAULT_CONTEXT_CONFIG
        self.vancouver_tz = VANCOUVER_TZ

    async def build(
        self,
        user_input: str,
        tier: str,
        model_config: Any,
        classification: Optional[ClassificationResult] = None
    ) -> ContextResult:
        """
        Build context prompt from all memory sources.

        Args:
            user_input: User's input query
            tier: Context tier level
            model_config: LLM model configuration
            classification: Query classification result

        Returns:
            ContextResult with assembled prompt
        """
        config = self.config
        context_start = time.perf_counter()

        optimizer = ContextOptimizer(tier)

        # Current time
        current_time = datetime.now(self.vancouver_tz).strftime("%Y년 %m월 %d일 (%A) %H:%M PST")

        # System prompt from identity
        full_system_prompt = ""
        if self.identity_manager:
            full_system_prompt = self.identity_manager.get_system_prompt()
        dynamic_prompt = get_dynamic_system_prompt(tier, full_system_prompt)
        optimizer.add_section("system_prompt", dynamic_prompt)

        # Temporal context
        temporal_content = f"현재 시각: {current_time}"
        if self.memory_manager and self.memory_manager.is_working_available():
            time_context = self.memory_manager.get_time_elapsed_context()
            if time_context:
                temporal_content += f"\n{time_context}"
                _log.debug("CTX temporal", context=time_context)
        optimizer.add_section("temporal", temporal_content)

        # Working memory context
        turn_count = 0
        if self.memory_manager and self.memory_manager.is_working_available():
            turn_count = self.memory_manager.get_turn_count()
            full_turns = config.get("full_turns", config["working_turns"] // 2)
            working_context = self.memory_manager.get_progressive_context(full_turns=full_turns)
            if working_context:
                optimizer.add_section("working_memory", working_context)
                _log.debug("MEM working", turns=turn_count, chars=len(working_context))
            else:
                _log.debug("MEM working empty", turns=turn_count)
        else:
            _log.warning("MEM working unavailable")

        # Long-term + GraphRAG + Session archive context (parallel fetch)
        longterm_data, graphrag_data, session_archive_data = await asyncio.gather(
            self._fetch_longterm_data(user_input, config),
            self._fetch_graphrag_data(user_input, config),
            self._fetch_session_archive_data(user_input),
        )
        if longterm_data:
            optimizer.add_section("long_term", longterm_data)
        if graphrag_data:
            optimizer.add_section("graphrag", graphrag_data)
        if session_archive_data:
            optimizer.add_section("session_archive", session_archive_data)

        # W3-2: M0 Event Buffer context
        event_buffer_data = self._fetch_event_buffer_data()
        if event_buffer_data:
            optimizer.add_section("event_buffer", event_buffer_data)

        # W3-2: M5 Hot Memories context
        hot_memories_data = self._fetch_hot_memories_data()
        if hot_memories_data:
            optimizer.add_section("hot_memories", hot_memories_data)

        # Code context (optional)
        code_summary, code_files_content = await self._build_code_context(
            user_input, classification
        )

        # Build final prompt
        optimized_context = optimizer.build()
        stats = optimizer.get_stats()

        full_prompt = f"## 현재 시간\n{current_time}\n\n"

        if optimized_context:
            full_prompt += f"## 기억 ({tier.upper()} Context)\n{optimized_context}"

        if code_summary:
            full_prompt += f"\n\n## 코드베이스\n{code_summary}"
        if code_files_content:
            full_prompt += code_files_content

        context_ms = (time.perf_counter() - context_start) * 1000

        _log.debug(
            "CTX build",
            tier=tier,
            working_turns=turn_count,
            sections=stats["sections_added"],
            truncated=stats["sections_truncated"],
            dropped=stats["sections_dropped"],
            raw_chars=stats["total_chars_raw"],
            final_chars=stats["total_chars_final"],
            tokens_approx=len(full_prompt) // 4,
            dur_ms=round(context_ms, 1),
        )

        rt.log_memory(
            longterm=config["chromadb_limit"],
            working=turn_count,
            tokens=len(full_prompt) // 4
        )

        return ContextResult(
            system_prompt=full_prompt,
            stats=stats,
            turn_count=turn_count,
            elapsed_ms=context_ms
        )

    async def _fetch_longterm_data(
        self,
        user_input: str,
        config: Dict[str, Any],
    ) -> Optional[str]:
        """Fetch long-term memory data (non-blocking via to_thread).

        Returns:
            Formatted memory string, or None if unavailable.
        """
        if not self.long_term:
            return None

        try:
            from backend.memory.temporal import parse_temporal_query

            try:
                temporal_filter = parse_temporal_query(user_input)
            except Exception as e:
                _log.debug("MEM temporal parse fail", error=str(e))
                temporal_filter = None

            memgpt = getattr(self.memory_manager, 'memgpt', None) if self.memory_manager else None
            if memgpt:
                token_budget = MEMORY_LONG_TERM_BUDGET
                limit = config["chromadb_limit"]

                selected_memories, used_tokens = await asyncio.to_thread(
                    memgpt.context_budget_select,
                    query=user_input,
                    token_budget=token_budget,
                    temporal_filter=temporal_filter,
                )
                if not selected_memories:
                    return None

                memory_items: List[str] = []
                for m in selected_memories[:limit]:
                    if not m.content:
                        continue
                    ts = (
                        m.metadata.get('event_timestamp') or
                        m.metadata.get('created_at') or
                        m.metadata.get('timestamp', '')
                    )
                    age_label = _format_memory_age(ts)
                    if age_label:
                        memory_items.append(f"[{age_label}] {m.content}")
                    else:
                        memory_items.append(m.content)

                if not memory_items:
                    return None

                memory_formatted = _format_as_bullets(memory_items)
                _log.debug("MEM longterm", count=len(memory_items), tokens=used_tokens)
                return memory_formatted
            else:
                formatted = await asyncio.to_thread(
                    self.long_term.get_formatted_context,
                    user_input,
                    max_items=config["chromadb_limit"],
                )
                if formatted:
                    _log.debug("MEM longterm fallback", chars=len(formatted))
                    return formatted
                return None
        except Exception as e:
            _log.warning("MEM longterm fail", error=str(e))
            return None

    async def _fetch_graphrag_data(
        self,
        user_input: str,
        config: Dict[str, Any],
    ) -> Optional[str]:
        """Fetch GraphRAG data (non-blocking via to_thread).

        Returns:
            GraphRAG context string, or None if unavailable.
        """
        if not config["use_graphrag"]:
            return None

        if not self.memory_manager or not self.memory_manager.is_graph_rag_available():
            return None

        try:
            graph_result = await asyncio.to_thread(
                self.memory_manager.graph_rag.query_sync, user_input
            )
            if graph_result and graph_result.context:
                _log.debug(
                    "MEM graphrag",
                    entities=len(graph_result.entities),
                    rels=len(graph_result.relations),
                    chars=len(graph_result.context),
                )
                return graph_result.context
            else:
                _log.debug("MEM graphrag empty")
                return None
        except Exception as e:
            _log.warning("MEM graphrag fail", error=str(e))
            return None

    async def _fetch_session_archive_data(
        self,
        user_input: str,
    ) -> Optional[str]:
        """Fetch session archive data with temporal filter support.

        Args:
            user_input: User query, parsed for temporal patterns.

        Returns:
            Session archive context string, or None if unavailable.
        """
        if not self.memory_manager or not self.memory_manager.is_session_archive_available():
            return None

        try:
            from backend.memory.temporal import parse_temporal_query

            session_archive = self.memory_manager.session_archive

            try:
                temporal_filter = parse_temporal_query(user_input)
            except Exception as e:
                _log.debug("MEM session temporal parse fail", error=str(e))
                temporal_filter = None

            budget = MEMORY_SESSION_ARCHIVE_BUDGET

            if temporal_filter:
                filter_type = temporal_filter.get("type")
                if filter_type == "exact":
                    from_date = temporal_filter.get("date")
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            session_archive.get_sessions_by_date,
                            from_date, None, 5, budget,
                        ),
                        timeout=CONTEXT_IO_TIMEOUT,
                    )
                elif filter_type == "range":
                    from_date = temporal_filter.get("from")
                    to_date = temporal_filter.get("to")
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            session_archive.get_sessions_by_date,
                            from_date, to_date, 10, budget,
                        ),
                        timeout=CONTEXT_IO_TIMEOUT,
                    )
                else:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            session_archive.get_recent_summaries, 10, budget,
                        ),
                        timeout=CONTEXT_IO_TIMEOUT,
                    )
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        session_archive.get_recent_summaries, 10, budget,
                    ),
                    timeout=CONTEXT_IO_TIMEOUT,
                )

            if not result or "최근 대화 기록이 없습니다" in result:
                return None

            _log.debug("MEM session_archive", chars=len(result))
            return result

        except asyncio.TimeoutError:
            _log.warning("MEM session_archive timeout", timeout=CONTEXT_IO_TIMEOUT)
            return None
        except Exception as e:
            _log.debug("MEM session_archive fail", error=str(e))
            return None

    async def _build_code_context(
        self,
        user_input: str,
        classification: Optional[ClassificationResult]
    ) -> tuple[str, str]:
        """Build code context if needed."""
        should_inject_code = classification and classification.needs_code
        if not should_inject_code:
            return "", ""

        try:
            from backend.core.tools.system_observer import get_code_summary, get_source_code

            code_summary = get_code_summary()
            if code_summary:
                code_summary = _truncate_text(
                    code_summary, MAX_CODE_CONTEXT_CHARS, label="code_summary"
                )
                _log.debug("CTX code", chars=len(code_summary))

            file_patterns = re.findall(
                r'([a-zA-Z_][a-zA-Z0-9_/]*\.py|[a-zA-Z_][a-zA-Z0-9_/]+/[a-zA-Z_][a-zA-Z0-9_]*\.[a-z]+)',
                user_input
            )
            injected_files = []
            code_files_content = ""
            for file_path in file_patterns[:3]:
                content = get_source_code(file_path)
                if content:
                    if len(content) > MAX_CODE_FILE_CHARS:
                        content = content[:MAX_CODE_FILE_CHARS] + "\n... (truncated)"
                    code_files_content += f"\n##  {file_path}\n```python\n{content}\n```"
                    injected_files.append(file_path)

            if injected_files:
                _log.debug("CTX code files", files=injected_files)

            return code_summary or "", code_files_content

        except Exception as e:
            _log.warning("CTX code fail", error=str(e))
            return "", ""

    def _fetch_event_buffer_data(self) -> Optional[str]:
        """Fetch M0 event buffer recent events.

        Returns:
            Formatted event buffer string, or None if unavailable.
        """
        if not self.memory_manager or not hasattr(self.memory_manager, 'event_buffer'):
            return None

        try:
            events = self.memory_manager.event_buffer.get_recent(limit=5)
            if not events:
                return None

            lines = []
            for event in events:
                event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
                lines.append(f"- [{event_type}] {event.metadata}")

            if lines:
                _log.debug("CTX event_buffer", events=len(lines))
                return "\n".join(lines)
        except Exception as e:
            _log.debug("CTX event_buffer fail", error=str(e))

        return None

    def _fetch_hot_memories_data(self) -> Optional[str]:
        """Fetch M5 hot memories.

        Returns:
            Formatted hot memories string, or None if unavailable.
        """
        if not self.memory_manager or not hasattr(self.memory_manager, 'meta_memory'):
            return None

        try:
            hot = self.memory_manager.meta_memory.get_hot_memories(limit=5)
            if not hot:
                return None

            lines = []
            for h in hot:
                mid = h["memory_id"][:8]
                count = h["access_count"]
                channels = h["channel_diversity"]
                lines.append(f"- {mid}… (access: {count}, channels: {channels})")

            if lines:
                _log.debug("CTX hot_memories", count=len(lines))
                return "\n".join(lines)
        except Exception as e:
            _log.debug("CTX hot_memories fail", error=str(e))

        return None
