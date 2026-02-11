"""W4-1: Verify GraphRAG async query uses LLM relevance evaluation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.memory.graph_rag.core import GraphRAG
from backend.memory.graph_rag.knowledge_graph import KnowledgeGraph, Entity


def _make_graphrag(relevance_response: str = "0.85") -> GraphRAG:
    """Build GraphRAG with mocked client."""
    client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = relevance_response

    # Entity extraction returns entity names
    entity_response = MagicMock()
    entity_response.text = '["Python"]'

    # Chain responses: first call = entity extraction, second = relevance eval
    client.aio.models.generate_content = AsyncMock(
        side_effect=[entity_response, mock_response]
    )

    graph = KnowledgeGraph()
    entity = Entity(
        id="e1", name="Python", entity_type="language", properties={}
    )
    graph.add_entity(entity)

    return GraphRAG(client=client, model_name="test-model", graph=graph)


class TestGraphRAGLLMScore:

    async def test_llm_relevance_score_returned(self):
        grag = _make_graphrag(relevance_response="0.85")
        result = await grag.query("What is Python?")
        assert result.relevance_score == 0.85

    async def test_fallback_on_llm_error(self):
        client = MagicMock()
        entity_response = MagicMock()
        entity_response.text = '["Python"]'

        # First call succeeds (entity extraction), second fails (relevance eval)
        client.aio.models.generate_content = AsyncMock(
            side_effect=[entity_response, RuntimeError("API error")]
        )

        graph = KnowledgeGraph()
        graph.add_entity(Entity(id="e1", name="Python", entity_type="language", properties={}))
        grag = GraphRAG(client=client, model_name="test-model", graph=graph)

        result = await grag.query("What is Python?")
        # Fallback = min(len(entities) * 0.2, 1.0) — entities include neighbors
        assert 0.0 < result.relevance_score <= 1.0

    async def test_no_client_returns_zero(self):
        grag = GraphRAG(client=None, model_name="test")
        result = await grag.query("test")
        assert result.relevance_score == 0.0

    async def test_sync_query_unchanged(self):
        """query_sync should still use arithmetic score (no LLM)."""
        graph = KnowledgeGraph()
        graph.add_entity(Entity(id="e1", name="test", entity_type="concept", properties={}))
        grag = GraphRAG(client=MagicMock(), model_name="test", graph=graph)

        result = grag.query_sync("test query")
        # Arithmetic: min(len(entities) * 0.2, 1.0) — no LLM call
        assert 0.0 < result.relevance_score <= 1.0
