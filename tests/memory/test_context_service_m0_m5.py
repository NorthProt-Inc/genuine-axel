"""W3-2: Verify ContextService includes M0 event buffer and M5 hot memories."""

from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass

import pytest

from backend.core.services.context_service import ContextService


def _make_context_service(
    has_event_buffer: bool = True,
    has_meta_memory: bool = True,
    events: list | None = None,
    hot_memories: list | None = None,
) -> ContextService:
    """Build ContextService with mocked memory manager."""
    mm = MagicMock()
    mm.is_working_available.return_value = True
    mm.is_graph_rag_available.return_value = False
    mm.is_session_archive_available.return_value = False
    mm.get_turn_count.return_value = 0
    mm.get_progressive_context.return_value = ""
    mm.get_time_elapsed_context.return_value = ""

    if has_event_buffer:
        @dataclass
        class FakeEvent:
            type: str = "message_received"
            metadata: dict = None

            def __post_init__(self):
                if self.metadata is None:
                    self.metadata = {}

        buf = MagicMock()
        buf.get_recent.return_value = events or [
            FakeEvent(type="message_received", metadata={"role": "user"}),
        ]
        mm.event_buffer = buf
    else:
        del mm.event_buffer

    if has_meta_memory:
        meta = MagicMock()
        meta.get_hot_memories.return_value = hot_memories or [
            {"memory_id": "abcd1234-5678", "access_count": 15, "channel_diversity": 3},
        ]
        mm.meta_memory = meta
    else:
        del mm.meta_memory

    return ContextService(memory_manager=mm)


class TestContextServiceM0M5:

    def test_event_buffer_data_returned(self):
        svc = _make_context_service(has_event_buffer=True)
        result = svc._fetch_event_buffer_data()
        assert result is not None
        assert "message_received" in result

    def test_event_buffer_none_when_no_events(self):
        mm = MagicMock()
        buf = MagicMock()
        buf.get_recent.return_value = []
        mm.event_buffer = buf
        svc = ContextService(memory_manager=mm)
        result = svc._fetch_event_buffer_data()
        assert result is None

    def test_event_buffer_none_when_no_buffer(self):
        svc = _make_context_service(has_event_buffer=False)
        result = svc._fetch_event_buffer_data()
        assert result is None

    def test_hot_memories_data_returned(self):
        svc = _make_context_service(has_meta_memory=True)
        result = svc._fetch_hot_memories_data()
        assert result is not None
        assert "abcd1234" in result
        assert "access: 15" in result

    def test_hot_memories_none_when_empty(self):
        mm = MagicMock()
        meta = MagicMock()
        meta.get_hot_memories.return_value = []
        mm.meta_memory = meta
        svc = ContextService(memory_manager=mm)
        result = svc._fetch_hot_memories_data()
        assert result is None

    def test_hot_memories_none_when_no_meta(self):
        svc = _make_context_service(has_meta_memory=False)
        result = svc._fetch_hot_memories_data()
        assert result is None
