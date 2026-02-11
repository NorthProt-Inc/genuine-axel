"""W1-1: Verify session.end_session() uses LLM importance for facts/insights."""

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

VANCOUVER_TZ = ZoneInfo("America/Vancouver")


def _make_manager_stub(facts: list[str], insights: list[str]):
    """Build a minimal SessionMixin-compatible stub with mocked components."""
    from backend.memory.unified.session import SessionMixin

    class Stub(SessionMixin):
        pass

    stub = Stub()
    stub.working = MagicMock()
    stub.working.session_id = "test-session"
    stub.working.get_messages.return_value = [
        MagicMock(
            content="hello",
            role="user",
            timestamp=datetime.now(VANCOUVER_TZ),
            get_relative_time=lambda: "0m",
            to_dict=lambda: {"role": "user", "content": "hello"},
        ),
    ]
    stub.working.reset_session = MagicMock()

    stub.session_archive = MagicMock()
    stub.long_term = MagicMock()
    stub.long_term.add = MagicMock(return_value="mem-id")
    stub.event_buffer = MagicMock()
    stub.client = MagicMock()
    stub.model_name = "test-model"

    summary = {
        "summary": "test summary",
        "key_topics": [],
        "emotional_tone": "neutral",
        "facts_discovered": facts,
        "insights_discovered": insights,
    }
    stub._summarize_session = AsyncMock(return_value=summary)
    stub._last_session_end = None

    return stub


class TestSessionLLMImportance:
    """Verify that end_session calls calculate_importance_async for facts/insights."""

    async def test_facts_use_llm_importance(self):
        stub = _make_manager_stub(facts=["User name is Alice"], insights=[])

        with patch(
            "backend.memory.unified.session.calculate_importance_async",
            new_callable=AsyncMock,
            return_value=0.92,
        ) as mock_calc:
            await stub.end_session()

        mock_calc.assert_called_once_with("User name is Alice", "", "")
        # First add call should be the fact (conversation promotion may follow)
        fact_call = stub.long_term.add.call_args_list[0]
        assert fact_call[1]["importance"] == 0.92
        assert fact_call[1]["memory_type"] == "fact"

    async def test_insights_use_llm_importance(self):
        stub = _make_manager_stub(facts=[], insights=["User prefers dark mode"])

        with patch(
            "backend.memory.unified.session.calculate_importance_async",
            new_callable=AsyncMock,
            return_value=0.68,
        ):
            await stub.end_session()

        # First add call should be the insight
        insight_call = stub.long_term.add.call_args_list[0]
        assert insight_call[1]["importance"] == 0.68
        assert insight_call[1]["memory_type"] == "insight"

    async def test_multiple_facts_each_get_importance(self):
        stub = _make_manager_stub(
            facts=["Fact A", "Fact B", "Fact C"],
            insights=[],
        )

        scores = iter([0.9, 0.5, 0.3])
        with patch(
            "backend.memory.unified.session.calculate_importance_async",
            new_callable=AsyncMock,
            side_effect=lambda *a, **kw: next(scores),
        ) as mock_calc:
            await stub.end_session()

        assert mock_calc.call_count == 3
        # First 3 calls should be facts (conversation promotion may follow)
        fact_calls = [
            c for c in stub.long_term.add.call_args_list
            if c[1]["memory_type"] == "fact"
        ]
        importances = [c[1]["importance"] for c in fact_calls]
        assert importances == [0.9, 0.5, 0.3]

    async def test_importance_fallback_on_error(self):
        """If LLM fails, calculate_importance_async returns 0.5 (neutral default)."""
        stub = _make_manager_stub(facts=["Some fact"], insights=[])

        with patch(
            "backend.memory.unified.session.calculate_importance_async",
            new_callable=AsyncMock,
            return_value=0.5,  # fallback value from importance.py
        ):
            await stub.end_session()

        # importance 0.5 < 0.6 threshold → no conversation promotion
        fact_call = stub.long_term.add.call_args_list[0]
        assert fact_call[1]["importance"] == 0.5

    async def test_empty_facts_no_importance_call(self):
        stub = _make_manager_stub(facts=[], insights=[])

        with patch(
            "backend.memory.unified.session.calculate_importance_async",
            new_callable=AsyncMock,
        ) as mock_calc:
            await stub.end_session()

        mock_calc.assert_not_called()
        stub.long_term.add.assert_not_called()
