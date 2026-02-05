"""
Context building service for ChatHandler.

Assembles context from 4-tier memory system for LLM prompts.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Dict, Any, List

from backend.core.context_optimizer import ContextOptimizer, get_dynamic_system_prompt
from backend.core.logging import get_logger, request_tracker as rt
from backend.core.utils.timezone import VANCOUVER_TZ
from backend.config import (
    MAX_CODE_CONTEXT_CHARS,
    MAX_CODE_FILE_CHARS,
    MEMORY_LONG_TERM_BUDGET,
    CONTEXT_WORKING_TURNS,
    CONTEXT_FULL_TURNS,
    CONTEXT_MAX_CHARS,
    CONTEXT_SESSION_COUNT,
    CONTEXT_SESSION_BUDGET,
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
    "use_sqlite": True,
    "chromadb_limit": 100,
    "use_graphrag": True,
    "max_context_chars": CONTEXT_MAX_CHARS,
    "session_count": CONTEXT_SESSION_COUNT,
    "session_budget": CONTEXT_SESSION_BUDGET,
}


def _truncate_text(text: str, max_chars: int, label: str = "") -> str:
    """Truncate text to max_chars with suffix indicator."""
    if not text:
        return ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    suffix = "\n... (truncated)"
    keep = max_chars - len(suffix)
    if keep <= 0:
        return text[:max_chars]
    if label:
        _log.debug("CTX truncate", section=label, chars=len(text), limit=max_chars)
    return text[:keep].rstrip() + suffix


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

        # Current time and model awareness
        current_time = datetime.now(self.vancouver_tz).strftime("%Y년 %m월 %d일 (%A) %H:%M PST")
        model_awareness = f" 현재 모드: {model_config.name} ({tier.upper()} 티어)"

        # System prompt from identity
        full_system_prompt = ""
        if self.identity_manager:
            full_system_prompt = self.identity_manager.get_system_prompt()
        dynamic_prompt = get_dynamic_system_prompt(tier, full_system_prompt)
        optimizer.add_section("system_prompt", dynamic_prompt)

        # Temporal context
        temporal_content = f"현재 시각: {current_time}\n{model_awareness}"
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

        # Session archive context
        if config["use_sqlite"] and self.memory_manager and self.memory_manager.is_session_archive_available():
            try:
                session_count = config.get("session_count", 10)
                session_budget = config.get("session_budget", 3000)
                session_context = self.memory_manager.session_archive.get_recent_summaries(
                    session_count, session_budget
                )
                if session_context and "최근 대화 기록이 없습니다" not in session_context:
                    session_lines = [line.strip() for line in session_context.split('\n') if line.strip()]
                    session_formatted = optimizer.format_as_bullets(session_lines)
                    optimizer.add_section("session_archive", session_formatted)
                    _log.debug("MEM session", chars=len(session_formatted))
                else:
                    _log.debug("MEM session empty")
            except Exception as e:
                _log.warning("MEM session fail", error=str(e))

        # Long-term memory context
        await self._add_longterm_context(optimizer, user_input, config)

        # GraphRAG context
        await self._add_graphrag_context(optimizer, user_input, config)

        # Code context (optional)
        code_summary, code_files_content = await self._build_code_context(
            user_input, classification
        )

        # Build final prompt
        optimized_context = optimizer.build()
        stats = optimizer.get_stats()

        full_prompt = f"##  현재 시간\n{current_time}\n\n"

        if optimized_context:
            full_prompt += f"##  기억 ({tier.upper()} Context)\n{optimized_context}"

        if code_summary:
            full_prompt += f"\n\n##  내 코드베이스\n{code_summary}"
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

    async def _add_longterm_context(
        self,
        optimizer: ContextOptimizer,
        user_input: str,
        config: Dict[str, Any]
    ) -> None:
        """Add long-term memory context to optimizer."""
        if not self.long_term:
            return

        try:
            memgpt = getattr(self.memory_manager, 'memgpt', None) if self.memory_manager else None
            if memgpt:
                token_budget = MEMORY_LONG_TERM_BUDGET

                selected_memories, used_tokens = memgpt.context_budget_select(
                    query=user_input,
                    token_budget=token_budget
                )
                if selected_memories:
                    memory_items = []
                    for m in selected_memories[:config["chromadb_limit"]]:
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

                    temporal_hint = " 각 기억의 [시간] 라벨을 참고해."
                    memory_formatted = temporal_hint + "\n" + optimizer.format_as_bullets(memory_items)
                    optimizer.add_section("long_term", memory_formatted)
                    _log.debug("MEM longterm", count=len(memory_items), tokens=used_tokens)
            else:
                formatted = self.long_term.get_formatted_context(
                    user_input, max_items=config["chromadb_limit"]
                )
                if formatted:
                    optimizer.add_section("long_term", formatted)
                    _log.debug("MEM longterm fallback", chars=len(formatted))
        except Exception as e:
            _log.warning("MEM longterm fail", error=str(e))

    async def _add_graphrag_context(
        self,
        optimizer: ContextOptimizer,
        user_input: str,
        config: Dict[str, Any]
    ) -> None:
        """Add GraphRAG context to optimizer."""
        if not config["use_graphrag"]:
            return

        if not self.memory_manager or not self.memory_manager.is_graph_rag_available():
            return

        try:
            graph_result = self.memory_manager.graph_rag.query_sync(user_input)
            if graph_result and graph_result.context:
                optimizer.add_section("graphrag", graph_result.context)
                _log.debug(
                    "MEM graphrag",
                    entities=len(graph_result.entities),
                    rels=len(graph_result.relations),
                    chars=len(graph_result.context)
                )
            else:
                _log.debug("MEM graphrag empty")
        except Exception as e:
            _log.warning("MEM graphrag fail", error=str(e))

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
                        content = content[:MAX_CODE_FILE_CHARS] + f"\n... (truncated)"
                    code_files_content += f"\n##  {file_path}\n```python\n{content}\n```"
                    injected_files.append(file_path)

            if injected_files:
                _log.debug("CTX code files", files=injected_files)

            return code_summary or "", code_files_content

        except Exception as e:
            _log.warning("CTX code fail", error=str(e))
            return "", ""
