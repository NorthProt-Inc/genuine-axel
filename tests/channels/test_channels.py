"""Tests for channel protocol, manager, message chunker, command registry, and bridge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.channels.protocol import (
    ChannelCapabilities,
    HealthStatus,
    InboundMessage,
    OutboundMessage,
    Platform,
)
from backend.channels.manager import ChannelManager
from backend.channels.message_chunker import (
    chunk_for_discord,
    chunk_for_telegram,
    chunk_message,
)
from backend.channels.commands.registry import parse_message


# ── Protocol tests ──────────────────────────────────────────


class TestProtocol:
    def test_inbound_message_creation(self) -> None:
        msg = InboundMessage(
            user_id="u1",
            channel_id="c1",
            content="hello",
            platform=Platform.DISCORD,
        )
        assert msg.user_id == "u1"
        assert msg.platform == Platform.DISCORD
        assert msg.thread_id is None

    def test_outbound_message_defaults(self) -> None:
        msg = OutboundMessage(content="hi")
        assert msg.format == "markdown"
        assert msg.reply_to is None

    def test_platform_values(self) -> None:
        assert Platform.DISCORD.value == "discord"
        assert Platform.TELEGRAM.value == "telegram"


# ── Message chunker tests ───────────────────────────────────


class TestMessageChunker:
    def test_short_message_no_split(self) -> None:
        result = chunk_message("short", 2000)
        assert result == ["short"]

    def test_exact_limit(self) -> None:
        text = "a" * 2000
        result = chunk_message(text, 2000)
        assert result == [text]

    def test_long_message_split(self) -> None:
        text = "word " * 1000  # 5000 chars
        result = chunk_for_discord(text)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 2000

    def test_paragraph_split_forced(self) -> None:
        text = "A" * 1500 + "\n\n" + "B" * 1500
        result = chunk_message(text, 2000)
        assert len(result) == 2

    def test_telegram_limit(self) -> None:
        text = "x" * 8000
        result = chunk_for_telegram(text)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 4096

    def test_code_block_preserved(self) -> None:
        code = "```python\n" + "x = 1\n" * 100 + "```"
        text = "Before\n\n" + code
        result = chunk_message(text, 2000)
        has_complete = any("```python" in c and c.count("```") == 2 for c in result)
        assert has_complete


# ── Command registry tests ──────────────────────────────────


class TestCommandRegistry:
    def test_no_directives(self) -> None:
        result = parse_message("hello world")
        assert result.content == "hello world"
        assert result.model is None
        assert result.enable_search is False

    def test_model_directive(self) -> None:
        result = parse_message("/model:claude explain quantum computing")
        assert result.model == "anthropic"
        assert result.content == "explain quantum computing"

    def test_search_directive(self) -> None:
        result = parse_message("/search latest news")
        assert result.enable_search is True
        assert result.content == "latest news"

    def test_tier_directive(self) -> None:
        result = parse_message("/tier:pro analyze this")
        assert result.tier == "pro"
        assert result.content == "analyze this"

    def test_multiple_directives(self) -> None:
        result = parse_message("/model:gemini /search what is AI")
        assert result.model == "gemini"
        assert result.enable_search is True
        assert result.content == "what is AI"

    def test_unknown_model_alias(self) -> None:
        result = parse_message("/model:llama test")
        assert result.model == "llama"


# ── ChannelManager tests ────────────────────────────────────


def _make_mock_adapter(platform: Platform) -> MagicMock:
    adapter = MagicMock()
    adapter.platform = platform
    adapter.capabilities = ChannelCapabilities()
    adapter.start = AsyncMock()
    adapter.stop = AsyncMock()
    adapter.send = AsyncMock()
    adapter.health_check = AsyncMock(
        return_value=HealthStatus(healthy=True, platform=platform)
    )
    return adapter


class TestChannelManager:
    @pytest.fixture
    def manager(self) -> ChannelManager:
        return ChannelManager()

    def test_register(self, manager: ChannelManager) -> None:
        adapter = _make_mock_adapter(Platform.DISCORD)
        manager.register(adapter)
        assert Platform.DISCORD in manager.registered_platforms

    async def test_start_all(self, manager: ChannelManager) -> None:
        dc = _make_mock_adapter(Platform.DISCORD)
        tg = _make_mock_adapter(Platform.TELEGRAM)
        manager.register(dc)
        manager.register(tg)
        await manager.start_all()
        dc.start.assert_awaited_once()
        tg.start.assert_awaited_once()
        assert manager.is_running

    async def test_stop_all(self, manager: ChannelManager) -> None:
        dc = _make_mock_adapter(Platform.DISCORD)
        manager.register(dc)
        await manager.start_all()
        await manager.stop_all()
        dc.stop.assert_awaited_once()
        assert not manager.is_running

    async def test_health_check_all(self, manager: ChannelManager) -> None:
        dc = _make_mock_adapter(Platform.DISCORD)
        manager.register(dc)
        results = await manager.health_check_all()
        assert "discord" in results
        assert results["discord"].healthy

    def test_no_adapters_registered(self, manager: ChannelManager) -> None:
        assert manager.registered_platforms == []

    async def test_start_empty(self, manager: ChannelManager) -> None:
        await manager.start_all()
        assert not manager.is_running
