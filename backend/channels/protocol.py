"""Channel Adapter Protocol — normalized interface for messaging platforms.

Inspired by axel's AxelChannel pattern and OpenClaw's multi-channel architecture.
Each platform adapter (Discord, Telegram, etc.) implements ChannelAdapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Protocol, runtime_checkable


class Platform(str, Enum):
    """Supported messaging platforms."""

    DISCORD = "discord"
    TELEGRAM = "telegram"


@dataclass(frozen=True)
class ChannelCapabilities:
    """Declares what a channel adapter supports."""

    streaming_edit: bool = False
    max_message_length: int = 2000
    typing_indicator: bool = False
    rich_media: bool = False
    threads: bool = False
    reactions: bool = False


@dataclass
class InboundMessage:
    """Normalized inbound message from any platform."""

    user_id: str
    channel_id: str
    content: str
    platform: Platform
    username: str = ""
    thread_id: str | None = None
    reply_to: str | None = None
    timestamp: float = 0.0
    raw_event: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """Normalized outbound message to any platform."""

    content: str
    reply_to: str | None = None
    format: str = "markdown"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthStatus:
    """Health check result for a channel adapter."""

    healthy: bool
    platform: Platform
    latency_ms: float = 0.0
    details: str = ""


@runtime_checkable
class ChannelAdapter(Protocol):
    """Protocol for messaging platform adapters.

    Each adapter must:
    - start/stop the bot connection
    - send single or streaming messages
    - report health status
    - declare capabilities
    """

    @property
    def platform(self) -> Platform: ...

    @property
    def capabilities(self) -> ChannelCapabilities: ...

    async def start(self) -> None:
        """Connect to the platform and start listening for messages."""
        ...

    async def stop(self) -> None:
        """Gracefully disconnect from the platform."""
        ...

    async def send(self, channel_id: str, message: OutboundMessage) -> None:
        """Send a single message to a channel."""
        ...

    async def send_streaming(
        self,
        channel_id: str,
        events: AsyncIterator[Any],
        reply_to: str | None = None,
    ) -> None:
        """Send a streaming response by editing a placeholder message."""
        ...

    async def health_check(self) -> HealthStatus:
        """Check if the adapter is connected and healthy."""
        ...
