"""W6-1: Test importance weight in retrieval scoring."""

from unittest.mock import MagicMock


from backend.memory.permanent.retrieval import MemoryRetriever


def _make_retriever(results, meta_memory=None):
    """Build retriever with mock dependencies."""
    repo = MagicMock()
    repo.query_by_embedding.return_value = results

    embedding_service = MagicMock()
    embedding_service.get_embedding.return_value = [0.1] * 3072

    decay_calc = MagicMock()
    decay_calc.calculate.return_value = 0.9  # fixed decay

    return MemoryRetriever(
        repository=repo,
        embedding_service=embedding_service,
        decay_calculator=decay_calc,
        meta_memory=meta_memory,
    )


def test_importance_weight_boosts_high_importance():
    """High importance memory should score higher than low importance."""
    results = [
        {
            "id": "high-imp",
            "content": "Important fact",
            "metadata": {"importance": 0.9, "created_at": "2025-01-01T00:00:00"},
            "similarity": 0.8,
        },
        {
            "id": "low-imp",
            "content": "Minor detail",
            "metadata": {"importance": 0.3, "created_at": "2025-01-01T00:00:00"},
            "similarity": 0.8,
        },
    ]
    retriever = _make_retriever(results)
    memories = retriever.query("test query")

    scores = {m["id"]: m["effective_score"] for m in memories}
    assert scores["high-imp"] > scores["low-imp"], \
        "Higher importance should result in higher effective_score"


def test_importance_weight_default_for_missing():
    """Memory without importance metadata should use default weight."""
    results = [
        {
            "id": "no-imp",
            "content": "No importance",
            "metadata": {"created_at": "2025-01-01T00:00:00"},
            "similarity": 0.8,
        },
    ]
    retriever = _make_retriever(results)
    memories = retriever.query("test query")

    assert len(memories) == 1
    # Default importance 0.5 → weight should be applied
    assert memories[0]["effective_score"] > 0, "should have positive score"


def test_importance_weight_range_normalization():
    """Importance weight should be in 0.5-1.0 range."""
    results = [
        {
            "id": "very-low",
            "content": "Very low importance",
            "metadata": {"importance": 0.1, "created_at": "2025-01-01T00:00:00"},
            "similarity": 0.8,
        },
        {
            "id": "max-imp",
            "content": "Maximum importance",
            "metadata": {"importance": 1.0, "created_at": "2025-01-01T00:00:00"},
            "similarity": 0.8,
        },
    ]
    retriever = _make_retriever(results)
    memories = retriever.query("test query")

    for m in memories:
        # importance_weight should be between 0.5 and 1.0
        base_score = 0.8 * 0.9  # similarity * decay
        assert m["effective_score"] >= base_score * 0.5, \
            "minimum weight should be 0.5"
        assert m["effective_score"] <= base_score * 1.0 + 0.01, \
            "maximum weight should be 1.0"


def test_importance_weight_in_result_metadata():
    """Query result should include importance_weight field."""
    results = [
        {
            "id": "test",
            "content": "Test",
            "metadata": {"importance": 0.7, "created_at": "2025-01-01T00:00:00"},
            "similarity": 0.8,
        },
    ]
    retriever = _make_retriever(results)
    memories = retriever.query("test query")

    assert "importance_weight" in memories[0], \
        "result should include importance_weight field"
