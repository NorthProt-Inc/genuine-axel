"""Shared utilities, constants, and configuration for GraphRAG."""

from dataclasses import dataclass
from backend.core.logging import get_logger

try:
    import aiofiles  # type: ignore[import-untyped]  # PERF-042: For async file I/O
except ImportError:
    aiofiles = None

_log = get_logger("memory.graph")

# T-06: Hybrid NER — graceful spaCy import
try:
    import spacy
    _nlp = spacy.load("en_core_web_sm")
    _HAS_SPACY = True
except (ImportError, OSError):
    _nlp = None
    _HAS_SPACY = False
    _log.debug("spaCy not available, using LLM-only extraction")


@dataclass(frozen=True)
class GraphRAGConfig:
    """Centralized configuration for GraphRAG query parameters."""

    max_entities: int = 5
    max_depth: int = 2
    max_relations: int = 10
    max_paths: int = 5
    importance_threshold: float = 0.6
    weight_increment: float = 0.1
    max_query_entities: int = 3
    max_format_entities: int = 5
    max_format_relations: int = 5


# Try to import native module for optimized graph operations
try:
    import axnmihn_native as _native
    _HAS_NATIVE_GRAPH = True
    _log.debug("Native graph_ops module loaded")
except ImportError:
    _native = None
    _HAS_NATIVE_GRAPH = False

# Minimum entity count to use native BFS (small graphs don't benefit)
_NATIVE_BFS_THRESHOLD = 100

# Entity stopwords (filter CONCEPT-type entities with these names)
ENTITY_STOPWORDS = frozenset({
    "the", "a", "an", "this", "that", "it", "is", "was", "are", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "must", "shall",
    "not", "no", "yes", "and", "or", "but", "if", "then", "else",
    "he", "she", "they", "we", "i", "you", "me", "us", "him", "her",
    "그", "이", "저", "것", "그것", "이것",
})
