"""Tests for session summary generation."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo
from backend.memory.current import TimestampedMessage


VANCOUVER_TZ = ZoneInfo("America/Vancouver")


def _make_message(role: str, content: str) -> TimestampedMessage:
    return TimestampedMessage(
        role=role,
        content=content,
        timestamp=datetime.now(VANCOUVER_TZ),
        emotional_context="neutral",
    )


class TestSessionSummary:

    def test_summary_prompt_includes_topics(self):
        from backend.memory.unified import SESSION_SUMMARY_PROMPT
        assert "key_topics" in SESSION_SUMMARY_PROMPT
        assert "emotional_tone" in SESSION_SUMMARY_PROMPT

    def test_fallback_summary_structure(self):
        from backend.memory.unified import MemoryManager

        manager = MagicMock(spec=MemoryManager)

        messages = [
            _make_message("user", "How do I use Python asyncio?"),
            _make_message("assistant", "You can use async/await syntax."),
        ]

        result = MemoryManager._build_fallback_summary(manager, messages)
        assert "summary" in result
        assert "key_topics" in result
        assert "emotional_tone" in result
        assert isinstance(result["key_topics"], list)

    def test_emotional_tone_in_fallback(self):
        from backend.memory.unified import MemoryManager

        manager = MagicMock(spec=MemoryManager)
        messages = [_make_message("user", "hello")]
        result = MemoryManager._build_fallback_summary(manager, messages)
        assert result["emotional_tone"] == "neutral"
