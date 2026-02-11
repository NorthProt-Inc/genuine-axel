"""Tests for M0 Event Buffer."""

import asyncio

import pytest

from backend.memory.event_buffer import EventBuffer, EventType, StreamEvent


class TestEventBufferPushAndGetRecent:

    def test_push_and_get_recent(self):
        """Push 3 events, get_recent(2) returns last 2."""
        buf = EventBuffer()
        e1 = StreamEvent(event_id="a", type=EventType.MESSAGE_RECEIVED)
        e2 = StreamEvent(event_id="b", type=EventType.SESSION_START)
        e3 = StreamEvent(event_id="c", type=EventType.TOOL_EXECUTED)

        buf.push(e1)
        buf.push(e2)
        buf.push(e3)

        recent = buf.get_recent(2)
        assert len(recent) == 2
        assert recent[0].event_id == "b"
        assert recent[1].event_id == "c"

    def test_empty_buffer_returns_empty(self):
        """Empty buffer returns empty list."""
        buf = EventBuffer()
        assert buf.get_recent() == []
        assert buf.get_recent(5) == []

    def test_get_recent_zero_returns_empty(self):
        """get_recent(0) returns empty list."""
        buf = EventBuffer()
        buf.push(StreamEvent(event_id="x"))
        assert buf.get_recent(0) == []


class TestEventBufferMaxsize:

    def test_maxsize_drops_oldest(self):
        """maxsize=3, push 5 → only last 3 remain, dropped=2."""
        buf = EventBuffer(maxsize=3)
        for i in range(5):
            buf.push(StreamEvent(event_id=str(i)))

        assert len(buf.get_recent(10)) == 3
        ids = [e.event_id for e in buf.get_recent(10)]
        assert ids == ["2", "3", "4"]

        stats = buf.stats
        assert stats["total_pushed"] == 5
        assert stats["total_dropped"] == 2
        assert stats["current_size"] == 3
        assert stats["maxsize"] == 3


class TestEventBufferGetByType:

    def test_get_by_type_filter(self):
        """Filter events by type."""
        buf = EventBuffer()
        buf.push(StreamEvent(event_id="1", type=EventType.MESSAGE_RECEIVED))
        buf.push(StreamEvent(event_id="2", type=EventType.SESSION_START))
        buf.push(StreamEvent(event_id="3", type=EventType.MESSAGE_RECEIVED))
        buf.push(StreamEvent(event_id="4", type=EventType.TOOL_EXECUTED))

        msgs = buf.get_by_type(EventType.MESSAGE_RECEIVED)
        assert len(msgs) == 2
        # Most recent first (reversed iteration)
        assert msgs[0].event_id == "3"
        assert msgs[1].event_id == "1"

    def test_get_by_type_limit(self):
        """Limit number of filtered results."""
        buf = EventBuffer()
        for i in range(10):
            buf.push(StreamEvent(event_id=str(i), type=EventType.MESSAGE_RECEIVED))

        result = buf.get_by_type(EventType.MESSAGE_RECEIVED, limit=3)
        assert len(result) == 3


class TestEventBufferDispatch:

    @pytest.mark.asyncio
    async def test_dispatch_calls_handlers(self):
        """Registered async handler is called on dispatch."""
        buf = EventBuffer()
        received = []

        async def handler(event: StreamEvent):
            received.append(event.event_id)

        buf.register_handler(handler)

        event = StreamEvent(event_id="dispatch-1", type=EventType.ENTITY_EXTRACTED)
        await buf.dispatch(event)

        assert received == ["dispatch-1"]
        assert buf.stats["total_pushed"] == 1

    @pytest.mark.asyncio
    async def test_dispatch_handler_failure_does_not_propagate(self):
        """Handler failure is caught, event still pushed."""
        buf = EventBuffer()

        async def bad_handler(event: StreamEvent):
            raise ValueError("boom")

        buf.register_handler(bad_handler)

        event = StreamEvent(event_id="fail-1")
        await buf.dispatch(event)  # Should not raise

        assert buf.stats["total_pushed"] == 1
        assert buf.get_recent(1)[0].event_id == "fail-1"


class TestEventBufferClear:

    def test_clear(self):
        """Clear removes all events."""
        buf = EventBuffer()
        buf.push(StreamEvent(event_id="1"))
        buf.push(StreamEvent(event_id="2"))
        buf.clear()

        assert buf.get_recent() == []
        assert buf.stats["current_size"] == 0
        # Counters persist after clear
        assert buf.stats["total_pushed"] == 2
