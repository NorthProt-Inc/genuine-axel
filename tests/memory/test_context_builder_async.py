"""W2-1/W2-3: Async context builder M0/M5 inclusion tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.memory.event_buffer import EventBuffer, EventType, StreamEvent
from backend.memory.meta_memory import MetaMemory


class TestAsyncContextM0M5:
    """Verify async context path includes M0 and M5 sections."""

    def _make_mixin(self, *, events=None, hot_memories=None):
        """Create a minimal ContextBuilderMixin-like object."""
        from backend.memory.unified.context_builder import ContextBuilderMixin

        mixin = object.__new__(ContextBuilderMixin)

        # Working memory mock
        mixin.working = MagicMock()
        mixin.working.get_progressive_context.return_value = ""
        mixin.working.get_turn_count.return_value = 0
        mixin.working.get_time_elapsed_context.return_value = ""
        mixin.working.session_id = "test-session"

        # Session archive mock
        mixin.session_archive = MagicMock()
        mixin.session_archive.get_time_since_last_session.return_value = None
        mixin.session_archive.get_recent_summaries.return_value = ""

        # MemGPT mock
        mixin.memgpt = MagicMock()
        mixin.LONG_TERM_BUDGET = 1000
        mixin.SESSION_ARCHIVE_BUDGET = 500
        mixin.MAX_CONTEXT_TOKENS = 4000

        # GraphRAG mock
        mixin.graph_rag = None

        # M0: Event buffer
        mixin.event_buffer = EventBuffer()
        if events:
            for e in events:
                mixin.event_buffer.push(e)

        # M5: Meta memory
        mixin.meta_memory = MetaMemory()
        if hot_memories:
            for hm in hot_memories:
                for _ in range(hm.get("access_count", 1)):
                    mixin.meta_memory.record_access(
                        query_text="test",
                        matched_memory_ids=[hm["memory_id"]],
                        channel_id="test",
                    )

        return mixin

    @pytest.mark.asyncio
    async def test_async_context_includes_event_buffer(self):
        events = [
            StreamEvent(type=EventType.MESSAGE_RECEIVED, metadata={"role": "user"}),
            StreamEvent(type=EventType.TOOL_EXECUTED, metadata={"tool": "search"}),
        ]
        mixin = self._make_mixin(events=events)
        result = await mixin._build_smart_context_async("")

        assert "이벤트 버퍼" in result
        assert "message_received" in result

    @pytest.mark.asyncio
    async def test_async_context_includes_meta_memory(self):
        hot = [{"memory_id": "mem-abc123", "access_count": 3}]
        mixin = self._make_mixin(hot_memories=hot)
        result = await mixin._build_smart_context_async("")

        assert "메타 메모리" in result
        assert "mem-abc1" in result

    @pytest.mark.asyncio
    async def test_async_context_empty_when_no_data(self):
        mixin = self._make_mixin()
        result = await mixin._build_smart_context_async("")

        assert "이벤트 버퍼" not in result
        assert "메타 메모리" not in result
