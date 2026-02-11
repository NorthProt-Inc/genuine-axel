"""Tests for T-06: Hybrid Entity Extraction (NER + LLM Decision Gate)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.memory.graph_rag import GraphRAG, KnowledgeGraph, Entity, _HAS_SPACY


@pytest.fixture
def mock_graph(tmp_path):
    """KnowledgeGraph with temp persist path."""
    return KnowledgeGraph(persist_path=str(tmp_path / "test_kg.json"))


@pytest.fixture
def mock_client():
    """Mock Gemini client for LLM calls."""
    client = MagicMock()
    response = MagicMock()
    response.text = json.dumps({
        "entities": [
            {"name": "Mark", "type": "person", "importance": 0.9},
            {"name": "Python", "type": "tool", "importance": 0.8},
        ],
        "relations": [
            {"source": "Mark", "target": "Python", "relation": "uses"},
        ],
    })
    client.aio.models.generate_content = AsyncMock(return_value=response)
    return client


class TestShortTextNerOnly:

    @pytest.mark.asyncio
    async def test_short_text_ner_only(self, mock_graph, mock_client):
        """Short text with mocked NER → LLM NOT called."""
        rag = GraphRAG(client=mock_client, model_name="test", graph=mock_graph)

        # Mock _extract_ner to return high-confidence NER results
        ner_entities = [
            {"name": "Alice", "type": "person", "importance": 0.8, "confidence": 0.9},
            {"name": "Vancouver", "type": "concept", "importance": 0.7, "confidence": 0.85},
        ]
        rag._extract_ner = MagicMock(return_value=(ner_entities, 0.875))

        # Short text (< 200 chars)
        result = await rag.extract_and_store("Alice lives in Vancouver", source="test")

        # LLM should NOT be called
        mock_client.aio.models.generate_content.assert_not_called()
        assert result["extraction_mode"] == "ner_only"
        assert result["entities_added"] >= 1


class TestLongTextUsesLlm:

    @pytest.mark.asyncio
    async def test_long_text_uses_llm(self, mock_graph, mock_client):
        """Long text (>= 200 chars) → LLM is called."""
        rag = GraphRAG(client=mock_client, model_name="test", graph=mock_graph)

        # Mock _extract_ner to return some entities
        rag._extract_ner = MagicMock(return_value=(
            [{"name": "Mark", "type": "person", "importance": 0.8, "confidence": 0.9}],
            0.9,
        ))

        long_text = "Mark is a software developer who lives in Vancouver. " * 10  # > 200 chars
        result = await rag.extract_and_store(long_text, source="test")

        # LLM should be called for long text
        mock_client.aio.models.generate_content.assert_called_once()
        assert result["entities_added"] >= 1


class TestNerLlmMerge:

    def test_merge_llm_overrides_ner(self):
        """LLM entities override NER on name match (case-insensitive)."""
        rag = GraphRAG(client=MagicMock(), model_name="test")

        ner = [
            {"name": "Python", "type": "concept", "importance": 0.7},
            {"name": "Alice", "type": "person", "importance": 0.6},
        ]
        llm = [
            {"name": "Python", "type": "tool", "importance": 0.9},  # Override
            {"name": "FastAPI", "type": "tool", "importance": 0.8},
        ]

        merged = rag._merge_ner_llm(ner, llm)

        names = {e["name"] for e in merged}
        assert "Python" in names
        assert "Alice" in names
        assert "FastAPI" in names
        assert len(merged) == 3  # Python (LLM), FastAPI (LLM), Alice (NER)

        # Python should have LLM type, not NER type
        python_e = next(e for e in merged if e["name"] == "Python")
        assert python_e["type"] == "tool"


class TestSpacyUnavailableFallback:

    @pytest.mark.asyncio
    async def test_spacy_unavailable_uses_llm_only(self, mock_graph, mock_client):
        """When spaCy is not available, extraction falls through to LLM-only."""
        rag = GraphRAG(client=mock_client, model_name="test", graph=mock_graph)

        # Mock _extract_ner to return empty (simulates spaCy unavailable)
        rag._extract_ner = MagicMock(return_value=([], 0.0))

        result = await rag.extract_and_store("Some text about Mark", source="test")

        # LLM should be called since no NER entities
        mock_client.aio.models.generate_content.assert_called_once()
        assert result["entities_added"] >= 1
