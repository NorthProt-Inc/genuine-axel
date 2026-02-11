"""W3-1/W3-2: Cross-layer M3↔M4 search enrichment tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass, field
from typing import List

from backend.memory.event_buffer import EventBuffer
from backend.memory.meta_memory import MetaMemory


@dataclass
class MockEntity:
    name: str


@dataclass
class MockGraphResult:
    context: str = ""
    entities: List[MockEntity] = field(default_factory=list)


class TestCrossLayerSearch:
    """Verify GraphRAG entities enrich M3 queries."""

    def _make_mixin(self, *, graph_result=None):
        """Create minimal ContextBuilderMixin with controllable graph_rag."""
        from backend.memory.unified.context_builder import ContextBuilderMixin

        mixin = object.__new__(ContextBuilderMixin)

        mixin.working = MagicMock()
        mixin.working.get_progressive_context.return_value = ""
        mixin.working.get_turn_count.return_value = 0
        mixin.working.get_time_elapsed_context.return_value = ""
        mixin.working.session_id = "test-session"

        mixin.session_archive = MagicMock()
        mixin.session_archive.get_time_since_last_session.return_value = None
        mixin.session_archive.get_recent_summaries.return_value = ""

        mixin.memgpt = MagicMock()
        mixin.memgpt.context_budget_select.return_value = ([], 0)
        mixin.LONG_TERM_BUDGET = 1000
        mixin.SESSION_ARCHIVE_BUDGET = 500
        mixin.MAX_CONTEXT_TOKENS = 4000

        # GraphRAG mock
        mixin.graph_rag = MagicMock()
        if graph_result is not None:
            mixin.graph_rag.query_sync.return_value = graph_result
        else:
            mixin.graph_rag = None

        mixin.event_buffer = EventBuffer()
        mixin.meta_memory = MetaMemory()

        return mixin

    @pytest.mark.asyncio
    async def test_enriched_query_includes_entity_names(self):
        """When GraphRAG returns entities, M3 query should be enriched."""
        gr = MockGraphResult(
            context="Python is a language",
            entities=[MockEntity("Python"), MockEntity("FastAPI")],
        )
        mixin = self._make_mixin(graph_result=gr)

        await mixin._build_smart_context_async("what is")

        # Verify M3 was called with enriched query
        call_args = mixin.memgpt.context_budget_select.call_args
        enriched_query = call_args[0][0]  # First positional arg
        assert "Python" in enriched_query
        assert "FastAPI" in enriched_query
        assert "what is" in enriched_query

    @pytest.mark.asyncio
    async def test_no_entities_uses_original_query(self):
        """When GraphRAG has no entities, M3 uses original query."""
        gr = MockGraphResult(context="some context", entities=[])
        mixin = self._make_mixin(graph_result=gr)

        await mixin._build_smart_context_async("test query")

        call_args = mixin.memgpt.context_budget_select.call_args
        query = call_args[0][0]
        assert query == "test query"

    @pytest.mark.asyncio
    async def test_no_graph_rag_uses_original_query(self):
        """Without GraphRAG, M3 uses original query unchanged."""
        mixin = self._make_mixin(graph_result=None)

        await mixin._build_smart_context_async("test query")

        call_args = mixin.memgpt.context_budget_select.call_args
        query = call_args[0][0]
        assert query == "test query"

    @pytest.mark.asyncio
    async def test_max_three_entities_enriched(self):
        """Only first 3 entities should be used for enrichment."""
        entities = [MockEntity(f"Entity{i}") for i in range(5)]
        gr = MockGraphResult(context="ctx", entities=entities)
        mixin = self._make_mixin(graph_result=gr)

        await mixin._build_smart_context_async("q")

        call_args = mixin.memgpt.context_budget_select.call_args
        query = call_args[0][0]
        assert "Entity0" in query
        assert "Entity2" in query
        assert "Entity3" not in query
