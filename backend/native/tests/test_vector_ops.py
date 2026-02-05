"""Tests for native vector operations module."""

import math
import pytest
import numpy as np

try:
    import axnmihn_native as native
    HAS_NATIVE = True
except ImportError:
    native = None
    HAS_NATIVE = False


def python_cosine_similarity(a: list, b: list) -> float:
    """Pure Python cosine similarity for verification."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return dot / (norm_a * norm_b)


@pytest.mark.skipif(not HAS_NATIVE, reason="Native module not available")
class TestCosineSimilarity:
    """Test cosine similarity calculations."""

    def test_identical_vectors(self):
        """Test similarity of identical vectors is 1."""
        vec = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = native.vector_ops.cosine_similarity(vec, vec)
        assert abs(result - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        """Test similarity of orthogonal vectors is 0."""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        result = native.vector_ops.cosine_similarity(a, b)
        assert abs(result) < 1e-6

    def test_opposite_vectors(self):
        """Test similarity of opposite vectors is -1."""
        a = [1.0, 2.0, 3.0]
        b = [-1.0, -2.0, -3.0]
        result = native.vector_ops.cosine_similarity(a, b)
        assert abs(result - (-1.0)) < 1e-6

    def test_matches_python(self):
        """Test native matches Python implementation."""
        np.random.seed(42)
        for _ in range(10):
            dim = np.random.randint(10, 1000)
            a = np.random.randn(dim).tolist()
            b = np.random.randn(dim).tolist()

            native_result = native.vector_ops.cosine_similarity(a, b)
            python_result = python_cosine_similarity(a, b)

            assert abs(native_result - python_result) < 1e-6


@pytest.mark.skipif(not HAS_NATIVE, reason="Native module not available")
class TestCosineSimilarityBatch:
    """Test batch cosine similarity."""

    def test_batch_matches_single(self):
        """Test batch results match individual calculations."""
        np.random.seed(42)
        dim = 768
        n_vectors = 100

        query = np.random.randn(dim).astype(np.float64)
        corpus = np.random.randn(n_vectors, dim).astype(np.float64)

        batch_results = native.vector_ops.cosine_similarity_batch(query, corpus)

        for i in range(n_vectors):
            single = native.vector_ops.cosine_similarity(query.tolist(), corpus[i].tolist())
            assert abs(batch_results[i] - single) < 1e-6, f"Mismatch at index {i}"

    def test_typical_embedding_dimension(self):
        """Test with typical embedding dimensions (768, 1024, 1536)."""
        for dim in [768, 1024, 1536]:
            query = np.random.randn(dim).astype(np.float64)
            corpus = np.random.randn(50, dim).astype(np.float64)

            results = native.vector_ops.cosine_similarity_batch(query, corpus)
            assert len(results) == 50


@pytest.mark.skipif(not HAS_NATIVE, reason="Native module not available")
class TestFindDuplicates:
    """Test duplicate finding by embedding similarity."""

    def test_finds_identical_vectors(self):
        """Test that identical vectors are found as duplicates."""
        embeddings = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0],  # Duplicate of first
        ], dtype=np.float64)

        duplicates = native.vector_ops.find_duplicates_by_embedding(embeddings, 0.99)

        # Should find (0, 2) as duplicates
        assert len(duplicates) == 1
        i, j, sim = duplicates[0]
        assert (i, j) == (0, 2)
        assert abs(sim - 1.0) < 1e-6

    def test_threshold_filtering(self):
        """Test that threshold correctly filters results."""
        np.random.seed(42)
        embeddings = np.random.randn(10, 50).astype(np.float64)

        high_threshold = native.vector_ops.find_duplicates_by_embedding(embeddings, 0.99)
        low_threshold = native.vector_ops.find_duplicates_by_embedding(embeddings, 0.5)

        assert len(low_threshold) >= len(high_threshold)

    def test_empty_embeddings(self):
        """Test with empty input."""
        embeddings = np.array([], dtype=np.float64).reshape(0, 10)
        duplicates = native.vector_ops.find_duplicates_by_embedding(embeddings, 0.9)
        assert duplicates == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
