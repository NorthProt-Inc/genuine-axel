"""Pytest fixtures for memory module tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from typing import Dict, List, Any
from datetime import datetime
from zoneinfo import ZoneInfo

VANCOUVER_TZ = ZoneInfo("America/Vancouver")


@pytest.fixture
def mock_chromadb_collection():
    """Mock ChromaDB collection for repository tests."""
    collection = MagicMock()
    collection.count.return_value = 0
    collection.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": [],
        "embeddings": [],
    }
    collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    collection.add.return_value = None
    collection.update.return_value = None
    collection.delete.return_value = None
    return collection


@pytest.fixture
def mock_chromadb_client(mock_chromadb_collection):
    """Mock ChromaDB client."""
    client = MagicMock()
    client.get_or_create_collection.return_value = mock_chromadb_collection
    return client


@pytest.fixture
def mock_genai_wrapper():
    """Mock GenerativeModelWrapper for embedding tests."""
    wrapper = MagicMock()

    # Mock embedding result
    mock_embedding_result = MagicMock()
    mock_embedding_value = MagicMock()
    mock_embedding_value.values = [0.1] * 768  # 768-dim embedding
    mock_embedding_result.embeddings = [mock_embedding_value]

    wrapper.embed_content_sync.return_value = mock_embedding_result
    return wrapper


@pytest.fixture
def sample_embedding() -> List[float]:
    """Sample 768-dimensional embedding vector."""
    return [0.1] * 768


@pytest.fixture
def sample_memories() -> List[Dict[str, Any]]:
    """Sample memory data for testing."""
    now = datetime.now(VANCOUVER_TZ).isoformat()
    return [
        {
            "id": "mem-001",
            "content": "User's name is Alice",
            "metadata": {
                "type": "fact",
                "importance": 0.9,
                "repetitions": 3,
                "created_at": now,
                "last_accessed": now,
                "access_count": 5,
            },
        },
        {
            "id": "mem-002",
            "content": "User prefers dark mode",
            "metadata": {
                "type": "preference",
                "importance": 0.7,
                "repetitions": 2,
                "created_at": now,
                "last_accessed": now,
                "access_count": 2,
            },
        },
        {
            "id": "mem-003",
            "content": "Discussed Python async patterns",
            "metadata": {
                "type": "conversation",
                "importance": 0.5,
                "repetitions": 1,
                "created_at": now,
                "last_accessed": now,
                "access_count": 1,
            },
        },
    ]


@pytest.fixture
def populated_chromadb_collection(mock_chromadb_collection, sample_memories):
    """ChromaDB collection pre-populated with sample memories."""
    ids = [m["id"] for m in sample_memories]
    documents = [m["content"] for m in sample_memories]
    metadatas = [m["metadata"] for m in sample_memories]

    mock_chromadb_collection.count.return_value = len(sample_memories)
    mock_chromadb_collection.get.return_value = {
        "ids": ids,
        "documents": documents,
        "metadatas": metadatas,
        "embeddings": None,
    }

    return mock_chromadb_collection


@pytest.fixture
def mock_rate_limiter():
    """Mock rate limiter for embedding service."""
    limiter = MagicMock()
    limiter.try_acquire.return_value = True
    return limiter


@pytest.fixture
def mock_graph_rag():
    """Mock GraphRAG for connection count tests."""
    graph = MagicMock()
    graph.get_connection_count.return_value = 0
    return graph
