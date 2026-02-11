"""Tests for entity/relation migration from axel PostgreSQL."""

import pytest
from backend.memory.graph_rag import KnowledgeGraph, Entity, Relation


@pytest.fixture
def graph(tmp_path):
    return KnowledgeGraph(persist_path=str(tmp_path / "test_kg.json"))


class TestEntityMigration:

    def test_entity_dedup_on_import(self, graph):
        """Same-name entity import should merge mentions."""
        e1 = Entity(
            id="mark_1",
            name="Mark",
            entity_type="person",
            mentions=5,
        )
        e2 = Entity(
            id="mark_2",
            name="mark",
            entity_type="person",
            mentions=3,
        )
        graph.add_entity(e1)
        graph.add_entity(e2)

        # Should be deduplicated - only one entity
        mark_entities = graph.find_entities_by_name("mark")
        assert len(mark_entities) == 1
        assert mark_entities[0].mentions >= 6  # at least sum of both

    def test_relation_weight_preserved(self, graph):
        """Axel relation weights should be preserved after import."""
        e1 = Entity(id="src", name="Source", entity_type="concept")
        e2 = Entity(id="tgt", name="Target", entity_type="concept")
        graph.add_entity(e1)
        graph.add_entity(e2)

        r = Relation(
            source_id="src",
            target_id="tgt",
            relation_type="uses",
            weight=0.85,
            context="test context",
        )
        graph.add_relation(r)

        stored_rel = graph.relations.get(r.id)
        assert stored_rel is not None
        assert stored_rel.weight == 0.85
        assert stored_rel.context == "test context"

    def test_empty_db_no_error(self, graph):
        """Empty entity/relation lists should not cause errors."""
        entities = []
        relations = []

        for e in entities:
            graph.add_entity(e)
        for r in relations:
            graph.add_relation(r)

        assert len(graph.entities) == 0
        assert len(graph.relations) == 0
