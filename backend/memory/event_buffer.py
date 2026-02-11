"""M0 Event Buffer — in-memory asyncio-compatible event stream.

Session-lifetime buffer using deque with maxsize.
Queue full → oldest event dropped (deque maxlen behavior).
No persistence needed (session-scoped).
"""

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List

from backend.core.logging import get_logger
from backend.core.utils.timezone import now_vancouver

_log = get_logger("memory.event_buffer")


class EventType(str, Enum):
    MESSAGE_RECEIVED = "message_received"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    MEMORY_ACCESSED = "memory_accessed"
    ENTITY_EXTRACTED = "entity_extracted"
    TOOL_EXECUTED = "tool_executed"


@dataclass
class StreamEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: EventType = EventType.MESSAGE_RECEIVED
    timestamp: datetime = field(default_factory=now_vancouver)
    metadata: Dict[str, Any] = field(default_factory=dict)


class EventBuffer:
    """Session-lifetime event buffer (M0 layer).

    In-memory buffer using deque with maxsize.
    Queue full → oldest event dropped by deque.
    No persistence needed (session-scoped).
    """

    DEFAULT_MAXSIZE = 1000

    def __init__(self, maxsize: int = DEFAULT_MAXSIZE):
        self._buffer: deque[StreamEvent] = deque(maxlen=maxsize)
        self._maxsize = maxsize
        self._total_pushed = 0
        self._total_dropped = 0
        self._handlers: List[Callable[[StreamEvent], Coroutine]] = []

    def push(self, event: StreamEvent) -> None:
        """Push event. If full, oldest is automatically dropped by deque."""
        was_full = len(self._buffer) >= self._maxsize
        self._buffer.append(event)
        self._total_pushed += 1
        if was_full:
            self._total_dropped += 1
        _log.debug("Event pushed", type=event.type.value, queue_size=len(self._buffer))

    def get_recent(self, n: int = 10) -> List[StreamEvent]:
        """Get most recent N events."""
        if n <= 0:
            return []
        return list(self._buffer)[-n:]

    def get_by_type(self, event_type: EventType, limit: int = 10) -> List[StreamEvent]:
        """Get recent events of specific type."""
        return [e for e in reversed(self._buffer) if e.type == event_type][:limit]

    def register_handler(self, handler: Callable[[StreamEvent], Coroutine]) -> None:
        """Register async event handler for consume pattern."""
        self._handlers.append(handler)

    async def dispatch(self, event: StreamEvent) -> None:
        """Push event and dispatch to all registered handlers."""
        self.push(event)
        for handler in self._handlers:
            try:
                await handler(event)
            except Exception as e:
                _log.warning("Event handler failed", type=event.type.value, error=str(e))

    def clear(self) -> None:
        """Clear all events (session end)."""
        self._buffer.clear()

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "current_size": len(self._buffer),
            "total_pushed": self._total_pushed,
            "total_dropped": self._total_dropped,
            "maxsize": self._maxsize,
        }
