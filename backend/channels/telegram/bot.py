"""Telegram bot adapter with streaming message editing.

Uses python-telegram-bot to connect to Telegram, receive messages,
and stream responses by editing a placeholder message.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, MessageHandler as TGMessageHandler, filters, ContextTypes
from telegram.error import BadRequest, RetryAfter, TimedOut

from backend.channels.bridge import handle_channel_message
from backend.channels.message_chunker import chunk_for_telegram
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

_log = get_logger("channels.telegram")

EDIT_THROTTLE_SECONDS = 1.5
THINKING_PLACEHOLDER = "💭 생각 중..."


class TelegramAdapter:
    """Telegram channel adapter with streaming edit support."""

    def __init__(
        self,
        token: str,
        handler: ChatHandler,
        *,
        allowed_chat_ids: list[int] | None = None,
        allowed_usernames: list[str] | None = None,
    ) -> None:
        self._token = token
        self._handler = handler
        self._allowed_chats = set(allowed_chat_ids) if allowed_chat_ids else None
        self._allowed_users = (
            {u.lower() for u in allowed_usernames} if allowed_usernames else None
        )

        self._app = Application.builder().token(token).build()
        self._setup_handlers()

    @property
    def platform(self) -> Platform:
        return Platform.TELEGRAM

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            streaming_edit=True,
            max_message_length=4096,
            typing_indicator=True,
            rich_media=True,
            threads=False,
            reactions=True,
        )

    def _setup_handlers(self) -> None:
        self._app.add_handler(
            TGMessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

    def _is_allowed(self, update: Update) -> bool:
        """Check if the message sender is allowed."""
        if not update.effective_user:
            return False

        if self._allowed_users:
            username = (update.effective_user.username or "").lower()
            if username not in self._allowed_users:
                return False

        if self._allowed_chats and update.effective_chat:
            if update.effective_chat.id not in self._allowed_chats:
                # In groups, check for mentions
                if update.effective_chat.type in ("group", "supergroup"):
                    return self._is_mentioned(update)
                return False

        return True

    def _is_mentioned(self, update: Update) -> bool:
        """Check if bot is mentioned in a group message."""
        if not update.message or not update.message.text:
            return False
        bot_username = self._app.bot.username
        if bot_username and f"@{bot_username}" in update.message.text:
            return True
        return False

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming Telegram messages."""
        if not update.message or not update.message.text:
            return
        if not update.effective_user or not update.effective_chat:
            return
        if not self._is_allowed(update):
            return

        content = update.message.text
        bot_username = self._app.bot.username
        if bot_username:
            content = content.replace(f"@{bot_username}", "").strip()

        if not content:
            return

        inbound = InboundMessage(
            user_id=str(update.effective_user.id),
            channel_id=str(update.effective_chat.id),
            content=content,
            platform=Platform.TELEGRAM,
            username=update.effective_user.first_name or "",
            reply_to=(
                str(update.message.reply_to_message.message_id)
                if update.message.reply_to_message
                else None
            ),
            timestamp=update.message.date.timestamp() if update.message.date else 0.0,
            raw_event=update,
        )

        asyncio.create_task(self._process_message(inbound, update, context))

    async def _process_message(
        self,
        inbound: InboundMessage,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Process inbound message with streaming edit."""
        chat_id = int(inbound.channel_id)
        placeholder_id: int | None = None
        buffer = ""
        last_edit = 0.0

        try:
            # Send typing indicator
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

            # Send placeholder
            placeholder_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=THINKING_PLACEHOLDER,
                reply_to_message_id=(
                    update.message.message_id if update.message else None
                ),
            )
            placeholder_id = placeholder_msg.message_id

            # Typing heartbeat task
            heartbeat_running = True

            async def _typing_heartbeat() -> None:
                while heartbeat_running:
                    try:
                        await context.bot.send_chat_action(
                            chat_id=chat_id, action=ChatAction.TYPING
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(4.0)

            heartbeat_task = asyncio.create_task(_typing_heartbeat())

            final_text = ""
            try:
                async for event in handle_channel_message(inbound, self._handler):
                    if event.type == EventType.TEXT:
                        buffer += event.content
                        now = time.monotonic()
                        if now - last_edit >= EDIT_THROTTLE_SECONDS and placeholder_id:
                            display = (
                                buffer[:4090] + "..." if len(buffer) > 4090 else buffer
                            )
                            await self._safe_edit(
                                context.bot, chat_id, placeholder_id, display
                            )
                            last_edit = now

                    elif event.type == EventType.DONE:
                        final_text = event.metadata.get("full_response", buffer)
                        break
            finally:
                heartbeat_running = False
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            if not final_text:
                final_text = buffer or "응답을 생성하지 못했습니다."

            # Final update with chunking
            chunks = chunk_for_telegram(final_text)
            if placeholder_id and chunks:
                await self._safe_edit(context.bot, chat_id, placeholder_id, chunks[0])
                for extra in chunks[1:]:
                    await context.bot.send_message(chat_id=chat_id, text=extra)

        except Exception:
            _log.exception("TELEGRAM message processing failed", user=inbound.user_id)
            if placeholder_id:
                await self._safe_edit(
                    context.bot, chat_id, placeholder_id, "⚠️ 오류가 발생했습니다."
                )

    async def _safe_edit(
        self, bot: Any, chat_id: int, message_id: int, text: str
    ) -> None:
        """Edit a message with retry on rate limit."""
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text
            )
        except BadRequest as e:
            if "message is not modified" not in str(e).lower():
                _log.warning("TELEGRAM edit failed", error=str(e))
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text
                )
            except Exception:
                pass
        except TimedOut:
            pass

    async def start(self) -> None:
        """Start the Telegram bot (polling mode)."""
        _log.info("TELEGRAM adapter starting")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        """Gracefully stop the Telegram bot."""
        _log.info("TELEGRAM adapter stopping")
        if self._app.updater and self._app.updater.running:
            await self._app.updater.stop()
        if self._app.running:
            await self._app.stop()
        await self._app.shutdown()

    async def send(self, channel_id: str, message: OutboundMessage) -> None:
        """Send a message to a Telegram chat."""
        chunks = chunk_for_telegram(message.content)
        for chunk in chunks:
            await self._app.bot.send_message(chat_id=int(channel_id), text=chunk)

    async def send_streaming(
        self,
        channel_id: str,
        events: AsyncIterator[Any],
        reply_to: str | None = None,
    ) -> None:
        """Send streaming response with message editing."""
        chat_id = int(channel_id)
        placeholder = await self._app.bot.send_message(
            chat_id=chat_id,
            text=THINKING_PLACEHOLDER,
            reply_to_message_id=int(reply_to) if reply_to else None,
        )
        buffer = ""
        last_edit = 0.0

        async for event in events:
            if isinstance(event, ChatEvent) and event.type == EventType.TEXT:
                buffer += event.content
                now = time.monotonic()
                if now - last_edit >= EDIT_THROTTLE_SECONDS:
                    display = buffer[:4090] + "..." if len(buffer) > 4090 else buffer
                    await self._safe_edit(self._app.bot, chat_id, placeholder.message_id, display)
                    last_edit = now

        chunks = chunk_for_telegram(buffer)
        if chunks:
            await self._safe_edit(self._app.bot, chat_id, placeholder.message_id, chunks[0])
            for extra in chunks[1:]:
                await self._app.bot.send_message(chat_id=chat_id, text=extra)

    async def health_check(self) -> HealthStatus:
        """Check Telegram bot connection health."""
        try:
            me = await self._app.bot.get_me()
            return HealthStatus(
                healthy=True,
                platform=Platform.TELEGRAM,
                details=f"bot=@{me.username}",
            )
        except Exception as e:
            return HealthStatus(
                healthy=False,
                platform=Platform.TELEGRAM,
                details=str(e),
            )
