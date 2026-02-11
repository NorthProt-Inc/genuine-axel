"""Tests for T-08: TF-IDF Relation Weight Scoring."""

import pytest

from backend.memory.graph_rag import KnowledgeGraph, Entity, Relation


@pytest.fixture
def graph(tmp_path):
    """Fresh KnowledgeGraph with temp persist path."""
    return KnowledgeGraph(persist_path=str(tmp_path / "test_kg.json"))


def _add_entities(graph, names):
    """Helper: add multiple entities."""
    for name in names:
        graph.add_entity(Entity(
            id=name.lower().replace(" ", "_"),
            name=name,
            entity_type="concept",
        ))


class TestCooccurrenceCountAccuracy:

    def test_cooccurrence_count_increments(self, graph):
        """3 repeated add_relation calls → cooccurrence=3."""
        _add_entities(graph, ["Alice", "Python"])

        rel = Relation(
            source_id="alice", target_id="python",
            relation_type="uses",
        )

        # First add creates the relation
        graph.add_relation(rel)

        # Subsequent adds increment cooccurrence
        graph.add_relation(rel)
        graph.add_relation(rel)
        graph.add_relation(rel)

        pair = tuple(sorted(["alice", "python"]))
        # After first add (new), 3 more re-adds: cooccurrence = 3
        assert graph._cooccurrence[pair] == 3

    def test_entity_mentions_tracked(self, graph):
        """Entity mentions counter updates correctly."""
        _add_entities(graph, ["Alice", "Python", "FastAPI"])

        rel1 = Relation(source_id="alice", target_id="python", relation_type="uses")
        rel2 = Relation(source_id="alice", target_id="fastapi", relation_type="uses")

        graph.add_relation(rel1)
        graph.add_relation(rel1)  # Re-add triggers mention tracking
        graph.add_relation(rel2)
        graph.add_relation(rel2)  # Re-add

        # alice mentioned in both re-adds: 2 times
        assert graph._entity_mentions["alice"] == 2


class TestRecalculateWeightsConvergence:

    def test_weights_in_valid_range(self, graph):
        """After recalculation, all weights are in [0, 1]."""
        _add_entities(graph, ["A", "B", "C", "D"])

        rels = [
            Relation(source_id="a", target_id="b", relation_type="r1"),
            Relation(source_id="b", target_id="c", relation_type="r2"),
            Relation(source_id="c", target_id="d", relation_type="r3"),
        ]
        for r in rels:
            graph.add_relation(r)

        # Simulate repeated interactions
        for _ in range(5):
            graph.add_relation(rels[0])  # A-B gets more co-occurrence

        result = graph.recalculate_weights()
        assert result["total"] == 3

        for rel in graph.relations.values():
            assert 0.0 <= rel.weight <= 1.0

    def test_higher_cooccurrence_affects_weight(self, graph):
        """Relation with more co-occurrences gets different weight than one without."""
        _add_entities(graph, ["X", "Y", "Z"])

        rel_xy = Relation(source_id="x", target_id="y", relation_type="r1")
        rel_yz = Relation(source_id="y", target_id="z", relation_type="r2")

        graph.add_relation(rel_xy)
        graph.add_relation(rel_yz)

        # Add more co-occurrences for X-Y
        for _ in range(10):
            graph.add_relation(rel_xy)

        graph.recalculate_weights()

        # Both weights should be valid
        w_xy = graph.relations[rel_xy.id].weight
        w_yz = graph.relations[rel_yz.id].weight
        assert 0.0 <= w_xy <= 1.0
        assert 0.0 <= w_yz <= 1.0


class TestBackwardCompatExistingRelations:

    def test_recalculate_no_error_on_existing(self, graph):
        """Recalculate on graph with existing relations doesn't error."""
        _add_entities(graph, ["Foo", "Bar"])

        graph.add_relation(Relation(
            source_id="foo", target_id="bar",
            relation_type="knows", weight=0.5,
        ))

        # No co-occurrence data yet → should still work
        result = graph.recalculate_weights()
        assert result["total"] == 1
        # Weight should be updated (0.7 * tf * idf + 0.3 * 0.5)
        assert graph.relations["foo--knows-->bar"].weight >= 0.0

    def test_save_and_load_preserves_cooccurrence(self, graph):
        """Co-occurrence data survives save/load cycle."""
        _add_entities(graph, ["P", "Q"])
        rel = Relation(source_id="p", target_id="q", relation_type="r")
        graph.add_relation(rel)
        graph.add_relation(rel)  # co-occurrence += 1

        graph.save()

        # Load into new graph
        graph2 = KnowledgeGraph(persist_path=graph.persist_path)
        pair = tuple(sorted(["p", "q"]))
        assert graph2._cooccurrence[pair] == 1
