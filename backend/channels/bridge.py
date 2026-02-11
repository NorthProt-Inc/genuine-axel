"""ChatHandler adapter — bridge between channel adapters and ChatHandler.

Converts InboundMessage to ChatRequest, calls ChatHandler.process(),
and yields ChatEvent stream back to the channel adapter.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from backend.channels.protocol import InboundMessage
from backend.core.chat_handler import ChatHandler, ChatRequest, ChatEvent
from backend.core.logging import get_logger

_log = get_logger("channels.bridge")

# Per-user semaphore to prevent concurrent processing
_user_locks: dict[str, asyncio.Semaphore] = {}
_USER_LOCK_LIMIT = 1


def _get_user_lock(user_id: str) -> asyncio.Semaphore:
    """Get or create a per-user semaphore."""
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Semaphore(_USER_LOCK_LIMIT)
    return _user_locks[user_id]


async def handle_channel_message(
    message: InboundMessage,
    handler: ChatHandler,
) -> AsyncGenerator[ChatEvent, None]:
    """Process an inbound channel message through ChatHandler.

    Acquires a per-user lock to prevent concurrent processing,
    converts InboundMessage to ChatRequest, and yields ChatEvent stream.

    Args:
        message: Normalized inbound message from any platform.
        handler: ChatHandler instance with initialized state.

    Yields:
        ChatEvent objects for streaming response.
    """
    lock = _get_user_lock(message.user_id)

    async with lock:
        request = ChatRequest(
            user_input=message.content,
            model_choice=message.metadata.get("model", "anthropic"),
            tier=message.metadata.get("tier", "axel"),
            enable_search=message.metadata.get("enable_search", False),
        )

        _log.info(
            "CHANNEL message received",
            platform=message.platform.value,
            user=message.user_id,
            channel=message.channel_id,
            input_len=len(message.content),
        )

        try:
            async for event in handler.process(request):
                yield event
        except Exception:
            _log.exception(
                "CHANNEL handler error",
                platform=message.platform.value,
                user=message.user_id,
            )
            raise
