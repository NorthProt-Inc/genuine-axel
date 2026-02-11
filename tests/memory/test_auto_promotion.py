"""W5-1: Test M2→M3 auto-promotion in session end."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_session_mixin(facts, insights, messages_count=4):
    """Build a minimal SessionMixin with mocked dependencies."""
    from backend.memory.unified.session import SessionMixin

    mixin = SessionMixin.__new__(SessionMixin)
    mixin.working = MagicMock()
    mixin.working.session_id = "sess-001"

    from backend.memory.current import TimestampedMessage
    from datetime import datetime, timezone

    msgs = []
    for i in range(messages_count):
        role = "user" if i % 2 == 0 else "assistant"
        m = TimestampedMessage(
            content=f"msg-{i}",
            role=role,
            timestamp=datetime.now(timezone.utc),
        )
        msgs.append(m)

    mixin.working.get_messages.return_value = msgs

    mixin.session_archive = MagicMock()
    mixin.long_term = MagicMock()
    mixin.long_term.add = MagicMock(return_value="new-id")

    mixin.event_buffer = MagicMock()
    mixin.event_buffer.push = MagicMock()
    mixin.event_buffer.clear = MagicMock()

    mixin.client = MagicMock()
    mixin.model_name = "test"

    summary = {
        "summary": "test summary",
        "key_topics": ["topic"],
        "emotional_tone": "neutral",
        "facts_discovered": facts,
        "insights_discovered": insights,
    }
    mixin._summarize_session = AsyncMock(return_value=summary)
    mixin._build_fallback_summary = MagicMock(return_value=summary)

    return mixin


@pytest.mark.asyncio
async def test_auto_promotion_high_importance():
    """Facts with importance >= 0.6 should trigger conversation promotion."""
    mixin = _make_session_mixin(facts=["important fact"], insights=[])

    with patch(
        "backend.memory.unified.session.calculate_importance_async",
        new_callable=AsyncMock,
        return_value=0.8,
    ):
        result = await mixin.end_session()

    assert result["status"] == "session_ended"
    # Should have fact store + conversation promotion store
    add_calls = mixin.long_term.add.call_args_list
    # At least one call should be for fact, at least one for conversation
    call_types = []
    for c in add_calls:
        if c.kwargs:
            call_types.append(c.kwargs.get("memory_type", ""))
        else:
            call_types.append(c[1].get("memory_type", "") if len(c) > 1 else "")

    assert "fact" in call_types, "fact should be stored"
    assert "conversation" in call_types, "conversation should be auto-promoted"


@pytest.mark.asyncio
async def test_no_promotion_low_importance():
    """Conversations with importance < 0.6 should NOT be auto-promoted."""
    mixin = _make_session_mixin(facts=["minor fact"], insights=[])

    with patch(
        "backend.memory.unified.session.calculate_importance_async",
        new_callable=AsyncMock,
        return_value=0.3,
    ):
        result = await mixin.end_session()

    assert result["status"] == "session_ended"
    # Only fact store, no conversation promotion
    add_calls = mixin.long_term.add.call_args_list
    call_types = []
    for c in add_calls:
        if c.kwargs:
            call_types.append(c.kwargs.get("memory_type", ""))

    assert "conversation" not in call_types, "low importance should not trigger promotion"


@pytest.mark.asyncio
async def test_promotion_includes_session_source():
    """Auto-promoted conversation should include source_session."""
    mixin = _make_session_mixin(facts=["a fact"], insights=[])

    with patch(
        "backend.memory.unified.session.calculate_importance_async",
        new_callable=AsyncMock,
        return_value=0.7,
    ):
        await mixin.end_session()

    add_calls = mixin.long_term.add.call_args_list
    conv_calls = [c for c in add_calls if c.kwargs.get("memory_type") == "conversation"]
    if conv_calls:
        assert conv_calls[0].kwargs.get("source_session") == "sess-001"


@pytest.mark.asyncio
async def test_no_promotion_empty_messages():
    """Empty sessions should not trigger promotion."""
    mixin = _make_session_mixin(facts=[], insights=[], messages_count=0)
    mixin.working.get_messages.return_value = []

    result = await mixin.end_session()
    assert result["status"] == "empty_session"
