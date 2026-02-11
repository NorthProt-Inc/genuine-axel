"""Tests for backend.memory.permanent.config — MemoryConfig constants.

Verifies all configuration attributes exist, have correct types,
and respect expected value ranges.
"""

import pytest

from backend.memory.permanent.config import MemoryConfig


class TestMemoryConfigAttributes:
    """Verify all attributes exist and have correct types."""

    def test_flush_threshold_is_positive_int(self):
        assert isinstance(MemoryConfig.FLUSH_THRESHOLD, int)
        assert MemoryConfig.FLUSH_THRESHOLD > 0

    def test_flush_interval_seconds_is_positive(self):
        assert isinstance(MemoryConfig.FLUSH_INTERVAL_SECONDS, (int, float))
        assert MemoryConfig.FLUSH_INTERVAL_SECONDS > 0

    def test_base_decay_rate_in_range(self):
        assert isinstance(MemoryConfig.BASE_DECAY_RATE, float)
        assert 0.0 < MemoryConfig.BASE_DECAY_RATE < 1.0

    def test_min_retention_in_range(self):
        assert isinstance(MemoryConfig.MIN_RETENTION, float)
        assert 0.0 < MemoryConfig.MIN_RETENTION < 1.0

    def test_decay_delete_threshold_in_range(self):
        assert isinstance(MemoryConfig.DECAY_DELETE_THRESHOLD, float)
        assert 0.0 < MemoryConfig.DECAY_DELETE_THRESHOLD < 1.0

    def test_duplicate_threshold_in_range(self):
        assert isinstance(MemoryConfig.DUPLICATE_THRESHOLD, float)
        assert 0.0 < MemoryConfig.DUPLICATE_THRESHOLD <= 1.0

    def test_min_importance_in_range(self):
        assert isinstance(MemoryConfig.MIN_IMPORTANCE, float)
        assert 0.0 <= MemoryConfig.MIN_IMPORTANCE < 1.0

    def test_access_stability_k(self):
        assert isinstance(MemoryConfig.ACCESS_STABILITY_K, float)
        assert MemoryConfig.ACCESS_STABILITY_K > 0

    def test_relation_resistance_k(self):
        assert isinstance(MemoryConfig.RELATION_RESISTANCE_K, float)
        assert MemoryConfig.RELATION_RESISTANCE_K > 0

    def test_reassess_age_hours(self):
        assert isinstance(MemoryConfig.REASSESS_AGE_HOURS, int)
        assert MemoryConfig.REASSESS_AGE_HOURS > 0
        # Default 168 hours = 7 days
        assert MemoryConfig.REASSESS_AGE_HOURS == 168

    def test_reassess_batch_size(self):
        assert isinstance(MemoryConfig.REASSESS_BATCH_SIZE, int)
        assert MemoryConfig.REASSESS_BATCH_SIZE > 0

    def test_decay_rate(self):
        assert isinstance(MemoryConfig.DECAY_RATE, float)
        assert 0.0 < MemoryConfig.DECAY_RATE < 1.0

    def test_min_repetitions(self):
        assert isinstance(MemoryConfig.MIN_REPETITIONS, int)
        assert MemoryConfig.MIN_REPETITIONS >= 1

    def test_similar_threshold(self):
        assert isinstance(MemoryConfig.SIMILAR_THRESHOLD, float)
        assert 0.0 < MemoryConfig.SIMILAR_THRESHOLD <= 1.0

    def test_preserve_repetitions(self):
        assert isinstance(MemoryConfig.PRESERVE_REPETITIONS, int)
        assert MemoryConfig.PRESERVE_REPETITIONS >= 1

    def test_embedding_model_is_string(self):
        assert isinstance(MemoryConfig.EMBEDDING_MODEL, str)
        assert len(MemoryConfig.EMBEDDING_MODEL) > 0

    def test_channel_diversity_k(self):
        assert isinstance(MemoryConfig.CHANNEL_DIVERSITY_K, float)
        assert MemoryConfig.CHANNEL_DIVERSITY_K > 0

    def test_embedding_dimension(self):
        assert isinstance(MemoryConfig.EMBEDDING_DIMENSION, int)
        assert MemoryConfig.EMBEDDING_DIMENSION > 0

    def test_embedding_cache_size(self):
        assert isinstance(MemoryConfig.EMBEDDING_CACHE_SIZE, int)
        assert MemoryConfig.EMBEDDING_CACHE_SIZE > 0


class TestMemoryConfigRelationships:
    """Verify relationships between config values make sense."""

    def test_decay_delete_below_min_retention(self):
        """Decay delete threshold should be below min retention."""
        assert MemoryConfig.DECAY_DELETE_THRESHOLD < MemoryConfig.MIN_RETENTION

    def test_min_importance_below_duplicate_threshold(self):
        """Min importance should be well below the duplicate threshold."""
        assert MemoryConfig.MIN_IMPORTANCE < MemoryConfig.DUPLICATE_THRESHOLD

    def test_similar_threshold_reasonable(self):
        """Similar threshold should be high enough to be meaningful."""
        assert MemoryConfig.SIMILAR_THRESHOLD >= 0.5

    def test_embedding_dimension_standard(self):
        """Embedding dimension should be a standard size."""
        # Common dimensions: 768, 1024, 1536, 3072
        assert MemoryConfig.EMBEDDING_DIMENSION in (768, 1024, 1536, 3072)


class TestMemoryConfigDefaults:
    """Verify specific default values that the system depends on."""

    def test_flush_threshold_default(self):
        assert MemoryConfig.FLUSH_THRESHOLD == 50

    def test_flush_interval_default(self):
        assert MemoryConfig.FLUSH_INTERVAL_SECONDS == 300

    def test_access_stability_k_default(self):
        assert MemoryConfig.ACCESS_STABILITY_K == 0.3

    def test_relation_resistance_k_default(self):
        assert MemoryConfig.RELATION_RESISTANCE_K == 0.1

    def test_decay_rate_default(self):
        assert MemoryConfig.DECAY_RATE == 0.002

    def test_min_repetitions_default(self):
        assert MemoryConfig.MIN_REPETITIONS == 1

    def test_similar_threshold_default(self):
        assert MemoryConfig.SIMILAR_THRESHOLD == 0.75

    def test_preserve_repetitions_default(self):
        assert MemoryConfig.PRESERVE_REPETITIONS == 3

    def test_channel_diversity_k_default(self):
        assert MemoryConfig.CHANNEL_DIVERSITY_K == 0.2

    def test_embedding_cache_size_default(self):
        assert MemoryConfig.EMBEDDING_CACHE_SIZE == 256
