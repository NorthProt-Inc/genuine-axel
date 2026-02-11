"""Discord bot adapter with streaming message editing.

Uses discord.py to connect to Discord, receive messages,
and stream responses by editing a placeholder message.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

import discord

from backend.channels.bridge import handle_channel_message
from backend.channels.message_chunker import chunk_for_discord
from backend.channels.protocol import (
    ChannelCapabilities,
    HealthStatus,
    InboundMessage,
    OutboundMessage,
    Platform,
)
from backend.core.chat_handler import ChatHandler, ChatEvent
from backend.core.services.react_service import EventType
from backend.core.logging import get_logger

_log = get_logger("channels.discord")

EDIT_THROTTLE_SECONDS = 1.0
THINKING_PLACEHOLDER = "💭 생각 중..."


class DiscordAdapter:
    """Discord channel adapter with streaming edit support."""

    def __init__(
        self,
        token: str,
        handler: ChatHandler,
        *,
        allowed_channel_ids: list[int] | None = None,
    ) -> None:
        self._token = token
        self._handler = handler
        self._allowed_channels = set(allowed_channel_ids) if allowed_channel_ids else None

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._setup_events()

    @property
    def platform(self) -> Platform:
        return Platform.DISCORD

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            streaming_edit=True,
            max_message_length=2000,
            typing_indicator=True,
            rich_media=True,
            threads=True,
            reactions=True,
        )

    def _setup_events(self) -> None:
        @self._client.event
        async def on_ready() -> None:
            _log.info(
                "DISCORD bot ready",
                user=str(self._client.user),
                guilds=len(self._client.guilds),
            )

        @self._client.event
        async def on_message(msg: discord.Message) -> None:
            if msg.author == self._client.user:
                return
            if msg.author.bot:
                return
            if self._allowed_channels and msg.channel.id not in self._allowed_channels:
                return

            # Respond to mentions or DMs
            is_dm = isinstance(msg.channel, discord.DMChannel)
            is_mentioned = self._client.user in msg.mentions if self._client.user else False
            if not is_dm and not is_mentioned:
                return

            content = msg.content
            if self._client.user:
                content = content.replace(f"<@{self._client.user.id}>", "").strip()

            if not content:
                return

            inbound = InboundMessage(
                user_id=str(msg.author.id),
                channel_id=str(msg.channel.id),
                content=content,
                platform=Platform.DISCORD,
                username=msg.author.display_name,
                thread_id=str(msg.thread.id) if hasattr(msg, "thread") and msg.thread else None,
                reply_to=str(msg.reference.message_id) if msg.reference else None,
                timestamp=msg.created_at.timestamp(),
                raw_event=msg,
            )

            asyncio.create_task(self._process_message(inbound, msg))

    async def _process_message(
        self, inbound: InboundMessage, original: discord.Message
    ) -> None:
        """Process inbound message with streaming edit."""
        placeholder: discord.Message | None = None
        buffer = ""
        last_edit = 0.0

        try:
            async with original.channel.typing():
                placeholder = await original.reply(THINKING_PLACEHOLDER)

                async for event in handle_channel_message(inbound, self._handler):
                    if event.type == EventType.TEXT:
                        buffer += event.content
                        now = time.monotonic()
                        if now - last_edit >= EDIT_THROTTLE_SECONDS and placeholder:
                            display = buffer[:1990] + "..." if len(buffer) > 1990 else buffer
                            try:
                                await placeholder.edit(content=display)
                                last_edit = now
                            except discord.HTTPException:
                                pass

                    elif event.type == EventType.DONE:
                        final_text = event.metadata.get("full_response", buffer)
                        if not final_text:
                            final_text = buffer or "응답을 생성하지 못했습니다."
                        break

            if not buffer and placeholder:
                final_text = buffer or "응답을 생성하지 못했습니다."

            # Final update — chunk if needed
            final_text = final_text if "final_text" in dir() else buffer
            chunks = chunk_for_discord(final_text)

            if placeholder and chunks:
                try:
                    await placeholder.edit(content=chunks[0])
                except discord.HTTPException:
                    pass
                for extra in chunks[1:]:
                    await original.channel.send(extra)

        except Exception:
            _log.exception("DISCORD message processing failed", user=inbound.user_id)
            if placeholder:
                try:
                    await placeholder.edit(content="⚠️ 오류가 발생했습니다.")
                except discord.HTTPException:
                    pass

    async def start(self) -> None:
        """Start the Discord bot (non-blocking)."""
        _log.info("DISCORD adapter starting")
        asyncio.create_task(self._client.start(self._token))

    async def stop(self) -> None:
        """Gracefully close the Discord connection."""
        _log.info("DISCORD adapter stopping")
        await self._client.close()

    async def send(self, channel_id: str, message: OutboundMessage) -> None:
        """Send a message to a Discord channel."""
        channel = self._client.get_channel(int(channel_id))
        if not channel or not isinstance(channel, discord.abc.Messageable):
            _log.warning("DISCORD channel not found", channel_id=channel_id)
            return

        chunks = chunk_for_discord(message.content)
        for chunk in chunks:
            await channel.send(chunk)

    async def send_streaming(
        self,
        channel_id: str,
        events: AsyncIterator[Any],
        reply_to: str | None = None,
    ) -> None:
        """Send streaming response with message editing."""
        channel = self._client.get_channel(int(channel_id))
        if not channel or not isinstance(channel, discord.abc.Messageable):
            return

        placeholder = await channel.send(THINKING_PLACEHOLDER)
        buffer = ""
        last_edit = 0.0

        async for event in events:
            if isinstance(event, ChatEvent) and event.type == EventType.TEXT:
                buffer += event.content
                now = time.monotonic()
                if now - last_edit >= EDIT_THROTTLE_SECONDS:
                    display = buffer[:1990] + "..." if len(buffer) > 1990 else buffer
                    try:
                        await placeholder.edit(content=display)
                        last_edit = now
                    except discord.HTTPException:
                        pass

        chunks = chunk_for_discord(buffer)
        if chunks:
            await placeholder.edit(content=chunks[0])
            for extra in chunks[1:]:
                await channel.send(extra)

    async def health_check(self) -> HealthStatus:
        """Check Discord connection health."""
        connected = self._client.is_ready()
        return HealthStatus(
            healthy=connected,
            platform=Platform.DISCORD,
            details=f"guilds={len(self._client.guilds)}" if connected else "disconnected",
        )
