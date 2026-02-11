"""GraphRAG - Knowledge graph-based memory system for Axel.

This package provides a graph-based memory system that extracts entities and
relationships from conversations and enables semantic querying.
"""

from .knowledge_graph import (
    Entity,
    Relation,
    GraphQueryResult,
    KnowledgeGraph,
)
from .utils import GraphRAGConfig, _HAS_SPACY, _nlp
from .core import GraphRAG

__all__ = [
    "Entity",
    "Relation",
    "GraphQueryResult",
    "KnowledgeGraph",
    "GraphRAG",
    "GraphRAGConfig",
    "_HAS_SPACY",
    "_nlp",
]
