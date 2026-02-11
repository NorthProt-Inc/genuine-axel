"""W2-2/W2-3: M0 → M5 event bridge tests."""

import pytest

from backend.memory.event_buffer import EventBuffer, EventType, StreamEvent
from backend.memory.meta_memory import MetaMemory


class TestEventMetaBridge:
    """Test MEMORY_ACCESSED event → M5 record_access propagation."""

    @pytest.mark.asyncio
    async def test_memory_accessed_event_triggers_record(self):
        eb = EventBuffer()
        meta = MetaMemory()

        async def handler(event: StreamEvent) -> None:
            if event.type == EventType.MEMORY_ACCESSED:
                meta.record_access(
                    query_text=event.metadata.get("query", ""),
                    matched_memory_ids=event.metadata.get("memory_ids", []),
                    channel_id=event.metadata.get("channel_id", "default"),
                )

        eb.register_handler(handler)

        event = StreamEvent(
            type=EventType.MEMORY_ACCESSED,
            metadata={
                "query": "What is Python?",
                "memory_ids": ["mem-001", "mem-002"],
                "channel_id": "discord",
            },
        )
        await eb.dispatch(event)

        hot = meta.get_hot_memories(limit=5)
        assert len(hot) == 2
        assert meta.get_channel_mentions("mem-001") == 1
        assert meta.get_channel_mentions("mem-002") == 1

    @pytest.mark.asyncio
    async def test_non_memory_event_does_not_trigger(self):
        eb = EventBuffer()
        meta = MetaMemory()

        async def handler(event: StreamEvent) -> None:
            if event.type == EventType.MEMORY_ACCESSED:
                meta.record_access(
                    query_text=event.metadata.get("query", ""),
                    matched_memory_ids=event.metadata.get("memory_ids", []),
                    channel_id=event.metadata.get("channel_id", "default"),
                )

        eb.register_handler(handler)

        event = StreamEvent(
            type=EventType.MESSAGE_RECEIVED,
            metadata={"role": "user"},
        )
        await eb.dispatch(event)

        assert meta.get_hot_memories(limit=5) == []

    @pytest.mark.asyncio
    async def test_multiple_events_accumulate(self):
        eb = EventBuffer()
        meta = MetaMemory()

        async def handler(event: StreamEvent) -> None:
            if event.type == EventType.MEMORY_ACCESSED:
                meta.record_access(
                    query_text=event.metadata.get("query", ""),
                    matched_memory_ids=event.metadata.get("memory_ids", []),
                    channel_id=event.metadata.get("channel_id", "default"),
                )

        eb.register_handler(handler)

        for ch in ["discord", "slack"]:
            await eb.dispatch(StreamEvent(
                type=EventType.MEMORY_ACCESSED,
                metadata={
                    "query": "test",
                    "memory_ids": ["mem-001"],
                    "channel_id": ch,
                },
            ))

        assert meta.get_channel_mentions("mem-001") == 2
        hot = meta.get_hot_memories(limit=1)
        assert hot[0]["access_count"] == 2
