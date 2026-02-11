"""Tests for T-01: Parallel Context Assembly + Fault Isolation."""

import asyncio
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from backend.memory.unified import MemoryManager


def _make_manager(
    *,
    memgpt_result=None,
    session_result=None,
    graph_result=None,
    memgpt_exc=None,
    session_exc=None,
    graph_exc=None,
):
    """Build MemoryManager with mocked dependencies."""
    with patch.object(MemoryManager, "__init__", lambda self, **kw: None):
        mgr = MemoryManager()

    # Working memory mock
    mgr.working = MagicMock()
    mgr.working.get_progressive_context.return_value = "recent chat"
    mgr.working.get_turn_count.return_value = 3
    mgr.working.get_time_elapsed_context.return_value = None
    mgr.working.session_id = "test-session"

    # Session archive mock
    mgr.session_archive = MagicMock()
    if session_exc:
        mgr.session_archive.get_recent_summaries.side_effect = session_exc
    else:
        mgr.session_archive.get_recent_summaries.return_value = session_result
    mgr.session_archive.get_time_since_last_session.return_value = None

    # MemGPT mock
    mgr.memgpt = MagicMock()
    if memgpt_exc:
        mgr.memgpt.context_budget_select.side_effect = memgpt_exc
    else:
        mgr.memgpt.context_budget_select.return_value = memgpt_result or ([], 0)

    # Graph RAG mock
    graph_query_result = MagicMock()
    graph_query_result.context = graph_result
    mgr.graph_rag = MagicMock()
    if graph_exc:
        mgr.graph_rag.query_sync.side_effect = graph_exc
    else:
        mgr.graph_rag.query_sync.return_value = graph_query_result

    # Config
    mgr.MAX_CONTEXT_TOKENS = 32000
    mgr.LONG_TERM_BUDGET = 2000
    mgr.SESSION_ARCHIVE_BUDGET = 1000
    mgr.TIME_CONTEXT_BUDGET = 200

    # M0/M5: Event buffer and meta memory
    from backend.memory.event_buffer import EventBuffer
    from backend.memory.meta_memory import MetaMemory
    mgr.event_buffer = EventBuffer()
    mgr.meta_memory = MetaMemory()

    # Write lock / semaphore
    import threading
    mgr._write_lock = threading.Lock()
    mgr._read_semaphore = threading.Semaphore(5)

    return mgr


def _make_scored_memory(id_, content, score):
    from backend.memory.memgpt import ScoredMemory
    return ScoredMemory(id=id_, content=content, score=score, token_estimate=len(content) // 4)


class TestParallelAllSucceed:

    @pytest.mark.asyncio
    async def test_parallel_all_succeed(self):
        """All 3 sources return data → all sections present in context."""
        mems = [_make_scored_memory("m1", "Alice is a developer", 0.9)]
        mgr = _make_manager(
            memgpt_result=(mems, 50),
            session_result="Session from yesterday about Python",
            graph_result="Mark --[uses]--> Python",
        )

        result = await mgr.build_smart_context("What does Alice do?")

        assert "관련 장기 기억" in result
        assert "최근 세션 기록" in result
        assert "관계 기반 지식" in result


class TestParallelOneSourceFails:

    @pytest.mark.asyncio
    async def test_parallel_one_source_fails(self):
        """One source raises exception → other 2 sources still present."""
        mems = [_make_scored_memory("m1", "Alice likes Python", 0.8)]
        mgr = _make_manager(
            memgpt_result=(mems, 30),
            session_exc=RuntimeError("DB connection error"),
            graph_result="Mark --[knows]--> Alice",
        )

        result = await mgr.build_smart_context("Tell me about Alice")

        assert "관련 장기 기억" in result
        assert "관계 기반 지식" in result
        # Session archive failed — should not appear
        assert "최근 세션 기록" not in result


class TestParallelAllFail:

    @pytest.mark.asyncio
    async def test_parallel_all_fail(self):
        """All sources fail → only time context + working context remain."""
        mgr = _make_manager(
            memgpt_exc=RuntimeError("ChromaDB down"),
            session_exc=RuntimeError("SQLite locked"),
            graph_exc=RuntimeError("Graph corrupt"),
        )

        result = await mgr.build_smart_context("anything")

        # Working context should still be present
        assert "현재 대화" in result
        # None of the failed sections should appear
        assert "관련 장기 기억" not in result
        assert "최근 세션 기록" not in result
        assert "관계 기반 지식" not in result


class TestSyncFallbackInRunningLoop:

    @pytest.mark.asyncio
    async def test_sync_fallback_in_running_loop(self):
        """build_smart_context_sync uses sync version inside running loop."""
        mgr = _make_manager(
            memgpt_result=([], 0),
            session_result=None,
            graph_result=None,
        )

        # Call build_smart_context_sync inside an async function (running loop exists)
        result = mgr.build_smart_context_sync("test query")

        # Should still produce valid output (uses sync path)
        assert isinstance(result, str)
        # Verify sync method was actually used (memgpt called directly, not via to_thread)
        mgr.memgpt.context_budget_select.assert_called_once()
