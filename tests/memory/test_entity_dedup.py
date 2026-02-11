"""Tests for entity deduplication and normalization."""

import pytest
from backend.memory.graph_rag import KnowledgeGraph, Entity


@pytest.fixture
def graph(tmp_path):
    return KnowledgeGraph(persist_path=str(tmp_path / "test_kg.json"))


class TestEntityDedup:

    def test_normalize_whitespace(self, graph):
        result = graph._normalize_entity_name("  John   Doe  ")
        assert result == "John Doe"

    def test_dedup_same_name_different_case(self, graph):
        e1 = Entity(id="john_1", name="John", entity_type="person")
        e2 = Entity(id="john_2", name="john", entity_type="person")
        graph.add_entity(e1)
        result_id = graph.add_entity(e2)
        assert result_id == "john_1"
        assert len(graph.entities) == 1
        assert graph.entities["john_1"].mentions == 2

    def test_dedup_prefers_specific_type(self, graph):
        e1 = Entity(id="python_1", name="Python", entity_type="concept")
        e2 = Entity(id="python_2", name="python", entity_type="tool")
        graph.add_entity(e1)
        graph.add_entity(e2)
        assert graph.entities["python_1"].entity_type == "tool"

    def test_stopword_filtered(self, graph):
        e = Entity(id="the_1", name="the", entity_type="concept")
        result = graph.add_entity(e)
        assert result == ""
        assert "the_1" not in graph.entities

    def test_non_concept_stopword_not_filtered(self, graph):
        e = Entity(id="is_1", name="is", entity_type="person")
        result = graph.add_entity(e)
        assert result != ""
