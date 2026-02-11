import asyncio
import time
from datetime import datetime, timedelta

from backend.core.logging import get_logger
from backend.core.utils.text import truncate_text
from backend.core.utils.timezone import VANCOUVER_TZ
from backend.core.security.prompt_defense import filter_output
from backend.core.persona.channel_adaptation import get_channel_hint

_log = get_logger("memory.unified.context_builder")


class ContextBuilderMixin:
    """Mixin for context building methods (sync + async)."""

    async def build_smart_context(
        self,
        current_query: str,
        channel_id: str = "default",
    ) -> str:
        """Build intelligent context from all memory sources.

        Uses async parallel fetch for optimal performance.

        Args:
            current_query: Current user query for relevance scoring
            channel_id: Channel ID for adaptation

        Returns:
            Formatted context string with time, working, long-term, and graph data
        """
        t0 = time.monotonic()
        self._current_channel_id = channel_id
        result = await self._build_smart_context_async(current_query)
        dur_ms = int((time.monotonic() - t0) * 1000)
        _log.info("Context build done", sources=result.count("##"), dur_ms=dur_ms)

        # Apply channel adaptation hint
        channel_hint = get_channel_hint(channel_id)
        if channel_hint:
            result = f"## 채널 톤 가이드\n{channel_hint}\n\n{result}"

        # Prompt defense: filter output
        result = filter_output(result)

        return result

    def build_smart_context_sync(
        self,
        current_query: str,
        channel_id: str = "default",
    ) -> str:
        """Sync wrapper for build_smart_context (backward compat).

        Args:
            current_query: Current user query for relevance scoring
            channel_id: Channel ID for adaptation

        Returns:
            Formatted context string
        """
        t0 = time.monotonic()
        self._current_channel_id = channel_id
        try:
            asyncio.get_running_loop()
            result = self._build_smart_context_sync(current_query)
        except RuntimeError:
            result = asyncio.run(self._build_smart_context_async(current_query))
        dur_ms = int((time.monotonic() - t0) * 1000)
        _log.info("Context build done (sync)", sources=result.count("##"), dur_ms=dur_ms)

        channel_hint = get_channel_hint(channel_id)
        if channel_hint:
            result = f"## 채널 톤 가이드\n{channel_hint}\n\n{result}"

        result = filter_output(result)
        return result

    def _build_smart_context_sync(self, current_query: str) -> str:
        """Build context synchronously (sequential fetches)."""
        context_parts = []

        time_context = self._build_time_context()
        if time_context:
            context_parts.append(f"## 시간 컨텍스트\n{time_context}")

        working_context = self.working.get_progressive_context()
        if working_context:
            context_parts.append(f"## 현재 대화 (최근 {self.working.get_turn_count()}턴, Progressive)\n{working_context}")

        if current_query:

            from ..temporal import parse_temporal_query
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

                    # W1-1: Record M3 access patterns in M5 Meta Memory
                    if hasattr(self, "meta_memory") and self.meta_memory:
                        try:
                            self.meta_memory.record_access(
                                query_text=current_query,
                                matched_memory_ids=[m.id for m in selected_memories],
                                relevance_scores=[m.score for m in selected_memories if m.score],
                                channel_id=getattr(self, "_current_channel_id", "default"),
                            )
                        except Exception as e:
                            _log.debug("M5 record_access failed (sync)", error=str(e))
            except Exception as e:
                _log.warning("MemGPT selection failed (sync)", error=str(e))

            try:
                if temporal_filter:
                    filter_type = temporal_filter.get("type")
                    if filter_type == "exact":
                        from_date = temporal_filter.get("date") or ""
                        session_context = self.session_archive.get_sessions_by_date(
                            from_date, "", 5, self.SESSION_ARCHIVE_BUDGET
                        )
                    elif filter_type == "range":
                        from_date = temporal_filter.get("from") or ""
                        to_date = temporal_filter.get("to") or ""
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

        # M0: Event buffer context (recent events)
        recent_events = self.event_buffer.get_recent(5)
        if recent_events:
            event_lines = [
                f"- [{e.type.value}] {e.timestamp.strftime('%H:%M')}"
                for e in recent_events
            ]
            context_parts.append(f"## 이벤트 버퍼 (최근 {len(recent_events)}개)\n" + "\n".join(event_lines))

        # M5: Meta memory context (hot memories)
        hot_memories = self.meta_memory.get_hot_memories(limit=5)
        if hot_memories:
            hot_lines = [
                f"- {hm['memory_id'][:8]}... (접근 {hm['access_count']}회, 채널 {hm['channel_diversity']}개)"
                for hm in hot_memories
            ]
            context_parts.append(f"## 메타 메모리 (핫 {len(hot_memories)}개)\n" + "\n".join(hot_lines))

        context_text = "\n\n".join(context_parts)
        context_text = truncate_text(context_text, self.MAX_CONTEXT_TOKENS * 4)

        return context_text

    # ── Async fetch wrappers for parallel context assembly ───────────

    async def _fetch_long_term(self, query: str, temporal_filter):
        """Fetch long-term memories in a thread."""
        return await asyncio.to_thread(
            self.memgpt.context_budget_select,
            query, self.LONG_TERM_BUDGET, None, temporal_filter,
        )

    async def _fetch_session_archive(self, query: str, temporal_filter):
        """Fetch session archive in a thread."""
        if temporal_filter:
            filter_type = temporal_filter.get("type")
            if filter_type == "exact":
                from_date = temporal_filter.get("date")
                return await asyncio.to_thread(
                    self.session_archive.get_sessions_by_date,
                    from_date, None, 5, self.SESSION_ARCHIVE_BUDGET,
                )
            elif filter_type == "range":
                from_date = temporal_filter.get("from")
                to_date = temporal_filter.get("to")
                return await asyncio.to_thread(
                    self.session_archive.get_sessions_by_date,
                    from_date, to_date, 10, self.SESSION_ARCHIVE_BUDGET,
                )
        return await asyncio.to_thread(
            self.session_archive.get_recent_summaries,
            10, self.SESSION_ARCHIVE_BUDGET,
        )

    async def _fetch_graph_rag(self, query: str):
        """Fetch graph RAG results in a thread."""
        if not self.graph_rag:
            return None
        return await asyncio.to_thread(self.graph_rag.query_sync, query)

    async def _build_smart_context_async(self, current_query: str) -> str:
        """Build context with parallel fetches using asyncio.gather."""
        context_parts = []

        time_context = self._build_time_context()
        if time_context:
            context_parts.append(f"## 시간 컨텍스트\n{time_context}")

        working_context = self.working.get_progressive_context()
        if working_context:
            context_parts.append(
                f"## 현재 대화 (최근 {self.working.get_turn_count()}턴, Progressive)\n{working_context}"
            )

        if current_query:
            from ..temporal import parse_temporal_query
            temporal_filter = parse_temporal_query(current_query)

            # W3-1: GraphRAG first, then enrich M3 query with entities
            try:
                gr_result = await self._fetch_graph_rag(current_query)
            except Exception as e:
                gr_result = e
                _log.debug("GraphRAG fetch failed", error=str(e))

            enriched_query = current_query
            if (
                not isinstance(gr_result, BaseException)
                and gr_result
                and hasattr(gr_result, "entities")
                and gr_result.entities
            ):
                entity_names = " ".join(e.name for e in gr_result.entities[:3])
                enriched_query = f"{current_query} {entity_names}"

            # Parallel fetch: M3 (enriched) + M2 (session archive)
            lt_result, sa_result = await asyncio.gather(
                self._fetch_long_term(enriched_query, temporal_filter),
                self._fetch_session_archive(current_query, temporal_filter),
                return_exceptions=True,
            )

            # Long-term memories
            if not isinstance(lt_result, BaseException) and lt_result:
                selected_memories, tokens_used = lt_result
                if selected_memories:
                    memory_lines = []
                    for mem in selected_memories:
                        score_str = f"[{mem.score:.2f}]" if mem.score else ""
                        memory_lines.append(f"- {score_str} {mem.content[:200]}...")
                    context_parts.append(
                        f"## 관련 장기 기억 ({len(selected_memories)}개, {tokens_used} tokens)\n"
                        + "\n".join(memory_lines)
                    )

                    # W1-1: Record M3 access patterns in M5 Meta Memory
                    if hasattr(self, "meta_memory") and self.meta_memory:
                        try:
                            self.meta_memory.record_access(
                                query_text=current_query,
                                matched_memory_ids=[m.id for m in selected_memories],
                                relevance_scores=[m.score for m in selected_memories if m.score],
                                channel_id=getattr(self, "_current_channel_id", "default"),
                            )
                        except Exception as e:
                            _log.debug("M5 record_access failed", error=str(e))
            elif isinstance(lt_result, BaseException):
                _log.warning("MemGPT selection failed (async)", error=str(lt_result))

            # Session archive
            if not isinstance(sa_result, BaseException) and sa_result:
                if "최근 대화 기록이 없습니다" not in sa_result:
                    context_parts.append(f"## 최근 세션 기록\n{sa_result}")
            elif isinstance(sa_result, BaseException):
                _log.debug("Session archive fetch failed (async)", error=str(sa_result))

            # GraphRAG
            if not isinstance(gr_result, BaseException) and gr_result and gr_result.context:
                context_parts.append(f"## 관계 기반 지식\n{gr_result.context}")
            elif isinstance(gr_result, BaseException):
                _log.debug("GraphRAG query skipped (async)", error=str(gr_result))

        # M0: Event buffer context (recent events)
        recent_events = self.event_buffer.get_recent(5)
        if recent_events:
            event_lines = [
                f"- [{e.type.value}] {e.timestamp.strftime('%H:%M')}"
                for e in recent_events
            ]
            context_parts.append(f"## 이벤트 버퍼 (최근 {len(recent_events)}개)\n" + "\n".join(event_lines))

        # M5: Meta memory context (hot memories)
        hot_memories = self.meta_memory.get_hot_memories(limit=5)
        if hot_memories:
            hot_lines = [
                f"- {hm['memory_id'][:8]}... (접근 {hm['access_count']}회, 채널 {hm['channel_diversity']}개)"
                for hm in hot_memories
            ]
            context_parts.append(f"## 메타 메모리 (핫 {len(hot_memories)}개)\n" + "\n".join(hot_lines))

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
