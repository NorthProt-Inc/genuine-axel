"""Tests for GraphRAGConfig dataclass."""


class TestGraphRAGConfig:
    """GraphRAGConfig should centralize magic numbers from graph_rag.py."""

    def test_default_max_entities(self):
        from backend.memory.graph_rag import GraphRAGConfig

        cfg = GraphRAGConfig()
        assert cfg.max_entities == 5

    def test_default_max_depth(self):
        from backend.memory.graph_rag import GraphRAGConfig

        cfg = GraphRAGConfig()
        assert cfg.max_depth == 2

    def test_default_max_relations(self):
        from backend.memory.graph_rag import GraphRAGConfig

        cfg = GraphRAGConfig()
        assert cfg.max_relations == 10

    def test_default_max_paths(self):
        from backend.memory.graph_rag import GraphRAGConfig

        cfg = GraphRAGConfig()
        assert cfg.max_paths == 5

    def test_default_importance_threshold(self):
        from backend.memory.graph_rag import GraphRAGConfig

        cfg = GraphRAGConfig()
        assert cfg.importance_threshold == 0.6

    def test_default_weight_increment(self):
        from backend.memory.graph_rag import GraphRAGConfig

        cfg = GraphRAGConfig()
        assert cfg.weight_increment == 0.1

    def test_custom_values(self):
        from backend.memory.graph_rag import GraphRAGConfig

        cfg = GraphRAGConfig(max_entities=10, max_depth=3, max_paths=8)
        assert cfg.max_entities == 10
        assert cfg.max_depth == 3
        assert cfg.max_paths == 8

    def test_frozen(self):
        from backend.memory.graph_rag import GraphRAGConfig
        import pytest

        cfg = GraphRAGConfig()
        with pytest.raises(AttributeError):
            cfg.max_entities = 99
